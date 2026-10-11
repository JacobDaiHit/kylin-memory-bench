"""Strict versioned JSONL contract. Gold checks never enter adapter requests."""
from pathlib import Path

from .common import BenchError, DIMENSIONS, ID_RE, digest, positive_number, relative_path, strict_json

SOURCES = {"response", "memory", "actions", "artifact"}
OPS = {"equals", "one_of", "contains", "excludes", "exists", "absent", "json_subset"}
FAILURES = {"omission", "confusion", "stale_memory", "wrong_persistence", "wrong_reuse"}


def _require(condition, message):
    if not condition:
        raise BenchError(message)


def validate_case(case):
    _require(isinstance(case, dict), "case must be an object")
    _require(case.get("schema_version") == "1.0", "schema_version must be 1.0")
    _require(isinstance(case.get("id"), str) and ID_RE.fullmatch(case["id"]), "invalid case id")
    _require(isinstance(case.get("title"), str) and case["title"].strip(), "title is required")
    _require(isinstance(case.get("dimension"), str) and case["dimension"] in DIMENSIONS, "invalid dimension")
    _require(case.get("synthetic") is True, "v1 datasets must explicitly be synthetic=true")
    steps = case.get("steps")
    _require(isinstance(steps, list) and 1 <= len(steps) <= 2000, "steps must contain 1..2000 entries")
    ids, checks, previous_day = set(), set(), -1
    for step in steps:
        _require(isinstance(step, dict), "step must be an object")
        sid = step.get("id")
        _require(isinstance(sid, str) and ID_RE.fullmatch(sid) and sid not in ids, "invalid/duplicate step id")
        ids.add(sid)
        _require(isinstance(step.get("kind"), str) and step["kind"] in {"message", "probe", "task"}, "invalid step kind")
        _require(isinstance(step.get("session"), str) and ID_RE.fullmatch(step["session"]), "invalid session")
        day = step.get("day")
        _require(type(day) is int and day >= 0 and day >= previous_day, "day must be a monotonic nonnegative integer")
        previous_day = day
        _require(isinstance(step.get("prompt"), str) and 0 < len(step["prompt"]) <= 100000, "invalid prompt")
        validations = step.get("checks", [])
        _require(isinstance(validations, list), "checks must be a list")
        for check in validations:
            _require(isinstance(check, dict), "check must be an object")
            cid = check.get("id")
            _require(isinstance(cid, str) and ID_RE.fullmatch(cid) and cid not in checks, "invalid/duplicate check id")
            checks.add(cid)
            source, op = check.get("source"), check.get("op")
            _require(isinstance(source, str) and isinstance(op, str) and source in SOURCES and op in OPS, "invalid check source/op")
            _require(isinstance(check.get("failure"), str) and check["failure"] in FAILURES, "check requires an explicit failure category")
            _require(positive_number(check.get("weight", 1)), "weight must be positive and finite")
            if op not in {"exists", "absent"}:
                _require("value" in check, "check requires value")
            if op in {"contains", "excludes"}:
                _require(isinstance(check["value"], str) and check["value"], "contains/excludes needs nonempty text")
            if op == "json_subset":
                _require(isinstance(check["value"], dict) and bool(check["value"]), "json_subset requires a nonempty object")
            if op == "one_of":
                values = check["value"]
                _require(isinstance(values, list) and 1 <= len(values) <= 32,
                         "one_of requires 1..32 explicitly accepted scalar values")
                _require(all(v is None or type(v) in (str, int, float, bool) for v in values),
                         "one_of accepts JSON scalars only")
            if source == "artifact":
                relative_path(check.get("path"))
            if source == "memory":
                _require(op in {"contains", "excludes"}, "memory supports contains/excludes only")
            if source == "actions":
                _require(op in {"json_subset", "absent"}, "actions supports json_subset/absent only")
            pointer = check.get("pointer", "")
            _require(isinstance(pointer, str) and (not pointer or pointer.startswith("/")), "invalid JSON pointer")
            _require(not pointer or source in {"response", "artifact"}, "pointer requires response/artifact")
    _require(bool(checks), "case must include at least one check")
    _require(len({s["session"] for s in steps}) >= 2, "memory evaluation requires at least two sessions")
    return case


def load_dataset(path):
    cases, ids = [], set()
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = validate_case(strict_json(line))
            _require(case["id"] not in ids, "duplicate case id")
        except BenchError as exc:
            raise BenchError(f"{path}:{line_no}: {exc}") from exc
        ids.add(case["id"])
        cases.append(case)
    _require(bool(cases), "dataset is empty")
    return cases


def describe(cases):
    dimensions = {key: 0 for key in DIMENSIONS}
    sources = {key: 0 for key in SOURCES}
    for case in cases:
        dimensions[case["dimension"]] += 1
        for step in case["steps"]:
            for check in step.get("checks", []):
                sources[check["source"]] += 1
    return {"cases": len(cases), "checks": sum(sources.values()), "dimensions": dimensions,
            "sources": sources, "sha256": digest(cases)}
