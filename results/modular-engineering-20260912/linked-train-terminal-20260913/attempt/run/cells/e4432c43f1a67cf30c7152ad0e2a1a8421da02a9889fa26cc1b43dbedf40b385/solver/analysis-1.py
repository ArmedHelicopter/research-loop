import csv, math
from pathlib import Path

required = ["fish_caught", "livebait", "camper", "persons", "child", "hours"]
files = sorted(Path("/input").glob("*.csv"))
if not files:
    print("No CSV files found in /input.")
    raise SystemExit

rows = []
for path in files:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
            continue
        for r in reader:
            try:
                vals = {k: float(str(r[k]).strip()) for k in ["fish_caught", "persons", "child", "hours"]}
                bait = str(r["livebait"]).strip().lower()
                camper = str(r["camper"]).strip().lower()
                vals["livebait"] = bait in {"1", "true", "yes", "y", "t"}
                vals["camper"] = camper in {"1", "true", "yes", "y", "t"}
                vals["raw"] = tuple(str(r.get(k, "")).strip() for k in required)
                rows.append(vals)
            except (TypeError, ValueError):
                pass

valid = [r for r in rows if r["hours"] > 0 and r["fish_caught"] >= 0 and r["persons"] >= 0 and r["child"] >= 0]
invalid = len(rows) - len(valid)

def summarize(group):
    if not group:
        return None
    total_fish = sum(r["fish_caught"] for r in group)
    total_hours = sum(r["hours"] for r in group)
    trip_rates = [r["fish_caught"] / r["hours"] for r in group]
    return len(group), total_fish / total_hours if total_hours else math.nan, sum(trip_rates) / len(trip_rates)

print(f"Trips parsed: {len(rows)}; valid for rate analysis: {len(valid)}; excluded: {invalid}.")
all_s = summarize(valid)
if all_s:
    print(f"Overall catch rate: {all_s[1]:.3f} fish/hour (exposure-weighted); mean trip rate: {all_s[2]:.3f}.")
for bait in (False, True):
    s = summarize([r for r in valid if r["livebait"]]) if bait else summarize([r for r in valid if not r["livebait"]])
    label = "livebait" if bait else "no-livebait"
    if s:
        print(f"{label}: n={s[0]}, weighted_rate={s[1]:.3f}, mean_trip_rate={s[2]:.3f}.")

if valid:
    bait_groups = {b: [r for r in valid if r["livebait"] == b] for b in (False, True)}
    if all(bait_groups[b] for b in bait_groups):
        diff = summarize(bait_groups[True])[1] - summarize(bait_groups[False])[1]
        print(f"Livebait weighted-rate difference: {diff:.3f} fish/hour.")
    duplicate_count = len(valid) - len({r["raw"] for r in valid})
    print(f"Exact duplicate valid rows: {duplicate_count}.")
else:
    print("No valid records remain for estimating catch rates.")