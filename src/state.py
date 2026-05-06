import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class State:
    """Persists the set of already-scraped URLs to a JSON file for resume support.

    Thread-safe: concurrent calls to `mark_done` and `completed_urls` are
    serialized via an internal lock.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._completed: set[str] = set()
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self._completed = set(data.get("completed_urls", []))

    def completed_urls(self) -> set[str]:
        with self._lock:
            return set(self._completed)

    def mark_done(self, url: str) -> None:
        with self._lock:
            if url in self._completed:
                return
            self._completed.add(url)
            self._flush_locked()

    def _flush_locked(self) -> None:
        """Caller must hold self._lock."""
        payload = {
            "completed_urls": sorted(self._completed),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2))
