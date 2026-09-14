"""Emit only timestamps and a fixed allowlist of startup event messages."""
import json
from pathlib import Path

ROOT = Path(__file__).parent
ALLOW = {
    "agent initialized",
    "auth initialize refreshed auth state",
    "built auth_methods",
    "model catalog fetch/retry succeeded",
    "notifying clients",
    "auth update enrichment done",
}
summary = {"schema": "allowlisted-native-log-summary-v1", "allowlist": sorted(ALLOW), "variants": {}}
for variant in ("A", "B"):
    log = ROOT / variant / "home" / "logs" / "unified.jsonl"
    events, malformed = [], 0
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        message = next((item.get(key) for key in ("message", "msg", "event")
                        if item.get(key) in ALLOW), None)
        if message is not None:
            events.append({"timestamp": item.get("timestamp"), "message": message})
    summary["variants"][variant] = {"allowlisted_events": events, "malformed_lines": malformed}
(ROOT / "allowlisted-log-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
