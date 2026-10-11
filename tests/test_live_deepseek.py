"""Offline financial guard/transport checks; these never contact a provider."""
import importlib.util
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

    def test_audit_contains_no_credentials_or_prompt(self):
        with patch.object(self.service, "remote", return_value=self.result()):
            self.service.completion(self.request())
        audit = Path(self.args.audit).read_text()
        self.assertNotIn("synthetic-test-key", audit)
        self.assertNotIn(self.service.token, audit)
        self.assertNotIn('"messages"', audit)


if __name__ == "__main__":
    unittest.main()
