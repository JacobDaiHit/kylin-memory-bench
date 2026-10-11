"""Shared serialization, path containment and atomic IO primitives."""
import hashlib
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path, PurePosixPath, PureWindowsPath

DIMENSIONS = {
    "retention": "长期保持",
    "retrieval": "记忆调用",
    "update": "动态更新",
    "disambiguation": "相近区分",
    "boundary": "边界识别",
    "reuse": "任务复用",
}
ID_RE = re.compile(r"^(?!(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$)[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$", re.IGNORECASE)
MAX_FILE_BYTES = 2 * 1024 * 1024


class BenchError(ValueError):
    """An actionable configuration, protocol or evidence error."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strict_json(text):
    def bad_constant(value):
        raise BenchError("Non-finite JSON number: " + value)

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise BenchError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    try:
        return json.loads(text, parse_constant=bad_constant, object_pairs_hook=pairs)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise BenchError("Invalid JSON: " + str(exc)) from exc


def read_json(path):
    return strict_json(Path(path).read_text(encoding="utf-8-sig"))


def write_text(path, text):
    """Atomic replacement, including on Windows; always UTF-8 and LF."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".kmb-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # Windows indexers/security scanners can briefly hold a non-share-delete handle.
        # Retry only publication of these already-written bytes, never an agent turn.
        for attempt in range(7):
            try:
                os.replace(name, path)
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) not in (5, 32, 33) or attempt == 6:
                    raise
                time.sleep(0.02 * (2 ** attempt))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise BenchError("Expected a non-empty POSIX relative path")
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if posix.is_absolute() or windows.drive or any(p in ("..", ".", "") for p in value.split("/")):
        raise BenchError("Unsafe relative path: " + value)
    reserved = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)
    if any(p.endswith((".", " ")) or reserved.fullmatch(p) or any(c in p for c in ":<>|?*") for p in posix.parts):
        raise BenchError("Path contains a platform-reserved component")
    return value


def contained(root, relative):
    relative_path(relative)
    root = Path(root).resolve()
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise BenchError("Path escapes workspace: " + relative) from exc
    # Reject even internal symlinks: evidence must be an ordinary workspace file.
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise BenchError("Symlink is not accepted as evidence: " + relative)
        cursor = cursor.parent
    return candidate


def positive_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def json_pointer(value, pointer):
    if pointer == "":
        return value
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise BenchError("JSON pointer must be empty or start with /")
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            if not part.isdigit():
                raise KeyError(part)
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(part)
    return value
