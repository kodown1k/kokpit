import json
import time
from pathlib import Path


class AuditLog:
    def __init__(self, path) -> None:
        self.path = Path(path)

    def record(self, event: str, detail: dict) -> None:
        row = {"ts_ms": int(time.time() * 1000), "event": event, "detail": detail}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")

    def tail(self, n: int = 50) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        out = []
        for line in lines[-n:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
