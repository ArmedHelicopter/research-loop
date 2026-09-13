import csv
import math
import os

path = "/input/data.csv"
if not os.path.exists(path):
    path = os.path.join(os.getcwd(), "data.csv")

with open(path, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))


def norm(s):
    return str(s).strip().lower()


def num(row, key):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None

# The task specifies philosophical debates focused on ethics; retain rows whose
# topic fields contain "ethic", while accepting all rows if no such subset exists.
ethics = [r for r in rows if "ethic" in norm(r.get("philosophical_topic", "")) or "ethic" in norm(r.get("topic_of_debate", ""))]
data = ethics if ethics else rows
outcome = "percentage_increase_in_utilitarianism"

valid = [r for r in data if num(r, outcome) is not None]
print(f"rows_total={len(rows)} rows_analyzed={len(data)} outcome_rows={len(valid)}")

stances = {}
for r in valid:
    stance = r.get("moderator_ethical_stance", "missing").strip() or "missing"
    st = stances.setdefault(stance, [])
    st.append(num(r, outcome))
for stance, values in sorted(stances.items()):
    print(f"stance={stance} n={len(values)} mean_outcome={sum(values)/len(values):.3f}")

events = {}
for r in valid:
    event = r.get("critical_event_occurred", "missing").strip() or "missing"
    events.setdefault(event, []).append(num(r, outcome))
for event, values in sorted(events.items()):
    print(f"critical_event={event} n={len(values)} mean_outcome={sum(values)/len(values):.3f}")


def corr(key):
    pairs = [(num(r, key), num(r, outcome)) for r in valid]
    pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(pairs) < 2:
        return None, len(pairs)
    xs, ys = zip(*pairs)
    mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
    dx = [x-mx for x in xs]
    dy = [y-my for y in ys]
    den = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    return (sum(x*y for x, y in zip(dx, dy))/den if den else None), len(pairs)

for key in ["argument_intensity", "audience_interest_level", "average_debate_duration", "number_of_sessions"]:
    value, n = corr(key)
    print(f"correlation={key} n={n} pearson={('NA' if value is None else f'{value:.3f}')}")