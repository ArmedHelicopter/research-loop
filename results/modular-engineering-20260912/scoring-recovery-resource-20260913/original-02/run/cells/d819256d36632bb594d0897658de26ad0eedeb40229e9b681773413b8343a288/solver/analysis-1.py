import csv
import math
import os

PATH = "/input/public_csv"
EXPECTED = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]

def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")

def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return float("nan")
    mx, my = mean([p[0] for p in pairs]), mean([p[1] for p in pairs])
    a = sum((x - mx) ** 2 for x, y in pairs)
    b = sum((y - my) ** 2 for x, y in pairs)
    return sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(a * b) if a and b else float("nan")

def fmt(x):
    return "NA" if not math.isfinite(x) else f"{x:.3f}"

def solve(A, b):
    n = len(b)
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
    for j in range(n):
        pivot = max(range(j, n), key=lambda i: abs(M[i][j]))
        if abs(M[pivot][j]) < 1e-10:
            return None
        M[j], M[pivot] = M[pivot], M[j]
        q = M[j][j]
        M[j] = [v / q for v in M[j]]
        for i in range(n):
            if i != j:
                q = M[i][j]
                M[i] = [M[i][k] - q * M[j][k] for k in range(n + 1)]
    return [M[i][-1] for i in range(n)]

with open(PATH, newline="") as f:
    rows = list(csv.DictReader(f))
if not rows or not set(EXPECTED).issubset(rows[0].keys()):
    raise ValueError("CSV is missing expected columns")

data = []
for r in rows:
    d = {k: num(r.get(k)) for k in EXPECTED}
    if all(d[k] is not None for k in EXPECTED) and d["hours"] > 0:
        d["rate"] = d["fish_caught"] / d["hours"]
        data.append(d)

rates = [d["rate"] for d in data]
print(f"Rows analyzed: {len(data)} of {len(rows)}")
print(f"Fish caught: mean={fmt(mean([d['fish_caught'] for d in data]))}; hours: mean={fmt(mean([d['hours'] for d in data]))}")
print(f"Fish per hour: mean={fmt(mean(rates))}, median={fmt(sorted(rates)[len(rates)//2]) if rates else 'NA'}")
for key in ("livebait", "camper"):
    groups = {}
    for d in data:
        groups.setdefault(int(d[key]), []).append(d["rate"])
    print(key + " rate means: " + ", ".join(f"{g}={fmt(mean(v))}" for g, v in sorted(groups.items())))
for key in ("hours", "livebait", "camper", "persons", "child"):
    print(f"Correlation(rate, {key}): {fmt(corr(rates, [d[key] for d in data]))}")

features = ["hours", "livebait", "camper", "persons", "child"]
if len(data) >= len(features) + 1:
    X = [[1.0] + [d[k] for k in features] for d in data]
    y = [d["fish_caught"] for d in data]
    XtX = [[sum(row[i] * row[j] for row in X) for j in range(len(features) + 1)] for i in range(len(features) + 1)]
    Xty = [sum(X[r][i] * y[r] for r in range(len(X))) for i in range(len(features) + 1)]
    beta = solve(XtX, Xty)
    if beta:
        print("OLS fish_caught coefficients: " + ", ".join(f"{k}={fmt(v)}" for k, v in zip(["intercept"] + features, beta)))