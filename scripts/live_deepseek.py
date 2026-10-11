"""Bounded DeepSeek live experiments. Credentials never reach the tested agents.

This optional script is separate from the offline benchmark. It fixes the main
model and inference controls for both systems and records those choices. The
loopback bridge is a budget/credential boundary, NOT an agent security sandbox.
"""
import argparse
import contextlib
import datetime
import decimal
import hashlib
import http.server
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

D = decimal.Decimal
MODEL = "deepseek-flash"
API = "https://api.deepseek.com"


def read_key(path, name):
    # Parse assignments as data; never source or execute the supplied .env.
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if m and m[1] == name:
            value = m[2].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in (chr(34), chr(39)):
                value = value[1:-1]
            if not value or any(c.isspace() for c in value):
                raise ValueError("Credential is empty or contains whitespace")
            return value
    raise ValueError("Requested credential variable was not found")


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(8):
        try:
            temporary.replace(path)
            break
        except PermissionError as exc:
            if os.name != 'nt' or getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == 7:
                raise
            time.sleep(.025 * (attempt + 1))


@contextlib.contextmanager
def budget_lock(path):
    """One active experiment per ledger; OS releases the lock after a crash."""
    target = Path(str(path) + '.lock')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('a+b') as file:
        if file.tell() == 0:
            file.write(b'0')
            file.flush()
        file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('Another live experiment owns this budget ledger') from None
        try:
            yield
        finally:
            file.seek(0)
            if os.name == 'nt':
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


class Service:
    def __init__(self, args):
        self.args = args
        self.key = read_key(args.env_file, args.key_name)
        self.token = secrets.token_urlsafe(32)
        self.requests = 0
        self.max_output = 2048
        self.audit = Path(args.audit)
        self.audit.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path = Path(args.ledger)
        current = self.balance()
        if self.ledger_path.exists():
            self.ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            if self.ledger.get("model") != MODEL:
                raise ValueError("Budget ledger model mismatch")
        else:
            self.ledger = {"started_at": now(), "initial_balance_cny": str(current),
                           "model": MODEL, "estimated_upper_cny": "0", "completed_requests": 0}
        self.floor = D(self.ledger["initial_balance_cny"]) - D(str(args.budget_cny))
        self.ledger["budget_cny"] = str(args.budget_cny)
        self.ledger["minimum_balance_cny"] = str(self.floor)
        self.ledger["last_balance_cny"] = str(current)
        save(self.ledger_path, self.ledger)
        self.log({"event": "start", "balance_cny": str(current), "floor_cny": str(self.floor),
                  "model": MODEL, "thinking": "disabled", "temperature": 0,
                  "max_output_tokens": self.max_output, "request_limit": args.request_limit,
                  "stream_transport": "buffered upstream response converted to SSE when requested",
                  "price_bound_cny_per_million": {"input_cache_miss": 2, "input_cache_hit": 0.04, "output": 8}})

    def log(self, item):
        # Audit only metadata/usage: no prompts, response text, headers or credentials.
        with self.audit.open("a", encoding="utf-8") as file:
            file.write(json.dumps({"at": now(), **item}, ensure_ascii=False) + "\n")

    def remote(self, path, data=None):
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode()
        request = urllib.request.Request(API + path, data=body,
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10 if path == "/user/balance" else 150) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # A bounded provider error is redacted before reaching local logs.
            raw = exc.read(4096).decode("utf-8", "replace").replace(self.key, "[REDACTED]")
            raise RuntimeError("DeepSeek HTTP " + str(exc.code) + ": " + raw) from None
        except urllib.error.URLError:
            raise RuntimeError("DeepSeek network request failed") from None

    def balance(self):
        value = self.remote("/user/balance")
        for row in value.get("balance_infos", []):
            if row.get("currency") == "CNY":
                return D(row["total_balance"])
        raise ValueError("A CNY balance is required for this budget guard")

    def refresh_balance(self, context):
        # A failed post-flight lookup must not discard an already-paid model result.
        try:
            value = self.balance()
        except Exception as exc:
            detail = str(exc).replace(self.key, "[REDACTED]").replace(self.token, "[REDACTED]")[:1024]
            self.log({"event": "balance_check_failed", "context": context, "reason": detail,
                      "model_response_preserved": context == "after-completion"})
            return False
        self.ledger["last_balance_cny"] = str(value)
        self.ledger["balance_checked_at"] = now()
        if context == "finished":
            self.ledger["final_balance_checked_at"] = self.ledger["balance_checked_at"]
        save(self.ledger_path, self.ledger)
        self.log({"event": "balance_checked", "context": context, "balance_cny": str(value)})
        return True

    def completion(self, body):
        if body.get("model") != MODEL:
            raise ValueError("Only the fixed benchmark model is allowed")
        if self.requests >= self.args.request_limit:
            raise ValueError("Live request limit reached")
        stream = bool(body.get("stream"))
        body = dict(body)
        body.pop("stream_options", None)
        body.pop("max_completion_tokens", None)
        body["stream"] = False
        body["max_tokens"] = min(int(body.get("max_tokens") or self.max_output), self.max_output)
        if body["max_tokens"] <= 0:
            raise ValueError("Invalid output limit")
        body["thinking"] = {"type": "disabled"}
        body["temperature"] = 0
        raw = json.dumps(body, ensure_ascii=False).encode()
        if len(raw) > 1024 * 1024:
            raise ValueError("Live request exceeds 1 MiB")
        # UTF-8 bytes plus protocol margin intentionally overestimate input tokens.
        reserve = (D(len(raw) + 8192) * 2 + D(body["max_tokens"]) * 8) / 1000000
        balance = self.balance()
        estimated = D(self.ledger["estimated_upper_cny"])
        if balance - reserve < self.floor or estimated + reserve > D(str(self.args.budget_cny)):
            self.log({"event": "budget_stop", "balance_cny": str(balance), "reserve_cny": str(reserve)})
            raise ValueError("Live budget exhausted; no upstream completion was sent")
        # Reserve BEFORE sending, retaining the bound if interrupted or usage missing.
        self.ledger["estimated_upper_cny"] = str(estimated + reserve)
        save(self.ledger_path, self.ledger)
        self.requests += 1
        started = now()
        result = self.remote("/chat/completions", body)
        usage = result.get("usage", {})
        if isinstance(usage.get("prompt_tokens"), int) and isinstance(usage.get("completion_tokens"), int):
            cached = usage.get("prompt_cache_hit_tokens", 0)
            if type(cached) is not int or not 0 <= cached <= usage["prompt_tokens"]:
                cached = 0
            cost = (D(usage["prompt_tokens"] - cached) * 2 + D(cached) * D("0.04")
                    + D(usage["completion_tokens"]) * 8) / 1000000
            self.ledger["estimated_upper_cny"] = str(estimated + cost)
        self.ledger["completed_requests"] += 1
        save(self.ledger_path, self.ledger)
        self.log({"event": "completion", "started_at": started, "model": result.get("model"),
                  "request_sha256": hashlib.sha256(raw).hexdigest(), "usage": usage,
                  "finish_reasons": [c.get("finish_reason") for c in result.get("choices", [])],
                  "balance_before_cny": str(balance)})
        self.refresh_balance("after-completion")
        return result, stream


def sse(result):
    chunks = []
    base = {key: result[key] for key in ("id", "created", "model") if key in result}
    base["object"] = "chat.completion.chunk"
    for choice in result.get("choices", []):
        message = dict(choice.get("message", {}))
        for i, tool in enumerate(message.get("tool_calls", [])):
            tool["index"] = i
        chunks.append({**base, "choices": [{"index": choice.get("index", 0), "delta": message,
                                         "finish_reason": None}]})
        chunks.append({**base, "choices": [{"index": choice.get("index", 0), "delta": {},
                                         "finish_reason": choice.get("finish_reason", "stop")}]})
    chunks.append({**base, "choices": [], "usage": result.get("usage", {})})
    return ("".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def server_for(service):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, status, data, content_type="application/json"):
            raw = data if isinstance(data, bytes) else json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                self.wfile.write(raw)

        def authorized(self):
            return secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + service.token)

        def do_GET(self):
            if not self.authorized():
                return self.reply(401, {"error": {"message": "Unauthorized"}})
            if self.path not in ("/models", "/v1/models"):
                return self.reply(404, {"error": {"message": "Unsupported path"}})
            return self.reply(200, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "deepseek"}]})

        def do_POST(self):
            if not self.authorized():
                return self.reply(401, {"error": {"message": "Unauthorized"}})
            if self.path not in ("/chat/completions", "/v1/chat/completions"):
                return self.reply(404, {"error": {"message": "Unsupported path"}})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 1024 * 1024:
                    raise ValueError("Invalid body length")
                result, stream = service.completion(json.loads(self.rfile.read(size)))
                self.reply(200, sse(result) if stream else result,
                           "text/event-stream" if stream else "application/json")
            except Exception as exc:
                detail = str(exc).replace(service.key, "[REDACTED]").replace(service.token, "[REDACTED]")
                service.log({"event": "rejected", "reason": detail})
                self.reply(400, {"error": {"message": detail, "type": "live_guard"}})
    return http.server.HTTPServer(("127.0.0.1", 0), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--key-name", default="MATHAGENT_DEEPSEEK_API_KEY")
    parser.add_argument("--budget-cny", type=float, default=10)
    parser.add_argument("--request-limit", type=int, default=30)
    parser.add_argument("--ledger", default="runs/deepseek-budget.local.json")
    parser.add_argument("--audit", required=True)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--config")
    parser.add_argument("--output")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--dataset")
    args = parser.parse_args()
    if not math.isfinite(args.budget_cny) or args.budget_cny <= 0 or args.request_limit < 1:
        parser.error("Budget and request limit must be positive")
    if not args.probe and (not args.config or not args.output):
        parser.error('--config and --output are required for a benchmark')
    with budget_lock(args.ledger):
        return execute_live(args)


def execute_live(args):
    service = Service(args)
    if args.probe:
        messages = [{"role": "user", "content": "Use record_memory to store project=alpha and format=Markdown. Then confirm with JSON only."}]
        tools = [{"type": "function", "function": {"name": "record_memory", "description": "Record one project preference",
                  "parameters": {"type": "object", "properties": {"project": {"type": "string"}, "format": {"type": "string"}},
                                 "required": ["project", "format"], "additionalProperties": False}}}]
        first, _ = service.completion({"model": MODEL, "messages": messages, "tools": tools, "max_tokens": 512})
        answer = first["choices"][0]["message"]
        calls = answer.get("tool_calls", [])
        if len(calls) != 1 or calls[0]["function"]["name"] != "record_memory":
            raise ValueError("Tool-call probe did not return the expected function")
        arguments = json.loads(calls[0]["function"]["arguments"])
        if arguments != {"project": "alpha", "format": "Markdown"}:
            raise ValueError("Tool-call arguments do not match the synthetic request")
        messages += [answer, {"role": "tool", "tool_call_id": calls[0]["id"], "content": '{"stored":true}'}]
        second, _ = service.completion({"model": MODEL, "messages": messages, "tools": tools, "max_tokens": 512})
        evidence = {"kind": "api_tool_roundtrip_only_not_agent_benchmark", "at": now(), "model": MODEL,
                    "tool_name": "record_memory", "arguments": arguments,
                    "final": second["choices"][0]["message"]["content"], "usage": [first["usage"], second["usage"]],
                    "balance_cny": str(service.balance())}
        save(Path(args.audit).with_suffix(".probe.json"), evidence)
        print(json.dumps(evidence, ensure_ascii=False))
        return 0
    server = server_for(service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = dict(os.environ)
    env["KMB_PROXY_KEY"] = service.token
    env["KMB_PROXY_BASE_URL"] = f"http://127.0.0.1:{server.server_port}/v1"
    # Config placeholders refer only to a loopback URL and an ephemeral proxy token.
    config_text = Path(args.config).read_text(encoding="utf-8").replace("KMB_PROXY_BASE_URL", env["KMB_PROXY_BASE_URL"])
    config_path = Path(args.audit).with_suffix(".config.local.json")
    config_path.write_text(config_text, encoding="utf-8")
    command = [sys.executable, "-m", "kylin_memory_bench", "run", "--config", str(config_path),
               "--output", args.output, "--repeats", str(args.repeats), "--jobs", str(args.jobs)]
    if args.dataset:
        command += ["--dataset", args.dataset]
    for case in args.case:
        command += ["--case", case]
    try:
        code = subprocess.call(command, env=env)
    finally:
        server.shutdown()
        server.server_close()
        fresh = service.refresh_balance("finished")
        service.log({"event": "finished", "balance_cny": service.ledger["last_balance_cny"], "balance_fresh": fresh})
    print(json.dumps({"requests_this_process": service.requests, "budget": service.ledger}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
