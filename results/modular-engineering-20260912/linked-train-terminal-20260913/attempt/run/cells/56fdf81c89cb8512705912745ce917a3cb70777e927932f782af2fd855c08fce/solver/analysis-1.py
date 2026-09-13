import csv
import math
import os

PATH = "/input/data.csv"
OUTCOME = "percentage_increase_in_utilitarianism"
NUMERIC = [
    "argument_intensity",
    "audience_interest_level",
    "average_debate_duration",
    "number_of_sessions",
]

def num(value):
    try:
        x = float(str(value).strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None

def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    ax = sum(x for x, _ in pairs) / len(pairs)
    ay = sum(y for _, y in pairs) / len(pairs)
    numr = sum((x - ax) * (y - ay) for x, y in pairs)
    denx = math.sqrt(sum((x - ax) ** 2 for x, _ in pairs))
    deny = math.sqrt(sum((y - ay) ** 2 for _, y in pairs))
    return numr / (denx * deny) if denx and deny else None

def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None

if not os.path.exists(PATH):
    print("data_unavailable: /input/data.csv not found")
else:
    with open(PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("data_unavailable: CSV has no rows")
    else:
        topic_fields = [c for c in ("philosophical_topic", "topic_of_debate") if c in rows[0]]
        if topic_fields:
            ethics_rows = [r for r in rows if any("ethic" in (r.get(c) or "").lower() for c in topic_fields)]
            data = ethics_rows or rows
            scope = "ethics-focused" if ethics_rows else "all rows (no ethics-topic matches)"
        else:
            data, scope = rows, "all rows (topic column unavailable)"
        ys = [num(r.get(OUTCOME)) for r in data]
        print(f"scope={scope}; n={len(data)}; outcome_mean={mean(ys)}")
        for col in NUMERIC:
            r = pearson([num(row.get(col)) for row in data], ys)
            print(f"correlation({col},{OUTCOME})={r}")
        if "moderator_ethical_stance" in data[0]:
            groups = {}
            for row, y in zip(data, ys):
                key = (row.get("moderator_ethical_stance") or "missing").strip()
                groups.setdefault(key, []).append(y)
            for key in sorted(groups):
                print(f"moderator={key}; n={len(groups[key])}; outcome_mean={mean(groups[key])}")
        if "critical_event_occurred" in data[0]:
            groups = {}
            for row, y in zip(data, ys):
                key = (row.get("critical_event_occurred") or "missing").strip()
                groups.setdefault(key, []).append(y)
            for key in sorted(groups):
                print(f"critical_event={key}; n={len(groups[key])}; outcome_mean={mean(groups[key])}")