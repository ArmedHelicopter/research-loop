import csv
import math
import re
from collections import defaultdict

PATH = "/input/public_csv"
OUTCOME = "percentage_increase_in_utilitarianism"
NUMERIC = [
    "argument_intensity",
    "audience_interest_level",
    "average_debate_duration",
    "number_of_sessions",
]

def num(x):
    try:
        return float(str(x).strip().replace("%", ""))
    except (TypeError, ValueError):
        return None

def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None, len(pairs)
    ax = sum(x for x, _ in pairs) / len(pairs)
    ay = sum(y for _, y in pairs) / len(pairs)
    dx = [x - ax for x, _ in pairs]
    dy = [y - ay for _, y in pairs]
    den = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    return (sum(a * b for a, b in zip(dx, dy)) / den if den else None), len(pairs)

def fmt(x):
    return "NA" if x is None else f"{x:.3f}"

with open(PATH, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

ethics = []
for r in rows:
    text = " ".join(r.get(k, "") for k in ("philosophical_topic", "topic_of_debate")).lower()
    if re.search(r"ethic", text):
        ethics.append(r)

print(f"Ethics-focused rows: {len(ethics)} of {len(rows)}")
ys = [num(r.get(OUTCOME)) for r in ethics]
valid_y = [v for v in ys if v is not None]
if valid_y:
    mean = sum(valid_y) / len(valid_y)
    print(f"Outcome mean={mean:.3f}, min={min(valid_y):.3f}, max={max(valid_y):.3f}, n={len(valid_y)}")
else:
    print("Outcome has no numeric observations")

for col in NUMERIC:
    r, n = pearson([num(x.get(col)) for x in ethics], ys)
    print(f"Correlation outcome vs {col}: r={fmt(r)}, paired_n={n}")

def grouped(col):
    groups = defaultdict(list)
    for r in ethics:
        y = num(r.get(OUTCOME))
        key = str(r.get(col, "")).strip() or "(missing)"
        if y is not None:
            groups[key].append(y)
    for key in sorted(groups):
        vals = groups[key]
        print(f"Mean outcome by {col}={key}: mean={sum(vals)/len(vals):.3f}, n={len(vals)}")

grouped("moderator_ethical_stance")
grouped("critical_event_occurred")
print("Interpret correlations and group differences as descriptive associations; confounding and sample size are not assessed.")