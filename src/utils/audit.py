import json
import logging
import os

logger = logging.getLogger(__name__)

# About 4,000 entries. The log is then moved to "<name>.1", so it never uses
# much more than twice this on disk.
DEFAULT_MAX_BYTES = 1_000_000


def append_audit_entries(path: str, entries: list, max_bytes: int = DEFAULT_MAX_BYTES) -> bool:
    """
    Appends entries to a JSON Lines audit log, rotating it once it reaches max_bytes.
    Best effort: a failure (e.g. a read-only disk) is logged and reported by
    returning False, never raised, so it cannot break the caller.
    """
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        if max_bytes and os.path.exists(path) and os.path.getsize(path) >= max_bytes:
            os.replace(path, f"{path}.1")
        with open(path, "a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, default=str) + "\n")
        return True
    except Exception as e:
        logger.error(f"Failed to write audit log {path}: {e}")
        return False


def read_audit_entries(path: str) -> list[tuple[dict, str]]:
    """
    Every entry in the audit log, newest first, each with its exact JSON line.
    Lines that are not JSON objects (e.g. half-written) are skipped. A missing
    log reads as empty.
    """
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append((entry, line))
    entries.reverse()
    return entries
