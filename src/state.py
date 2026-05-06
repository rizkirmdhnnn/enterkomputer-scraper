import json
from datetime import datetime, timezone
from pathlib import Path


class State:
    """Persists the set of already-scraped URLs to a JSON file for resume support."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._completed: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        self._completed = set(data.get("completed_urls", []))

    def completed_urls(self) -> set[str]:
        return set(self._completed)

    def mark_done(self, url: str) -> None:
        if url in self._completed:
            return
        self._completed.add(url)
        self._flush()

    def _flush(self) -> None:
        payload = {
            "completed_urls": sorted(self._completed),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2))
