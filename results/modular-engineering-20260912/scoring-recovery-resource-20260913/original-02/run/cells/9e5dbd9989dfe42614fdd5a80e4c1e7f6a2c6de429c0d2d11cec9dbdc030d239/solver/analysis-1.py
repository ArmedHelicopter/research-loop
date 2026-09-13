import csv
import math
import os
import statistics

path = "/input/public_csv"
rows = []
with open(path, newline="", encoding="utf-8-sig") as f:
    for raw in csv.DictReader(f):
        try:
            fish = float(raw["fish_caught"])
            hours = float(raw["hours"])
            livebait = float(raw["livebait"])
            camper = float(raw["camper"])
            persons = float(raw["persons"])
            child = float(raw["child"])
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(x) for x in (fish, hours, livebait, camper, persons, child)) and hours > 0:
            rows.append({"fish": fish, "hours": hours, "livebait": livebait,
                         "camper": camper, "persons": persons, "child": child,
                         "rate": fish / hours})

if not rows:
    print("No valid rows with numeric fish_caught and positive hours were found.")
    raise SystemExit

def fmt(x):
    return f"{x:.3f}"

def summarize(label, subset):
    total_fish = sum(r["fish"] for r in subset)
    total_hours = sum(r["hours"] for r in subset)
    mean_rate = statistics.mean(r["rate"] for r in subset)
    print(f"{label}: n={len(subset)}, mean_trip_rate={fmt(mean_rate)}, "
          f"exposure_rate={fmt(total_fish / total_hours)}")

print(f"Valid trips: {len(rows)}")
summarize("Overall", rows)
for value in sorted(set(r["livebait"] for r in rows)):
    summarize(f"livebait={value:g}", [r for r in rows if r["livebait"] == value])
for value in sorted(set(r["camper"] for r in rows)):
    summarize(f"camper={value:g}", [r for r in rows if r["camper"] == value])

try:
    import numpy as np
    import statsmodels.api as sm
    y = np.array([r["fish"] for r in rows])
    X = np.array([[r["livebait"], r["camper"], r["persons"], r["child"]] for r in rows])
    X = sm.add_constant(X, has_constant="add")
    offset = np.log(np.array([r["hours"] for r in rows]))
    model = sm.GLM(y, X, family=sm.families.Poisson(), offset=offset).fit()
    names = ["intercept", "livebait", "camper", "persons", "child"]
    print("Poisson rate model (exposure=hours):")
    for name, coef, pvalue in zip(names, model.params, model.pvalues):
        print(f"  {name}: rate_ratio={fmt(math.exp(coef))}, p={pvalue:.4g}")
except Exception as exc:
    print(f"Adjusted Poisson model unavailable: {type(exc).__name__}")

print("Interpretation: rates and model coefficients are observational associations; they do not establish that live bait causes a change in catch rate.")