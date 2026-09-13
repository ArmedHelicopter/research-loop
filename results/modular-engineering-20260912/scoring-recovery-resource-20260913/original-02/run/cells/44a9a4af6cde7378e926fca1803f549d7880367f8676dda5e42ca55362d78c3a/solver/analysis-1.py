import csv
import math
import os
import statistics

PATH = "/input/public_csv"
TARGET = "percentage_increase_in_utilitarianism"
NUMERIC = [
    "argument_intensity", "audience_interest_level",
    "average_debate_duration", "number_of_sessions"
]


def num(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def is_ethics(row):
    text = " ".join(str(row.get(k, "")) for k in ("topic_of_debate", "philosophical_topic")).lower()
    return "ethic" in text


def mean(values):
    return statistics.mean(values) if values else float("nan")


def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    a, b = zip(*pairs)
    ma, mb = mean(a), mean(b)
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return None if da == 0 or db == 0 else sum((x - ma) * (y - mb) for x, y in pairs) / (da * db)


def label_event(value):
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def fmt(x):
    return "NA" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.3f}"

with open(PATH, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

ethics = [r for r in rows if is_ethics(r)]
for r in ethics:
    r["_y"] = num(r.get(TARGET))
    for c in NUMERIC:
        r["_" + c] = num(r.get(c))
    r["_event"] = label_event(r.get("critical_event_occurred"))

valid_y = [r for r in ethics if r["_y"] is not None]
print(f"Rows read: {len(rows)}; ethics-focused rows: {len(ethics)}; usable outcomes: {len(valid_y)}")
if not valid_y:
    print("No usable percentage_increase_in_utilitarianism observations were found.")
    raise SystemExit

print(f"Overall mean percentage increase: {fmt(mean([r['_y'] for r in valid_y]))}")

for col in NUMERIC:
    value = corr([r["_" + col] for r in ethics], [r["_y"] for r in ethics])
    print(f"Correlation outcome vs {col}: {fmt(value)}")

for col in ("moderator_ethical_stance", "critical_event_occurred"):
    groups = {}
    for r in valid_y:
        key = ("event" if r["_event"] else "no_event") if col == "critical_event_occurred" else str(r.get(col, "missing")).strip().lower()
        groups.setdefault(key, []).append(r["_y"])
    print(f"Means by {col}: " + "; ".join(f"{k} n={len(v)} mean={fmt(mean(v))}" for k, v in sorted(groups.items())))

# High/low engagement comparison using medians, retaining complete cases.
complete = [r for r in valid_y if all(r["_" + c] is not None for c in NUMERIC)]
if complete:
    med = {c: statistics.median([r["_" + c] for r in complete]) for c in NUMERIC}
    high = [r["_y"] for r in complete if sum(r["_" + c] >= med[c] for c in NUMERIC) >= 3]
    low = [r["_y"] for r in complete if sum(r["_" + c] < med[c] for c in NUMERIC) >= 3]
    print(f"High-engagement mean (at least 3/4 predictors at or above median): {fmt(mean(high))} n={len(high)}")
    print(f"Low-engagement mean (at least 3/4 predictors below median): {fmt(mean(low))} n={len(low)}")

print("Interpretation: positive correlations or higher group means indicate association with a larger utilitarianism increase; these summaries are not causal tests.")