import csv
import math
import os
import statistics

PATH = "/input/public_csv"
EXPECTED = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]


def read_rows(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
        except csv.Error:
            dialect = csv.excel
        return list(csv.DictReader(f, dialect=dialect))


def num(x):
    try:
        return float(str(x).strip())
    except (TypeError, ValueError):
        return None


def encode(x):
    n = num(x)
    if n is not None:
        return n
    s = str(x).strip().lower()
    if s in {"yes", "y", "true", "t", "1"}:
        return 1.0
    if s in {"no", "n", "false", "f", "0"}:
        return 0.0
    return None


def mean(xs):
    return statistics.mean(xs) if xs else float("nan")


def corr(xs, ys):
    if len(xs) < 2:
        return float("nan")
    mx, my = mean(xs), mean(ys)
    den = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
    return sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / den if den else float("nan")


def fmt(x):
    return "NA" if not math.isfinite(x) else f"{x:.3f}"


rows = read_rows(PATH)
fields = set(rows[0]) if rows else set()
missing_fields = [c for c in EXPECTED if c not in fields]
if missing_fields:
    raise ValueError("Missing expected columns: " + ", ".join(missing_fields))

records = []
for r in rows:
    v = {c: (num(r[c]) if c in {"fish_caught", "persons", "child", "hours"} else encode(r[c])) for c in EXPECTED}
    records.append(v)

complete = [r for r in records if all(r[c] is not None for c in EXPECTED)]
valid = [r for r in complete if r["hours"] > 0]
rate = [r["fish_caught"] / r["hours"] for r in valid]
print(f"rows={len(rows)} complete={len(complete)} valid_hours={len(valid)}")
print("missing=" + ", ".join(f"{c}:{sum(r[c] is None for r in records)}" for c in EXPECTED))
if valid:
    print(f"fish_per_hour_mean={fmt(mean(rate))} median={fmt(statistics.median(rate))} total_fish={fmt(sum(r['fish_caught'] for r in valid))} total_hours={fmt(sum(r['hours'] for r in valid))}")
    for c in ["livebait", "camper"]:
        groups = {}
        for r in valid:
            groups.setdefault(r[c], []).append(r["fish_caught"] / r["hours"])
        print(c + "_rate=" + "; ".join(f"{k:g}:{fmt(mean(v))}(n={len(v)})" for k, v in sorted(groups.items())))
    for c in ["persons", "child", "hours", "livebait", "camper"]:
        print(f"corr_rate_{c}={fmt(corr(rate, [r[c] for r in valid]))}")

# OLS with an intercept and standardized numeric predictors, using complete valid rows.
predictors = ["livebait", "camper", "persons", "child", "hours"]
if len(valid) >= len(predictors) + 2:
    X = [[1.0] + [r[c] for c in predictors] for r in valid]
    y = [r["fish_caught"] for r in valid]
    try:
        import numpy as np
        beta = np.linalg.lstsq(np.asarray(X), np.asarray(y), rcond=None)[0]
        pred = np.asarray(X) @ beta
        ssr = float(sum((a-b)**2 for a, b in zip(y, pred)))
        sst = float(sum((a-mean(y))**2 for a in y))
        print("ols_fish_caught=" + ", ".join(f"intercept:{beta[0]:.3f}" if i == 0 else f"{c}:{beta[i]:.3f}" for i, c in enumerate(["intercept"] + predictors)))
        print(f"ols_r2={fmt(1-ssr/sst if sst else float('nan'))}")
    except Exception as e:
        print("ols_unavailable=" + type(e).__name__)
else:
    print("ols_unavailable=insufficient_valid_rows")