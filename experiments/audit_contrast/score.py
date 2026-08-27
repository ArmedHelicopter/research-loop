"""Score audit-contrast JSON against hidden labels. No overall effectiveness."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from experiments.error_catching.score import parse_output

HOLD = frozenset({"withdrawn", "invalid"})
KEEP = frozenset({"proceed", "closed_negative"})
VERDICTS = frozenset({"valid", "invalid"})


def load_label(path: Path) -> dict[str, Any]:
    label = json.loads(path.read_text(encoding="utf-8"))
    for key in ("id", "gold_status", "gold_reason", "violation_if"):
        if key not in label:
            raise ValueError(f"{path} missing {key}")
    return label


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def resolve_fields(output: dict[str, Any]) -> tuple[str, str]:
    verdict = _norm(output.get("audit_verdict") or output.get("verdict"))
    rec = _norm(output.get("recommended_status") or output.get("status"))
    if verdict not in VERDICTS:
        if rec in HOLD:
            verdict = "invalid"
        elif rec in KEEP:
            verdict = "valid"
    return verdict, rec


def score_output(task: dict[str, Any], label: dict[str, Any], raw: str) -> dict[str, Any]:
    try:
        output = parse_output(raw)
        parse_ok = True
        err = None
    except (json.JSONDecodeError, ValueError) as exc:
        output = {}
        parse_ok = False
        err = str(exc)
    verdict, rec = resolve_fields(output) if parse_ok else ("", "")
    gold = str(label["gold_status"]).strip().lower()
    hold = gold in HOLD
    if not parse_ok:
        item_correct = False
    elif hold:
        item_correct = verdict == "invalid" and rec in HOLD and rec not in {"proceed", "complete"}
    elif gold in KEEP:
        item_correct = verdict == "valid" and rec == gold
    else:
        item_correct = False
    over_reject = (not hold) and gold in KEEP and (verdict == "invalid" or rec in HOLD)
    miss = hold and not (verdict == "invalid" and rec in HOLD)
    return {
        "id": task["id"],
        "parse_ok": parse_ok,
        "parse_error": err,
        "audit_verdict": verdict,
        "recommended_status": rec,
        "gold_status": gold,
        "item_correct": bool(item_correct),
        "over_reject": bool(over_reject),
        "miss": bool(miss),
        "hold_out_item": hold,
    }
