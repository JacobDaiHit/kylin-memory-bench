"""Offline financial guard/transport checks; these never contact a provider."""
import importlib.util
import concurrent.futures
import threading
import urllib.error
import urllib.request
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("live_deepseek", Path(__file__).parents[1] / "scripts/live_deepseek.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class LiveGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = self.root / "test.env"
        env.write_text('UNRELATED=ignore\nTEST_KEY="synthetic-test-key"\n', encoding="utf-8")
        self.args = SimpleNamespace(env_file=str(env), key_name="TEST_KEY", budget_cny=10,
            request_limit=2, audit=str(self.root/"audit.jsonl"), ledger=str(self.root/"ledger.json"))
        balance = patch.object(live.Service, "balance", return_value=live.D("18.06"))
        balance.start()
        self.addCleanup(balance.stop)
        self.service = live.Service(self.args)

    def request(self, **kw):
        return {"model": live.MODEL, "messages": [{"role": "user", "content": "synthetic"}], **kw}

    def result(self):
        return {"id": "synthetic", "model": live.MODEL, "created": 1,
            "usage": {"prompt_tokens": 1000, "completion_tokens": 20, "prompt_cache_hit_tokens": 900},
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}

    def test_budget_rejects_before_paid_request(self):
        self.service.floor = live.D("18.0599")
        with patch.object(self.service, "remote") as remote:
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                self.service.completion(self.request())
            remote.assert_not_called()

    def test_fixed_model_and_call_count(self):
        with patch.object(self.service, "remote") as remote:
            with self.assertRaisesRegex(ValueError, "fixed benchmark model"):
                self.service.completion(self.request(model="expensive-other-model"))
            self.service.requests = 2
            with self.assertRaisesRegex(ValueError, "request limit"):
                self.service.completion(self.request())
            remote.assert_not_called()

    def test_controls_and_cached_cost_bound(self):
        with patch.object(self.service, "remote", return_value=self.result()) as remote:
            result, stream = self.service.completion(self.request(stream=True, max_tokens=99999))
            payload = remote.call_args.args[1]
            self.assertEqual(payload["max_tokens"], 2048)
            self.assertEqual(payload["thinking"], {"type": "disabled"})
            self.assertEqual(payload["temperature"], 0)
            self.assertFalse(payload["stream"])
            self.assertTrue(stream)
            self.assertEqual(live.D(self.service.ledger["estimated_upper_cny"]), live.D("0.000396"))

    def test_failed_request_keeps_reserved_budget(self):
        with patch.object(self.service, "remote", side_effect=RuntimeError("upstream failure")):
            with self.assertRaises(RuntimeError):
                self.service.completion(self.request())
        persisted = json.loads(Path(self.args.ledger).read_text())
        self.assertGreater(live.D(persisted["estimated_upper_cny"]), 0)
        self.assertEqual(persisted["completed_requests"], 0)

    def test_postflight_balance_failure_preserves_paid_response_and_next_call_still_checks_budget(self):
        with patch.object(self.service, "remote", return_value=self.result()) as remote, patch.object(self.service, "balance", side_effect=[live.D("18.06"), RuntimeError("synthetic-test-key unavailable")]):
            result, stream = self.service.completion(self.request())
            self.assertEqual(result, self.result())
            self.assertEqual(remote.call_count, 1)
        persisted = json.loads(Path(self.args.ledger).read_text())
        self.assertEqual(persisted["completed_requests"], 1)
        self.assertEqual(live.D(persisted["estimated_upper_cny"]), live.D("0.000396"))
        records = [json.loads(x) for x in Path(self.args.audit).read_text().splitlines()]
        self.assertEqual(sum(r["event"] == "completion" for r in records), 1)
        self.assertTrue(records[-1]["model_response_preserved"])
        self.assertNotIn("synthetic-test-key", Path(self.args.audit).read_text())
        with patch.object(self.service, "balance", side_effect=RuntimeError("offline")), patch.object(self.service, "remote") as remote:
            with self.assertRaisesRegex(RuntimeError, "offline"):
                self.service.completion(self.request())
            remote.assert_not_called()

    def test_existing_ledger_is_not_reset(self):
        self.service.ledger["estimated_upper_cny"] = "3.5"
        live.save(self.args.ledger, self.service.ledger)
        second = live.Service(self.args)
        self.assertEqual(second.ledger["estimated_upper_cny"], "3.5")
        self.assertEqual(second.floor, live.D("8.06"))

    def test_additional_period_preserves_history_and_limits_estimate_and_balance(self):
        self.service.ledger["estimated_upper_cny"] = "20"
        live.save(self.args.ledger, self.service.ledger)
        self.args.budget_cny = 25
        self.args.additional_budget_cny = 5
        period = live.Service(self.args)
        self.assertEqual(period.ledger["estimated_upper_cny"], "20")
        self.assertEqual(period.period_estimated_start, live.D("20"))
        self.assertEqual(period.floor, live.D("13.06"))
        self.assertEqual(len(period.ledger["budget_periods"]), 1)
        with patch.object(period, "remote", return_value=self.result()) as remote:
            period.completion(self.request())
            self.assertEqual(remote.call_count, 1)
        period.ledger["estimated_upper_cny"] = "24.999999"
        with patch.object(period, "remote") as remote:
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                period.completion(self.request())
            remote.assert_not_called()
        period.ledger["estimated_upper_cny"] = "20"
        with patch.object(period, "balance", return_value=live.D("13.060001")), patch.object(period, "remote") as remote:
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                period.completion(self.request())
            remote.assert_not_called()

    def test_sse_carries_tool_arguments_and_usage(self):
        result = self.result()
        result["choices"][0]["message"] = {"role": "assistant", "content": None,
            "tool_calls": [{"id": "call1", "type": "function", "function": {"name": "memory", "arguments": '{"v":1}'}}]}
        result["choices"][0]["finish_reason"] = "tool_calls"
        data = live.sse(result).decode()
        rows = [json.loads(line[6:]) for line in data.splitlines() if line.startswith("data: {")]
        self.assertEqual(rows[0]["choices"][0]["delta"]["tool_calls"][0]["index"], 0)
        self.assertEqual(rows[-1]["usage"], result["usage"])
        self.assertTrue(data.endswith("data: [DONE]\n\n"))

    def test_budget_lock_excludes_concurrent_experiments_and_releases(self):
        with live.budget_lock(self.args.ledger):
            with self.assertRaisesRegex(ValueError, 'Another live experiment'):
                with live.budget_lock(self.args.ledger):
                    self.fail('second lock acquired')
        with live.budget_lock(self.args.ledger):
            pass

    def test_http_transport_preserves_retryable_upstream_status(self):
        server = live.server_for(self.service)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for failure, expected in ((TimeoutError("synthetic-test-key timeout"), 504),
                                      (live.UpstreamFailure(429, "rate limited"), 429),
                                      (ValueError("budget exhausted"), 400)):
                with patch.object(self.service, "completion", side_effect=failure):
                    request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/v1/chat/completions",
                        data=json.dumps(self.request()).encode(),
                        headers={"Authorization": "Bearer " + self.service.token, "Content-Type": "application/json"})
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request, timeout=5)
                    self.assertEqual(caught.exception.code, expected)
                    self.assertNotIn("synthetic-test-key", caught.exception.read().decode())
        finally:
            server.shutdown()
            server.server_close()
        self.assertNotIn(self.service.token, Path(self.args.audit).read_text())

    def test_parallel_calls_settle_without_losing_other_reservations(self):
        self.args.request_limit = 4
        gate = threading.Barrier(4)
        def remote(*args):
            gate.wait(timeout=5)
            return self.result()
        with patch.object(self.service, "remote", side_effect=remote):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(self.service.completion, self.request()) for _ in range(4)]
                self.assertTrue(all(f.result(timeout=10)[0] == self.result() for f in futures))
        self.assertEqual(self.service.ledger["completed_requests"], 4)
        self.assertEqual(self.service.requests, 4)
        self.assertEqual(self.service.pending_reserves, 0)
        self.assertEqual(live.D(self.service.ledger["estimated_upper_cny"]), live.D("0.001584"))
        audit = [json.loads(line) for line in Path(self.args.audit).read_text().splitlines()]
        self.assertEqual(sum(r["event"] == "completion" for r in audit), 4)

    def test_inflight_call_cannot_allocate_the_same_account_budget_twice(self):
        entered, release = threading.Event(), threading.Event()
        self.service.floor = live.D("18.01")
        def remote(*args):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("Test did not release pending request")
            return self.result()
        with patch.object(self.service, "remote", side_effect=remote) as remote_mock:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(self.service.completion, self.request())
                try:
                    self.assertTrue(entered.wait(timeout=5))
                    with self.assertRaisesRegex(ValueError, "budget exhausted"):
                        self.service.completion(self.request())
                    self.assertEqual(remote_mock.call_count, 1)
                finally:
                    release.set()
                first.result(timeout=5)
        self.assertEqual(self.service.pending_reserves, 0)

    def test_parallel_failure_retains_unknown_usage_reserve(self):
        gate = threading.Barrier(2)
        def remote(path, body):
            gate.wait(timeout=5)
            if body["messages"][0]["content"] == "failure":
                raise TimeoutError("upstream timeout")
            return self.result()
        with patch.object(self.service, "remote", side_effect=remote):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                success = pool.submit(self.service.completion, self.request())
                failure = pool.submit(self.service.completion,
                    self.request(messages=[{"role":"user","content":"failure"}]))
                success.result(timeout=10)
                with self.assertRaises(TimeoutError):failure.result(timeout=10)
        self.assertEqual(self.service.pending_reserves, 0)
        self.assertEqual(self.service.ledger["completed_requests"], 1)
        self.assertGreater(live.D(self.service.ledger["estimated_upper_cny"]), live.D("0.000396"))
        persisted = json.loads(Path(self.args.ledger).read_text())
        self.assertEqual(persisted["estimated_upper_cny"], self.service.ledger["estimated_upper_cny"])

    def test_audit_contains_no_credentials_or_prompt(self):
        with patch.object(self.service, "remote", return_value=self.result()):
            self.service.completion(self.request())
        audit = Path(self.args.audit).read_text()
        self.assertNotIn("synthetic-test-key", audit)
        self.assertNotIn(self.service.token, audit)
        self.assertNotIn('"messages"', audit)

    def test_cached_balance_removes_per_completion_lookups(self):
        self.service.balance_interval = 30
        with patch.object(self.service, 'balance', side_effect=AssertionError('No refresh needed')) as balance, patch.object(self.service, 'remote', return_value=self.result()) as remote:
            self.service.completion(self.request())
            self.service.completion(self.request())
            balance.assert_not_called()
            self.assertEqual(remote.call_count, 2)

    def test_stale_balance_failure_blocks_calls_and_does_not_queue_refreshes(self):
        self.service.balance_interval = 30
        self.service.balance_checked_mono -= 31
        with patch.object(self.service, 'balance', side_effect=TimeoutError('synthetic-test-key offline')) as balance, patch.object(self.service, 'remote') as remote:
            for _ in range(2):
                with self.assertRaises(live.UpstreamFailure) as error:
                    self.service.completion(self.request())
                self.assertEqual(error.exception.status, 503)
            self.assertEqual(balance.call_count, 1)
            remote.assert_not_called()
        self.assertEqual(self.service.requests, 0)
        self.assertNotIn('synthetic-test-key', self.service.audit.read_text())

    def test_unknown_usage_remains_protected_between_cached_requests(self):
        self.service.balance_interval = 30
        self.service.max_output = 1024
        self.service.additional_budget = live.D('0.03')
        response=self.result();response['usage']={}
        with patch.object(self.service, 'remote', return_value=response) as remote:
            self.service.completion(self.request())
            with self.assertRaisesRegex(ValueError,'budget exhausted'):
                self.service.completion(self.request())
            self.assertEqual(remote.call_count,1)
        self.assertGreater(live.D(self.service.ledger['estimated_upper_cny']),0)

    def test_invalid_provider_usage_cannot_refund_reservation(self):
        result=self.result();result['usage']={'prompt_tokens':-100,'completion_tokens':-20}
        with patch.object(self.service,'remote',return_value=result):
            self.service.completion(self.request())
        self.assertGreater(live.D(self.service.ledger['estimated_upper_cny']),0)
        self.assertEqual(self.service.pending_reserves,0)

    def test_invalid_provider_object_releases_pending_but_keeps_reserve(self):
        with patch.object(self.service,'remote',return_value=[]):
            with self.assertRaises(live.UpstreamFailure):self.service.completion(self.request())
        self.assertEqual(self.service.pending_reserves,0)
        self.assertGreater(live.D(self.service.ledger['estimated_upper_cny']),0)

    def test_http_per_turn_cap_overrides_native_request_with_shared_limit(self):
        self.service.max_output=4096
        server=live.server_for(self.service)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with patch.object(self.service,'remote',return_value=self.result()) as remote:
                for cap in (1024,4096):
                    request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/cap/{cap}/chat/completions',
                        data=json.dumps(self.request(max_tokens=512)).encode(),headers={'Authorization':'Bearer '+self.service.token,'Content-Type':'application/json'})
                    with urllib.request.urlopen(request,timeout=5) as response:
                        self.assertEqual(response.status,200)
                    self.assertEqual(remote.call_args.args[1]['max_tokens'],cap)
        finally:
            server.shutdown();server.server_close()


if __name__ == "__main__":
    unittest.main()
