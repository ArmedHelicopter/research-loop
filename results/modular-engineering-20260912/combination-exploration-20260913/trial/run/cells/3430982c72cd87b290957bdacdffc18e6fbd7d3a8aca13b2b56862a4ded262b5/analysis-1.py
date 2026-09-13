import csv
import math
import os
import statistics

PATH = "/input/public_csv"
REQUIRED = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]

def num(x):
    try:
        return float(str(x).strip())
    except Exception:
        return None

def mean(xs):
    return statistics.mean(xs) if xs else float("nan")

def fmt(x):
    return "NA" if not math.isfinite(x) else f"{x:.3f}"

def group_value(v):
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "t"}:
        return "1"
    if s in {"0", "false", "no", "n", "f"}:
        return "0"
    return str(v).strip()

def ols(y, X):
    # Small Gaussian-elimination OLS with an intercept; no external packages.
    p = len(X[0])
    a = [[sum(X[i][j] * X[i][k] for i in range(len(y))) for k in range(p)] +
         [sum(X[i][j] * y[i] for i in range(len(y)))] for j in range(p)]
    for c in range(p):
        pivot = max(range(c, p), key=lambda r: abs(a[r][c]))
        if abs(a[pivot][c]) < 1e-12:
            return None
        a[c], a[pivot] = a[pivot], a[c]
        z = a[c][c]
        a[c] = [v / z for v in a[c]]
        for r in range(p):
            if r == c:
                continue
            z = a[r][c]
            a[r] = [a[r][j] - z * a[c][j] for j in range(p + 1)]
    return [a[i][-1] for i in range(p)]

with open(PATH, newline="", encoding="utf-8-sig") as f:
    sample = f.read(4096)
    f.seek(0)
    dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
    rows = list(csv.DictReader(f, dialect=dialect))

missing = [c for c in REQUIRED if not rows or c not in rows[0]]
if missing:
    print("Missing required columns: " + ", ".join(missing))
    raise SystemExit(0)

clean = []
for r in rows:
    vals = {c: num(r.get(c, "")) for c in REQUIRED}
    if all(vals[c] is not None for c in REQUIRED) and vals["hours"] > 0:
        vals["livebait"] = group_value(r["livebait"])
        vals["camper"] = group_value(r["camper"])
        clean.append(vals)

if not clean:
    print("No complete rows with positive hours were available.")
    raise SystemExit(0)

rates = [r["fish_caught"] / r["hours"] for r in clean]
print(f"Rows analyzed: {len(clean)}; mean fish/hour: {fmt(mean(rates))}; median fish/hour: {fmt(statistics.median(rates))}")
print(f"Mean fish caught: {fmt(mean([r['fish_caught'] for r in clean]))}; mean hours: {fmt(mean([r['hours'] for r in clean]))}")
for col in ["livebait", "camper"]:
    levels = sorted({r[col] for r in clean})
    parts = []
    for level in levels:
        g = [r for r in clean if r[col] == level]
        parts.append(f"{col}={level}: n={len(g)}, fish/hour={fmt(mean([x['fish_caught']/x['hours'] for x in g]))}")
    print("; ".join(parts))

# Adjusted linear model: fish caught ~ hours + livebait + camper + persons + child.
levels = {c: sorted({r[c] for r in clean}) for c in ["livebait", "camper"]}
X, y = [], []
for r in clean:
    X.append([1, r["hours"], 1 if r["livebait"] == levels["livebait"][-1] else 0,
              1 if r["camper"] == levels["camper"][-1] else 0, r["persons"], r["child"]])
    y.append(r["fish_caught"])
b = ols(y, X)
if b:
    names = ["intercept", "hours", "livebait(high)", "camper(high)", "persons", "child"]
    print("Adjusted coefficients (fish caught): " + ", ".join(f"{n}={fmt(v)}" for n, v in zip(names, b)))
    print("Interpret hours coefficient as estimated additional fish per hour, conditional on the other recorded factors.")
else:
    print("Adjusted regression could not be estimated because predictors were collinear or insufficiently variable.")