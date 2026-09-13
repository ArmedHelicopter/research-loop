import csv
import math
import os

PATH = "/input/public_csv"


def as_number(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def mean(values):
    return sum(values) / len(values) if values else float("nan")


def solve_linear(A, b):
    n = len(b)
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            return None
        M[col], M[pivot] = M[pivot], M[col]
        scale = M[col][col]
        M[col] = [x / scale for x in M[col]]
        for row in range(n):
            if row == col:
                continue
            factor = M[row][col]
            M[row] = [M[row][j] - factor * M[col][j] for j in range(n + 1)]
    return [M[i][n] for i in range(n)]


with open(PATH, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

required = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]
missing = [c for c in required if not rows or c not in rows[0]]
if missing:
    print("Missing required columns: " + ", ".join(missing))
else:
    data = []
    for row in rows:
        vals = {c: as_number(row.get(c)) for c in required}
        if all(vals[c] is not None for c in required) and vals["hours"] > 0:
            vals["rate"] = vals["fish_caught"] / vals["hours"]
            data.append(vals)

    rates = [r["rate"] for r in data]
    print(f"Valid trips: {len(data)} of {len(rows)}")
    if not rates:
        print("No valid trips with positive hours; estimates unavailable.")
    else:
        print(f"Mean fish caught per hour: {mean(rates):.4f}")
        print(f"Median fish caught per hour: {sorted(rates)[len(rates)//2]:.4f}")
        for col in ["livebait", "camper"]:
            groups = {}
            for r in data:
                groups.setdefault(r[col], []).append(r["rate"])
            text = "; ".join(f"{k}: n={len(v)}, mean_rate={mean(v):.4f}" for k, v in sorted(groups.items()))
            print(f"{col} groups: {text}")

        features = ["livebait", "camper", "persons", "child", "hours"]
        X = [[1.0] + [r[c] for c in features] for r in data]
        y = rates
        p = len(features) + 1
        if len(data) >= p:
            XtX = [[sum(row[i] * row[j] for row in X) for j in range(p)] for i in range(p)]
            Xty = [sum(X[k][i] * y[k] for k in range(len(y))) for i in range(p)]
            beta = solve_linear(XtX, Xty)
            if beta is not None:
                ybar = mean(y)
                ss_tot = sum((v - ybar) ** 2 for v in y)
                ss_res = sum((y[k] - sum(beta[j] * X[k][j] for j in range(p))) ** 2 for k in range(len(y)))
                r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else float("nan")
                print("OLS hourly-rate coefficients (intercept, livebait, camper, persons, child, hours): " + ", ".join(f"{v:.4f}" for v in beta))
                print(f"OLS R-squared: {r2:.4f}")
            else:
                print("OLS model could not be fit because the design matrix is singular.")
        else:
            print("Not enough complete observations for the multivariable model.")