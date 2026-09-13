import os
import sys
import numpy as np
import pandas as pd

PATH = "/input/public_csv"
EXPECTED = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]

try:
    df = pd.read_csv(PATH)
except Exception as e:
    print(f"Could not read {PATH}: {e}")
    sys.exit(1)

missing = [c for c in EXPECTED if c not in df.columns]
if missing:
    print("Missing columns: " + ", ".join(missing))
    sys.exit(1)

d = df[EXPECTED].copy()
for c in EXPECTED:
    d[c] = pd.to_numeric(d[c], errors="coerce")
d = d.replace([np.inf, -np.inf], np.nan).dropna()
d = d[d["hours"] > 0].copy()
if len(d) == 0:
    print("No valid trips with positive hours.")
    sys.exit(0)

d["rate"] = d["fish_caught"] / d["hours"]

def fmt(x):
    return "NA" if not np.isfinite(x) else f"{x:.3f}"

def weighted_rate(x):
    return x["fish_caught"].sum() / x["hours"].sum()

print(f"Trips: {len(d)}; total fish: {d['fish_caught'].sum():.0f}; total hours: {d['hours'].sum():.1f}; overall fish/hour: {fmt(weighted_rate(d))}")
print(f"Mean trip rate: {fmt(d['rate'].mean())}; median trip rate: {fmt(d['rate'].median())}")

for col in ["livebait", "camper"]:
    print(f"{col} rates (exposure-weighted):")
    for level, g in d.groupby(col, dropna=False):
        print(f"  {col}={level:g}: n={len(g)}, fish/hour={fmt(weighted_rate(g))}, mean trip rate={fmt(g['rate'].mean())}")

# Least-squares log-rate model: log((fish+0.5)/hours) against predictors.
y = np.log((d["fish_caught"].to_numpy() + 0.5) / d["hours"].to_numpy())
cols = ["livebait", "camper", "persons", "child", "log_hours", "bait_x_log_hours"]
X = pd.DataFrame({
    "const": 1.0,
    "livebait": d["livebait"],
    "camper": d["camper"],
    "persons": d["persons"],
    "child": d["child"],
    "log_hours": np.log(d["hours"]),
    "bait_x_log_hours": d["livebait"] * np.log(d["hours"])
}).to_numpy(dtype=float)
labels = ["intercept"] + cols
try:
    beta, _, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ beta
    r2 = 1 - np.sum((y - pred) ** 2) / max(np.sum((y - y.mean()) ** 2), 1e-12)
    print(f"Adjusted log-rate model: n={len(d)}, rank={rank}, R2={r2:.3f}")
    for name, value in zip(labels, beta):
        print(f"  {name} coefficient: {value:.4f}; multiplicative rate factor: {np.exp(value):.3f}")
except Exception as e:
    print(f"Model unavailable: {e}")

print("Interpret coefficients as associations, not causal effects; the exposure-weighted rates describe fish caught per fishing hour.")