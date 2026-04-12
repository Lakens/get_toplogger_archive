"""
Annotates the Monk Rotterdam floorplan SVG with:
  - Area labels at the correct positions (using SVG wall-center coords)
  - Regions coloured by number of ticks (from the SQLite DB)
  - Coloured dots for every currently active boulder (hold colour)
  - Red NEW badge on areas with boulders set in the last NEW_DAYS days
Saves to P:/Backups/Toplogger/monk_rotterdam_annotated.svg
"""

import re, sqlite3

SVG_IN  = "P:/Backups/Toplogger/monk_rotterdam_floorplan.svg"
SVG_OUT = "P:/Backups/Toplogger/monk_rotterdam_annotated.svg"

# Wall data: region ID maps to area name.
# Label positions come from the SVG's map-wall-center paths (extracted once;
# see the "How it works" section in README for details).
walls = [
    {"name":"Area 1",  "region":"1"},
    {"name":"Area 2",  "region":"2"},
    {"name":"Area 3",  "region":"3"},
    {"name":"Area 4",  "region":"4"},
    {"name":"Area 5",  "region":"5"},
    {"name":"Area 6",  "region":"6"},
    {"name":"Area 7",  "region":"7"},
    {"name":"Area 8",  "region":"8"},
    {"name":"Area 9",  "region":"9"},
    {"name":"Area 10", "region":"10"},
    {"name":"Area 11", "region":"11"},
    {"name":"Area 12", "region":"12"},
    {"name":"Area 13", "region":"13"},
    {"name":"Area 14", "region":"14"},
    {"name":"Area 15", "region":"15"},
    {"name":"Area 16", "region":"16"},
    {"name":"Area 17", "region":"17"},
    {"name":"Area 18", "region":"18"},
    {"name":"Area 19", "region":"26"},
    {"name":"Area 20", "region":"19"},
    {"name":"Area 21", "region":"20"},
    {"name":"Area 22", "region":"21"},
    {"name":"Area 23", "region":"22"},
    {"name":"Area 24", "region":"23"},
    {"name":"Kilter",  "region":"25"},
]

NEW_DAYS = 7   # boulders set within this many days are flagged as new

# ---------------------------------------------------------------------------
# Read SVG and extract wall-center coordinates
# ---------------------------------------------------------------------------
with open(SVG_IN, encoding="utf-8") as f:
    svg = f.read()

# Parse every map-wall-center path to get the true SVG label position.
# These are tiny triangles whose first coordinate is the center of the wall.
svg_centers = {}  # region_id (str) -> (cx, cy)
for m in re.finditer(r'id="map-region-(\d+)"', svg):
    rid = m.group(1)
    chunk = svg[m.start():m.start() + 600]
    c = re.search(r'map-wall-center" d="m([\d.]+)[\s,]([\d.]+)', chunk)
    if c:
        svg_centers[rid] = (float(c.group(1)), float(c.group(2)))

W, H = 945.0, 2232.0

# ---------------------------------------------------------------------------
# Query DB: ticks, current boulders, new boulders
# ---------------------------------------------------------------------------
conn = sqlite3.connect("P:/Backups/Toplogger/toplogger.db")

ticks_per_wall = {}
for row in conn.execute(
    "SELECT c.wall, COUNT(*) FROM ticks t JOIN climbs c ON t.climb_id=c.id GROUP BY c.wall"
):
    if row[0]:
        ticks_per_wall[row[0]] = row[1]

# All currently active boulders: (wall, grade_font, hold_color_hex)
current_boulders = {}   # wall -> list of (grade_font, hex_color)
for row in conn.execute("""
    SELECT wall, grade_font, hold_color_hex
    FROM climbs
    WHERE climb_type='boulder'
      AND (out_at IS NULL OR date(out_at) > date('now'))
    ORDER BY wall, grade
"""):
    wall, grade, color = row
    if wall:
        current_boulders.setdefault(wall, []).append((grade or "?", color or "#888888"))

# New boulders: currently active AND set within NEW_DAYS days
new_per_wall = {}  # wall -> list of grade_font strings
for row in conn.execute(f"""
    SELECT wall, grade_font
    FROM climbs
    WHERE climb_type='boulder'
      AND date(in_at) >= date('now', '-{NEW_DAYS} days')
      AND (out_at IS NULL OR date(out_at) > date('now'))
    ORDER BY wall, grade
"""):
    wall, grade = row
    if wall:
        new_per_wall.setdefault(wall, []).append(grade or "?")

conn.close()

max_ticks = max(ticks_per_wall.values()) if ticks_per_wall else 1

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def heat_colour(n, max_n):
    """White (0 ticks) to deep orange (max ticks)."""
    t = n / max_n
    return f"#{255:02x}{int(255 - t*160):02x}{int(255 - t*230):02x}"

# ---------------------------------------------------------------------------
# 1. Colour each map-region by tick count
# ---------------------------------------------------------------------------
for wall in walls:
    region_id = f"map-region-{wall['region']}"
    n = ticks_per_wall.get(wall["name"], 0)
    colour = heat_colour(n, max_ticks)
    svg = re.sub(
        rf'(id="{re.escape(region_id)}")',
        rf'\1 style="fill:{colour};fill-opacity:0.75;"',
        svg
    )

# ---------------------------------------------------------------------------
# 2. Build label + boulder-dot overlay
# ---------------------------------------------------------------------------
DOT_R    = 9    # radius of each boulder dot
DOT_COLS = 5    # max dots per row
DOT_GAP  = DOT_R * 2 + 3

labels = []

for wall in walls:
    rid = wall["region"]
    name = wall["name"]

    # Use SVG center if available, else fall back to fraction
    if rid in svg_centers:
        x, y = svg_centers[rid]
    else:
        x = wall.get("lx", 0.5) * W
        y = wall.get("ly", 0.5) * H

    short = name.replace("Area ", "")
    n = ticks_per_wall.get(name, 0)
    tick_str = f"({n})" if n else ""

    # Area number label
    labels.append(
        f'<text x="{x:.1f}" y="{y:.1f}" '
        f'text-anchor="middle" font-family="sans-serif" '
        f'font-size="22" font-weight="bold" fill="#222">'
        f'{short}</text>'
    )

    cursor_y = y + 20  # tracks next available y below the number

    # Tick count
    if tick_str:
        cursor_y += 16
        labels.append(
            f'<text x="{x:.1f}" y="{cursor_y:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'font-size="16" fill="#555">'
            f'{tick_str}</text>'
        )

    # NEW badge
    new_grades = new_per_wall.get(name, [])
    if new_grades:
        cursor_y += 20
        grade_txt = " ".join(new_grades)
        pill_w = max(60, len(grade_txt) * 8 + 16)
        labels.append(
            f'<rect x="{x - pill_w/2:.1f}" y="{cursor_y - 13:.1f}" '
            f'width="{pill_w:.0f}" height="16" rx="8" fill="#D62728" fill-opacity="0.88"/>'
        )
        labels.append(
            f'<text x="{x:.1f}" y="{cursor_y:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'font-size="11" font-weight="bold" fill="white">'
            f'NEW {grade_txt}</text>'
        )

    # Boulder dots — one coloured circle per active boulder
    boulders = current_boulders.get(name, [])
    if boulders:
        cursor_y += DOT_R + 6
        rows = [boulders[i:i+DOT_COLS] for i in range(0, len(boulders), DOT_COLS)]
        for row_boulders in rows:
            row_w = len(row_boulders) * DOT_GAP - 3
            start_x = x - row_w / 2 + DOT_R
            for j, (grade, hex_col) in enumerate(row_boulders):
                cx = start_x + j * DOT_GAP
                # White outline so dots are visible against dark regions
                labels.append(
                    f'<circle cx="{cx:.1f}" cy="{cursor_y:.1f}" r="{DOT_R}" '
                    f'fill="{hex_col}" stroke="white" stroke-width="1.5"/>'
                )
                labels.append(
                    f'<text x="{cx:.1f}" y="{cursor_y + 4:.1f}" '
                    f'text-anchor="middle" font-family="sans-serif" '
                    f'font-size="8" font-weight="bold" fill="#222">'
                    f'{grade}</text>'
                )
            cursor_y += DOT_GAP

# ---------------------------------------------------------------------------
# 3. Legend
# ---------------------------------------------------------------------------
total_new = sum(len(v) for v in new_per_wall.values())
total_active = sum(len(v) for v in current_boulders.values())

legend = [
    f'<rect x="20" y="20" width="230" height="155" rx="6" fill="white" fill-opacity="0.88" stroke="#ccc"/>',
    f'<text x="30" y="42" font-family="sans-serif" font-size="15" font-weight="bold" fill="#333">Ticks per area</text>',
]
for i, (label, col) in enumerate([
    ("0",           heat_colour(0, max_ticks)),
    (f"{max_ticks//2}", heat_colour(max_ticks//2, max_ticks)),
    (f"{max_ticks}", heat_colour(max_ticks, max_ticks)),
]):
    lx2, ly2 = 30 + i * 65, 52
    legend.append(f'<rect x="{lx2}" y="{ly2}" width="55" height="16" rx="3" fill="{col}" stroke="#aaa"/>')
    legend.append(f'<text x="{lx2+27}" y="{ly2+28}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#555">{label} ticks</text>')

legend.append(f'<line x1="30" y1="100" x2="220" y2="100" stroke="#ddd"/>')

# NEW badge legend
legend.append(f'<rect x="30" y="108" width="70" height="14" rx="7" fill="#D62728" fill-opacity="0.88"/>')
legend.append(f'<text x="65" y="119" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="bold" fill="white">NEW</text>')
legend.append(f'<text x="108" y="119" font-family="sans-serif" font-size="11" fill="#333">set last {NEW_DAYS}d ({total_new})</text>')

# Boulder dots legend
legend.append(f'<circle cx="40" cy="140" r="{DOT_R}" fill="#FFF100" stroke="white" stroke-width="1.5"/>')
legend.append(f'<circle cx="60" cy="140" r="{DOT_R}" fill="#00BFFF" stroke="white" stroke-width="1.5"/>')
legend.append(f'<circle cx="80" cy="140" r="{DOT_R}" fill="#50C878" stroke="white" stroke-width="1.5"/>')
legend.append(f'<text x="96" y="144" font-family="sans-serif" font-size="11" fill="#333">active boulders ({total_active})</text>')

# ---------------------------------------------------------------------------
# 4. Write output
# ---------------------------------------------------------------------------
overlay = "\n".join(labels + legend)
svg = svg.replace("</svg>", f"<g id='labels'>\n{overlay}\n</g>\n</svg>")

svg = svg.replace(
    '<svg xmlns="http://www.w3.org/2000/svg"',
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(W)} {int(H)}"'
)

with open(SVG_OUT, "w", encoding="utf-8") as f:
    f.write(svg)

print(f"Saved annotated map to {SVG_OUT}")
import subprocess
subprocess.Popen(["start", SVG_OUT], shell=True)
