import csv
import math
from collections import defaultdict

PATH = "/input/public_csv"
TARGET = "percentage_increase_in_utilitarianism"
NUMERIC = [
    "argument_intensity",
    "audience_interest_level",
    "average_debate_duration",
    "number_of_sessions",
    TARGET,
]

def num(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None

def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None, len(pairs)
    ax = sum(x for x, _ in pairs) / len(pairs)
    ay = sum(y for _, y in pairs) / len(pairs)
    sx = sum((x - ax) ** 2 for x, _ in pairs)
    sy = sum((y - ay) ** 2 for _, y in pairs)
    if sx == 0 or sy == 0:
        return None, len(pairs)
    r = sum((x - ax) * (y - ay) for x, y in pairs) / math.sqrt(sx * sy)
    return r, len(pairs)

def fmt(x):
    return "NA" if x is None else f"{x:.3f}"

with open(PATH, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# Retain records explicitly focused on ethics when a usable topic label exists.
labels = []
for r in rows:
    text = " ".join(str(r.get(k, "")) for k in ("topic_of_debate", "philosophical_topic")).lower()
    if text.strip():
        labels.append("ethic" in text)
ethics_rows = [r for r in rows if "ethic" in (" ".join(str(r.get(k, "")) for k in ("topic_of_debate", "philosophical_topic")).lower())]
use = ethics_rows if ethics_rows else rows
print(f"records={len(rows)}; ethics_records={len(ethics_rows)}; analyzed={len(use)}")

for field in NUMERIC[:-1]:
    r, n = corr([num(x.get(field)) for x in use], [num(x.get(TARGET)) for x in use])
    print(f"correlation {field} vs {TARGET}: r={fmt(r)}, n={n}")

for field in ("moderator_ethical_stance", "critical_event_occurred"):
    groups = defaultdict(list)
    for row in use:
        y = num(row.get(TARGET))
        key = str(row.get(field, "")).strip() or "missing"
        if y is not None:
            groups[key].append(y)
    if not groups:
        print(f"group means by {field}: insufficient target data")
    else:
        parts = []
        for key in sorted(groups):
            vals = groups[key]
            parts.append(f"{key}:n={len(vals)},mean={sum(vals)/len(vals):.3f}")
        print(f"group means by {field}: " + "; ".join(parts))

# Compact conditional summaries for the combination of stance and event.
combo = defaultdict(list)
for row in use:
    y = num(row.get(TARGET))
    if y is not None:
        stance = str(row.get("moderator_ethical_stance", "")).strip() or "missing"
        event = str(row.get("critical_event_occurred", "")).strip() or "missing"
        combo[(stance, event)].append(y)
if combo:
    parts = [f"{s}|{e}:n={len(v)},mean={sum(v)/len(v):.3f}" for (s, e), v in sorted(combo.items())]
    print("stance-by-event means: " + "; ".join(parts))
else:
    print("stance-by-event means: insufficient target data")