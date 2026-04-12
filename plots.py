"""
Four plots from the Toplogger SQLite database.
Saves to P:/Backups/Toplogger/plots.png
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np

DB_PATH  = "P:/Backups/Toplogger/toplogger.db"
OUT_PATH = "P:/Backups/Toplogger/plots.png"

# Font grade label mapping for y-axis ticks
_GRADE_STEPS = [
    (3.00,"3"),  (3.17,"3+"), (3.33,"3b"),(3.50,"3b+"),(3.67,"3c"),(3.83,"3c+"),
    (4.00,"4"),  (4.17,"4+"), (4.33,"4b"),(4.50,"4b+"),(4.67,"4c"),(4.83,"4c+"),
    (5.00,"5a"), (5.17,"5a+"),(5.33,"5b"),(5.50,"5b+"),(5.67,"5c"),(5.83,"5c+"),
    (6.00,"6a"), (6.17,"6a+"),(6.33,"6b"),(6.50,"6b+"),(6.67,"6c"),(6.83,"6c+"),
    (7.00,"7a"), (7.17,"7a+"),(7.33,"7b"),(7.50,"7b+"),(7.67,"7c"),(7.83,"7c+"),
    (8.00,"8a"),
]
FONT_GRADES = {round(d * 100): label for d, label in _GRADE_STEPS}

GRADE_TICKS = {round(d*100): label for d, label in _GRADE_STEPS
               if label in ("4","5a","5b","5c","6a","6a+","6b","6b+","6c","6c+","7a")}

def to_font(grade):
    if not grade:
        return None
    grade = int(grade)
    if grade == 0:
        return None
    closest = min(FONT_GRADES.keys(), key=lambda k: abs(k - grade))
    return FONT_GRADES[closest]

# ---------------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

sessions_raw = conn.execute("""
    SELECT stats_at_date, boulders_grade_trend, boulders_grade_max,
           boulders_total_tries, grade_distribution_boulders, gym_name
    FROM sessions
    ORDER BY stats_at_date
""").fetchall()
conn.close()

sessions = [dict(r) for r in sessions_raw]

# Parse dates
for s in sessions:
    s["date"] = datetime.strptime(s["stats_at_date"], "%Y-%m-%d")

# ---------------------------------------------------------------------------
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("My TopLogger Climbing Data", fontsize=16, fontweight="bold", y=0.98)
plt.subplots_adjust(hspace=0.42, wspace=0.32)

ACCENT   = "#E07B39"
BLUE     = "#4A90D9"
GREEN    = "#5BAD72"
DARK     = "#2C2C2C"
GRID_COL = "#EEEEEE"

# ---------------------------------------------------------------------------
# Plot 1: Grade progression over time
# ---------------------------------------------------------------------------
ax1 = axes[0, 0]

trend = [(s["date"], s["boulders_grade_trend"])
         for s in sessions if s["boulders_grade_trend"] and s["boulders_grade_trend"] > 0]
dates_t, grades_t = zip(*trend)

ax1.fill_between(dates_t, grades_t, alpha=0.12, color=ACCENT)
ax1.plot(dates_t, grades_t, color=ACCENT, linewidth=2.2, zorder=3)

ax1.set_title("Grade Progression (all-time)", fontweight="bold")
ax1.set_xlabel("")
ax1.set_ylabel("Grade (Font scale)")
ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax1.xaxis.set_major_locator(mdates.YearLocator())

# Y-axis: Font grade labels at key milestones
tick_vals  = [v for v in GRADE_TICKS if min(grades_t) - 20 <= v <= max(grades_t) + 20]
tick_lbls  = [GRADE_TICKS[v] for v in tick_vals]
ax1.set_yticks(tick_vals)
ax1.set_yticklabels(tick_lbls)
ax1.set_ylim(min(grades_t) - 30, max(grades_t) + 30)
ax1.yaxis.grid(True, color=GRID_COL, zorder=0)
ax1.set_axisbelow(True)

# Annotate current grade
ax1.annotate(f"Now: {to_font(grades_t[-1])}",
             xy=(dates_t[-1], grades_t[-1]),
             xytext=(-60, 12), textcoords="offset points",
             fontsize=9, color=ACCENT, fontweight="bold",
             arrowprops=dict(arrowstyle="->", color=ACCENT, lw=1.2))

# ---------------------------------------------------------------------------
# Plot 2: Sessions per month heatmap
# ---------------------------------------------------------------------------
ax2 = axes[0, 1]

month_counts = defaultdict(int)
for s in sessions:
    if s["boulders_total_tries"] and s["boulders_total_tries"] > 0:
        key = (s["date"].year, s["date"].month)
        month_counts[key] += 1

years  = sorted(set(s["date"].year for s in sessions))
months = list(range(1, 13))
month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

grid = np.zeros((len(years), 12))
for (yr, mo), cnt in month_counts.items():
    if yr in years:
        grid[years.index(yr), mo - 1] = cnt

im = ax2.imshow(grid, aspect="auto", cmap="YlOrRd", interpolation="nearest")
ax2.set_xticks(range(12))
ax2.set_xticklabels(month_names, fontsize=8)
ax2.set_yticks(range(len(years)))
ax2.set_yticklabels(years, fontsize=8)
ax2.set_title("Sessions per Month", fontweight="bold")

cb = fig.colorbar(im, ax=ax2, fraction=0.04, pad=0.04)
cb.set_label("Sessions", fontsize=8)

# Annotate cells with count where > 0
for yi, yr in enumerate(years):
    for mi in range(12):
        v = int(grid[yi, mi])
        if v > 0:
            ax2.text(mi, yi, str(v), ha="center", va="center",
                     fontsize=7, color="black" if v < 4 else "white")

# ---------------------------------------------------------------------------
# Plot 3: All-time grade distribution (aggregated from per-session JSON)
# ---------------------------------------------------------------------------
ax3 = axes[1, 0]

grade_fl = defaultdict(int)
grade_rp = defaultdict(int)

for s in sessions:
    dist = s.get("grade_distribution_boulders")
    if not dist:
        continue
    try:
        items = json.loads(dist)
    except Exception:
        continue
    for item in items:
        g = int(item.get("grade", 0))
        if g < 200:   # skip ungraded / very low
            continue
        label = to_font(g)
        if label:
            grade_fl[label] += item.get("countFl", 0)
            grade_rp[label] += item.get("countRp", 0)

# Order by grade value
ordered_labels = [to_font(v) for v in sorted(GRADE_TICKS.keys())]
ordered_labels = [l for l in ordered_labels if l in grade_fl or l in grade_rp]
# Keep only grades that appear in data
present = set(grade_fl.keys()) | set(grade_rp.keys())

all_font = [to_font(v) for v in sorted({
    int(item["grade"])
    for s in sessions
    for item in (json.loads(s["grade_distribution_boulders"]) if s["grade_distribution_boulders"] else [])
    if int(item.get("grade", 0)) >= 200
})]
all_font = list(dict.fromkeys(all_font))  # deduplicate, preserve order
all_font = [l for l in all_font if l]

fl_vals = [grade_fl.get(l, 0) for l in all_font]
rp_vals = [grade_rp.get(l, 0) for l in all_font]

x = np.arange(len(all_font))
ax3.bar(x, rp_vals, color=ACCENT, label="Redpoint", zorder=3)
ax3.bar(x, fl_vals, bottom=rp_vals, color=BLUE, label="Flash", zorder=3)

ax3.set_xticks(x)
ax3.set_xticklabels(all_font, rotation=45, ha="right", fontsize=8)
ax3.set_title("All-Time Grade Distribution", fontweight="bold")
ax3.set_ylabel("Total tops")
ax3.legend(fontsize=8)
ax3.yaxis.grid(True, color=GRID_COL, zorder=0)
ax3.set_axisbelow(True)

# ---------------------------------------------------------------------------
# Plot 4: Session volume over time (rolling 8-session average)
# ---------------------------------------------------------------------------
ax4 = axes[1, 1]

active = [(s["date"], s["boulders_total_tries"])
          for s in sessions if s["boulders_total_tries"] and s["boulders_total_tries"] > 0]
dates_v, tries_v = zip(*active)

# Scatter raw
ax4.scatter(dates_v, tries_v, s=14, color=BLUE, alpha=0.35, zorder=2)

# Rolling 8-session average
window = 8
rolling_avg = np.convolve(tries_v, np.ones(window) / window, mode="valid")
rolling_dates = dates_v[window - 1:]
ax4.plot(rolling_dates, rolling_avg, color=ACCENT, linewidth=2.2, zorder=3,
         label=f"{window}-session avg")

ax4.set_title("Tries per Session Over Time", fontweight="bold")
ax4.set_ylabel("Tries in session")
ax4.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax4.xaxis.set_major_locator(mdates.YearLocator())
ax4.legend(fontsize=8)
ax4.yaxis.grid(True, color=GRID_COL, zorder=0)
ax4.set_axisbelow(True)

# Annotate peak
peak_idx = int(np.argmax(tries_v))
ax4.annotate(f"Peak: {tries_v[peak_idx]}",
             xy=(dates_v[peak_idx], tries_v[peak_idx]),
             xytext=(10, -18), textcoords="offset points",
             fontsize=8, color=DARK,
             arrowprops=dict(arrowstyle="->", color=DARK, lw=1))

# ---------------------------------------------------------------------------
for ax in axes.flat:
    ax.tick_params(axis="x", labelsize=8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

plt.savefig(OUT_PATH, dpi=150, bbox_inches="tight", facecolor="white")
print(f"Saved to {OUT_PATH}")
plt.show()
