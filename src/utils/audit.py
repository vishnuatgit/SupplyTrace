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
