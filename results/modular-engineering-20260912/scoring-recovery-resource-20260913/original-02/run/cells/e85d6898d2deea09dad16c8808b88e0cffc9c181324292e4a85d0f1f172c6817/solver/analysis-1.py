import csv
import math
from collections import defaultdict

PATH = "/input/public_csv"

def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None

def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")

def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return float("nan")
    ax, ay = mean([p[0] for p in pairs]), mean([p[1] for p in pairs])
    sx = math.sqrt(sum((p[0] - ax) ** 2 for p in pairs))
    sy = math.sqrt(sum((p[1] - ay) ** 2 for p in pairs))
    return sum((x - ax) * (y - ay) for x, y in pairs) / (sx * sy) if sx and sy else float("nan")

def fmt(x):
    return "NA" if not math.isfinite(x) else f"{x:.3f}"

def solve(A, b):
    n = len(b)
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-10:
            return None
        M[col], M[pivot] = M[pivot], M[col]
        q = M[col][col]
        M[col] = [z / q for z in M[col]]
        for r in range(n):
            if r != col:
                q = M[r][col]
                M[r] = [M[r][j] - q * M[col][j] for j in range(n + 1)]
    return [M[i][-1] for i in range(n)]

with open(PATH, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

# Prefer rows explicitly labeled ethics; fall back to all rows if the synthetic data has no such label.
def is_ethics(r):
    text = " ".join(str(r.get(k, "")).lower() for k in ("topic_of_debate", "philosophical_topic"))
    return "ethic" in text
ethics = [r for r in rows if is_ethics(r)] or rows

yname = "percentage_increase_in_utilitarianism"
num_names = ["argument_intensity", "audience_interest_level", "average_debate_duration", "number_of_sessions"]
print(f"rows_total={len(rows)} ethics_rows={len(ethics)}")

for field in ("moderator_ethical_stance", "critical_event_occurred"):
    groups = defaultdict(list)
    for r in ethics:
        y = num(r.get(yname))
        if y is not None:
            groups[str(r.get(field, "missing")).strip().lower()].append(y)
    label = field.replace("_", "=")
    print(label + ": " + "; ".join(f"{k}:n={len(v)},mean={fmt(mean(v))}" for k, v in sorted(groups.items())))

for xname in num_names:
    xs, ys = [], []
    for r in ethics:
        x, y = num(r.get(xname)), num(r.get(yname))
        if x is not None and y is not None:
            xs.append(x); ys.append(y)
    print(f"corr_{xname}={fmt(corr(xs, ys))},n={len(xs)}")

# OLS: intercept, intensity, interest, duration, sessions, event flag, stance dummies.
stance_values = sorted({str(r.get("moderator_ethical_stance", "missing")).strip().lower() for r in ethics})
base = stance_values[0] if stance_values else "missing"
X, Y = [], []
for r in ethics:
    y = num(r.get(yname))
    vals = [num(r.get(k)) for k in num_names]
    event = num(r.get("critical_event_occurred"))
    if event is None:
        event = 1.0 if str(r.get("critical_event_occurred", "")).strip().lower() in {"true", "yes", "y", "1"} else 0.0
    stance = str(r.get("moderator_ethical_stance", "missing")).strip().lower()
    if y is not None and all(v is not None for v in vals):
        X.append([1.0] + vals + [event] + [1.0 if stance == s else 0.0 for s in stance_values[1:]])
        Y.append(y)
if len(X) >= len(X[0]) if X else False:
    p = len(X[0])
    gram = [[sum(row[i] * row[j] for row in X) for j in range(p)] for i in range(p)]
    rhs = [sum(X[k][i] * Y[k] for k in range(len(X))) for i in range(p)]
    beta = solve(gram, rhs)
    if beta:
        names = ["intercept"] + num_names + ["critical_event"] + ["stance_" + s for s in stance_values[1:]]
        print("ols_n=" + str(len(X)) + " " + " ".join(f"{n}={fmt(v)}" for n, v in zip(names, beta)) + f" baseline_stance={base}")
    else:
        print("ols=singular_design")
else:
    print("ols=insufficient_complete_rows")