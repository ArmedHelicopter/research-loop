import csv
import math
import os

PATH = "/input/public_csv"
TARGETS = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]

def num(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None

def mean(values):
    return sum(values) / len(values) if values else float("nan")

def corr(x, y):
    if len(x) < 2:
        return None
    mx, my = mean(x), mean(y)
    ssx = sum((v - mx) ** 2 for v in x)
    ssy = sum((v - my) ** 2 for v in y)
    if ssx == 0 or ssy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(ssx * ssy)

def fmt(value):
    return "NA" if value is None or not math.isfinite(value) else f"{value:.4f}"

def solve_linear(X, y):
    n, p = len(X), len(X[0])
    a = [[sum(X[r][i] * X[r][j] for r in range(n)) for j in range(p)] +
         [sum(X[r][i] * y[r] for r in range(n))] for i in range(p)]
    for col in range(p):
        pivot = max(range(col, p), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-10:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        div = a[col][col]
        a[col] = [v / div for v in a[col]]
        for r in range(p):
            if r != col:
                factor = a[r][col]
                a[r] = [a[r][j] - factor * a[col][j] for j in range(p + 1)]
    return [a[i][-1] for i in range(p)]

with open(PATH, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

available = set(rows[0]) if rows else set()
missing = [c for c in TARGETS if c not in available]
if missing:
    print("Missing columns: " + ", ".join(missing))
    raise SystemExit

rates = []
for row in rows:
    fish, hours = num(row["fish_caught"]), num(row["hours"])
    if fish is not None and hours is not None and hours > 0:
        rates.append(fish / hours)
print(f"Trips: {len(rows)}; valid fish/hour observations: {len(rates)}")
if rates:
    print(f"Mean fish/hour: {mean(rates):.4f}; median: {sorted(rates)[len(rates)//2]:.4f}")

for name in ["livebait", "camper", "persons", "child", "hours"]:
    x, y = [], []
    for row in rows:
        v = num(row[name])
        fish, hours = num(row["fish_caught"]), num(row["hours"])
        if v is not None and fish is not None and hours is not None and hours > 0:
            x.append(v); y.append(fish / hours)
    print(f"Correlation rate vs {name}: {fmt(corr(x, y))} (n={len(x)})")

features = ["hours", "livebait", "camper", "persons", "child"]
X, y = [], []
for row in rows:
    vals = [num(row[c]) for c in ["fish_caught"] + features]
    if all(v is not None for v in vals):
        y.append(vals[0]); X.append([1.0] + vals[1:])
if len(X) >= len(features) + 2:
    beta = solve_linear(X, y)
    if beta:
        print("OLS fish_caught coefficients (intercept, " + ", ".join(features) + "): " +
              ", ".join(fmt(v) for v in beta) + f"; n={len(X)}")
else:
    print("OLS model unavailable: insufficient complete rows")