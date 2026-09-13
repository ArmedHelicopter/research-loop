import csv
import math
import os

PATH = "/input/data.csv"
TARGET = "percentage_increase_in_utilitarianism"
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
    if len(xs) < 2:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    den = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    return None if den == 0 else sum(x*y for x, y in zip(dx, dy)) / den

def fmt(x):
    return "NA" if x is None else f"{x:.3f}"

if not os.path.exists(PATH):
    print("No data file found at /input/data.csv.")
    raise SystemExit

with open(PATH, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# Prefer ethics rows if the topic field contains an ethics label; otherwise use all rows.
def is_ethics(r):
    text = " ".join(str(r.get(k, "")).lower() for k in ("topic_of_debate", "philosophical_topic"))
    return "ethic" in text
ethics_rows = [r for r in rows if is_ethics(r)]
use = ethics_rows or rows

print(f"Rows analyzed: {len(use)} (ethics-filtered: {bool(ethics_rows)}).")
for col in NUMERIC:
    pairs = [(num(r.get(col)), num(r.get(TARGET))) for r in use]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    xs, ys = zip(*pairs) if pairs else ([], [])
    print(f"Correlation {col} vs {TARGET}: r={fmt(pearson(list(xs), list(ys)))}; n={len(pairs)}.")

# Group means for moderator stance and critical-event status.
for col in ("moderator_ethical_stance", "critical_event_occurred"):
    groups = {}
    for r in use:
        y = num(r.get(TARGET))
        key = str(r.get(col, "")).strip() or "missing"
        if y is not None:
            groups.setdefault(key, []).append(y)
    if groups:
        summary = "; ".join(f"{k}: mean={sum(v)/len(v):.3f}, n={len(v)}" for k, v in sorted(groups.items()))
        print(f"{col} outcome means: {summary}.")

print("Interpretation: positive r indicates higher predictor values coincide with higher utilitarianism percentage increase; group means are descriptive and do not establish causality.")