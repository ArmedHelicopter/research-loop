import csv
import math
import os

PATH = "/input/data.csv"
TARGET = "percentage_increase_in_utilitarianism"
NUMERIC = [
    "argument_intensity", "audience_interest_level", "average_debate_duration",
    "number_of_sessions", "critical_event_occurred", TARGET, "external_temperature"
]

def num(v):
    try:
        x = float(str(v).strip())
        return x if math.isfinite(x) else None
    except Exception:
        return None

def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    a, b = zip(*pairs)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in pairs) / math.sqrt(va * vb)

def solve(a, b):
    n = len(b)
    m = [list(map(float, a[i])) + [float(b[i])] for i in range(n)]
    for k in range(n):
        p = max(range(k, n), key=lambda i: abs(m[i][k]))
        if abs(m[p][k]) < 1e-12:
            return None
        m[k], m[p] = m[p], m[k]
        q = m[k][k]
        m[k] = [z / q for z in m[k]]
        for i in range(n):
            if i != k:
                q = m[i][k]
                m[i] = [m[i][j] - q * m[k][j] for j in range(n + 1)]
    return [m[i][-1] for i in range(n)]

def regression(rows):
    stances = sorted({r.get("moderator_ethical_stance", "") for r in rows})
    base = stances[0] if stances else ""
    cols = ["intercept", "argument_intensity", "audience_interest_level",
            "average_debate_duration", "number_of_sessions", "critical_event_occurred"]
    for s in stances[1:]:
        cols.append("stance=" + s)
    data = []
    for r in rows:
        vals = [num(r.get(c)) for c in ["argument_intensity", "audience_interest_level",
                "average_debate_duration", "number_of_sessions", "critical_event_occurred", TARGET]]
        if any(v is None for v in vals):
            continue
        x = [1.0] + vals[:5]
        s = r.get("moderator_ethical_stance", "")
        x += [1.0 if s == z else 0.0 for z in stances[1:]]
        data.append((x, vals[5]))
    if len(data) <= len(cols):
        return None
    p = len(cols)
    xtx = [[sum(x[i] * x[j] for x, y in data) for j in range(p)] for i in range(p)]
    xty = [sum(x[i] * y for x, y in data) for i in range(p)]
    beta = solve(xtx, xty)
    return dict(zip(cols, beta)) if beta else None

try:
    with open(PATH, newline="", encoding="utf-8-sig") as f:
        all_rows = list(csv.DictReader(f))
except Exception as e:
    print("Unable to read /input/data.csv: " + str(e))
    raise SystemExit

rows = []
for r in all_rows:
    topic = (r.get("philosophical_topic", "") + " " + r.get("topic_of_debate", "")).lower()
    if "ethic" in topic:
        rows.append(r)
if not rows:
    rows = all_rows

out = ["rows=" + str(len(rows))]
for c in NUMERIC:
    miss = sum(num(r.get(c)) is None for r in rows)
    if miss:
        out.append(c + "_missing=" + str(miss))
for c in ["argument_intensity", "audience_interest_level", "average_debate_duration", "number_of_sessions", "critical_event_occurred", "external_temperature"]:
    r = corr([num(x.get(c)) for x in rows], [num(x.get(TARGET)) for x in rows])
    if r is not None:
        out.append("corr(" + c + ",target)=" + format(r, ".3f"))
for event in [0.0, 1.0]:
    ys = [num(r.get(TARGET)) for r in rows if num(r.get("critical_event_occurred")) == event]
    ys = [y for y in ys if y is not None]
    if ys:
        out.append("critical_event=" + str(int(event)) + ":n=" + str(len(ys)) + ",mean_target=" + format(sum(ys)/len(ys), ".3f"))
stances = {}
for r in rows:
    s = r.get("moderator_ethical_stance", "unknown")
    y = num(r.get(TARGET))
    if y is not None:
        stances.setdefault(s, []).append(y)
for s, ys in sorted(stances.items()):
    out.append("stance=" + s + ":n=" + str(len(ys)) + ",mean_target=" + format(sum(ys)/len(ys), ".3f"))
b = regression(rows)
if b and "argument_intensity" in b:
    out.append("adjusted_argument_intensity_coef=" + format(b["argument_intensity"], ".3f"))
print("; ".join(out))