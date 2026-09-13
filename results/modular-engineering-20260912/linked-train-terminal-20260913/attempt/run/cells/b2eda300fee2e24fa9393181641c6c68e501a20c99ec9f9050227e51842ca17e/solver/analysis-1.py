import csv
import glob
import math
import os

REQUIRED = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]

def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def mean(xs):
    return sum(xs) / len(xs) if xs else float("nan")

def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return float("nan")
    xa = mean([p[0] for p in pairs])
    ya = mean([p[1] for p in pairs])
    dx = [p[0] - xa for p in pairs]
    dy = [p[1] - ya for p in pairs]
    den = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    return sum(a * b for a, b in zip(dx, dy)) / den if den else float("nan")

def fmt(x):
    return "NA" if not math.isfinite(x) else f"{x:.3f}"

files = sorted(glob.glob("/input/*.csv"))
if not files:
    print("No CSV file found in /input.")
    raise SystemExit

path = files[0]
with open(path, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

missing = [c for c in REQUIRED if not rows or c not in rows[0]]
if missing:
    print("Missing required columns: " + ", ".join(missing))
    raise SystemExit

clean = []
for r in rows:
    vals = {c: num(r.get(c)) for c in REQUIRED}
    if all(vals[c] is not None for c in REQUIRED) and vals["hours"] > 0:
        clean.append(vals)

rates = [r["fish_caught"] / r["hours"] for r in clean]
print(f"records={len(rows)} usable={len(clean)} overall_fish_per_hour={fmt(mean(rates))}")

for field in ("livebait", "camper"):
    groups = {}
    for r in clean:
        key = int(r[field]) if r[field].is_integer() else r[field]
        groups.setdefault(key, []).append(r["fish_caught"] / r["hours"])
    summary = ", ".join(f"{k}:{fmt(mean(v))}" for k, v in sorted(groups.items(), key=lambda z: z[0]))
    print(f"{field}_group_rates={summary}")

for field in ("hours", "persons", "child"):
    print(f"corr_rate_{field}={fmt(pearson(rates, [r[field] for r in clean]))}")
