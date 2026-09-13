import csv
import math
import os

PATH = "/input/public_csv"
EXPECTED = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]

def num(x):
    try:
        v = float(str(x).strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")

def sd(xs):
    if len(xs) < 2:
        return float("nan")
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))

def ols(y, columns):
    # Normal equations with a small Gaussian-elimination solver.
    p = len(columns[0]) + 1
    a = [[0.0] * (p + 1) for _ in range(p)]
    for yi, row in zip(y, columns):
        x = [1.0] + row
        for i in range(p):
            for j in range(p):
                a[i][j] += x[i] * x[j]
            a[i][p] += x[i] * yi
    for k in range(p):
        pivot = max(range(k, p), key=lambda i: abs(a[i][k]))
        if abs(a[pivot][k]) < 1e-10:
            return None
        a[k], a[pivot] = a[pivot], a[k]
        q = a[k][k]
        for j in range(k, p + 1):
            a[k][j] /= q
        for i in range(p):
            if i == k:
                continue
            q = a[i][k]
            for j in range(k, p + 1):
                a[i][j] -= q * a[k][j]
    return [a[i][p] for i in range(p)]

if not os.path.isfile(PATH):
    print("No dataset found at /input/public_csv.")
else:
    with open(PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    missing = [c for c in EXPECTED if not rows or c not in rows[0]]
    if missing:
        print("Missing expected columns: " + ", ".join(missing))
    else:
        clean = []
        for r in rows:
            vals = {c: num(r.get(c)) for c in EXPECTED}
            if all(vals[c] is not None for c in EXPECTED) and vals["hours"] > 0:
                clean.append(vals)
        rates = [r["fish_caught"] / r["hours"] for r in clean]
        print(f"Trips: {len(rows)}; usable trips: {len(clean)}.")
        if rates:
            print(f"Mean catch rate: {mean(rates):.3f} fish/hour (SD {sd(rates):.3f}); median not computed.")
            for field in ("livebait", "camper"):
                groups = {}
                for r, rate in zip(clean, rates):
                    key = int(r[field]) if r[field].is_integer() else r[field]
                    groups.setdefault(key, []).append(rate)
                if len(groups) >= 2:
                    text = "; ".join(f"{k}: n={len(v)}, mean={mean(v):.3f}" for k, v in sorted(groups.items(), key=lambda z: str(z[0])))
                    print(field + " groups - " + text + ".")
            predictors = [[r["livebait"], r["camper"], r["persons"], r["child"], r["hours"]] for r in clean]
            coef = ols(rates, predictors) if len(clean) >= 7 else None
            if coef:
                names = ["intercept", "livebait", "camper", "persons", "child", "hours"]
                print("OLS rate coefficients: " + ", ".join(f"{n}={b:.3f}" for n, b in zip(names, coef)) + ".")
            else:
                print("OLS rate model unavailable because there are too few rows or collinear predictors.")
        else:
            print("No usable rows with numeric values and positive hours.")