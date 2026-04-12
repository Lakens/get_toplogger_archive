"""
Annotates the Monk Rotterdam floorplan SVG with:
  - Area labels at the correct positions
  - Regions coloured by number of ticks (from the SQLite DB)
Saves to P:/Backups/Toplogger/monk_rotterdam_annotated.svg
"""

import json, re, sqlite3
import requests

SVG_IN  = "P:/Backups/Toplogger/monk_rotterdam_floorplan.svg"
SVG_OUT = "P:/Backups/Toplogger/monk_rotterdam_annotated.svg"

# Wall data with label positions (labelX/Y are 0-1 fractions of SVG viewport)
walls = [
    {"name":"Area 1",  "region":"1",  "lx":0.085685,"ly":0.855546},
    {"name":"Area 2",  "region":"2",  "lx":0.079611,"ly":0.804721},
    {"name":"Area 3",  "region":"3",  "lx":0.11815, "ly":0.727829},
    {"name":"Area 4",  "region":"4",  "lx":0.13949, "ly":0.658361},
    {"name":"Area 5",  "region":"5",  "lx":0.126273,"ly":0.625583},
    {"name":"Area 6",  "region":"6",  "lx":0.187568,"ly":0.451226},
    {"name":"Area 7",  "region":"7",  "lx":0.168086,"ly":0.411411},
    {"name":"Area 8",  "region":"8",  "lx":0.22814, "ly":0.378246},
    {"name":"Area 9",  "region":"9",  "lx":0.247369,"ly":0.423981},
    {"name":"Area 10", "region":"10", "lx":0.201103,"ly":0.208815},
    {"name":"Area 11", "region":"11", "lx":0.252241,"ly":0.190407},
    {"name":"Area 12", "region":"12", "lx":0.286786,"ly":0.212711},
    {"name":"Area 13", "region":"13", "lx":0.423033,"ly":0.186577},
    {"name":"Area 14", "region":"14", "lx":0.551833,"ly":0.181914},
    {"name":"Area 15", "region":"15", "lx":0.652537,"ly":0.219208},
    {"name":"Area 16", "region":"16", "lx":0.671227,"ly":0.315044},
    {"name":"Area 17", "region":"17", "lx":0.634686,"ly":0.39881},
    {"name":"Area 18", "region":"18", "lx":0.656465,"ly":0.437775},
    {"name":"Area 19", "region":"26", "lx":0.735249,"ly":0.539435},
    {"name":"Area 20", "region":"19", "lx":0.660802,"ly":0.617874},
    {"name":"Area 21", "region":"20", "lx":0.560159,"ly":0.647788},
    {"name":"Area 22", "region":"21", "lx":0.544035,"ly":0.725261},
    {"name":"Area 23", "region":"22", "lx":0.579433,"ly":0.812704},
    {"name":"Area 24", "region":"23", "lx":0.633761,"ly":0.891951},
    {"name":"Kilter",  "region":"25", "lx":0.234838,"ly":0.009239},
]

# Ticks per area and new boulders from DB
NEW_DAYS = 7   # boulders set within this many days are flagged as new

conn = sqlite3.connect("P:/Backups/Toplogger/toplogger.db")
ticks_per_wall = {}
for row in conn.execute("SELECT c.wall, COUNT(*) FROM ticks t JOIN climbs c ON t.climb_id=c.id GROUP BY c.wall"):
    if row[0]:
        ticks_per_wall[row[0]] = row[1]

# New boulders: currently active, set within NEW_DAYS days
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

def heat_colour(n, max_n):
    """Orange heat colour from white (0) to deep orange (max)."""
    t = n / max_n
    r = int(255)
    g = int(255 - t * 160)
    b = int(255 - t * 230)
    return f"#{r:02x}{g:02x}{b:02x}"

# Read SVG
with open(SVG_IN, encoding="utf-8") as f:
    svg = f.read()

# Determine SVG coordinate space from the background path
# Background: m0 0h945v1416.0171... => width=945, total height ~2232
W, H = 945.0, 2232.0

# 1. Colour each map-region by tick count
for wall in walls:
    region_id = f"map-region-{wall['region']}"
    n = ticks_per_wall.get(wall["name"], 0)
    colour = heat_colour(n, max_ticks)
    # Replace fill on the element with this id
    # Pattern: id="map-region-X" ... fill="..."  OR add fill style
    svg = re.sub(
        rf'(id="{re.escape(region_id)}")',
        rf'\1 style="fill:{colour};fill-opacity:0.75;"',
        svg
    )

# 2. Build label overlay — insert before closing </svg>
labels = []
for wall in walls:
    x = wall["lx"] * W
    y = wall["ly"] * H
    name = wall["name"]
    n = ticks_per_wall.get(name, 0)
    short = name.replace("Area ", "")  # "Area 7" → "7", "Kilter" stays
    tick_str = f"({n})" if n else ""
    labels.append(
        f'<text x="{x:.1f}" y="{y:.1f}" '
        f'text-anchor="middle" font-family="sans-serif" '
        f'font-size="22" font-weight="bold" fill="#222">'
        f'{short}</text>'
    )
    if tick_str:
        labels.append(
            f'<text x="{x:.1f}" y="{y+24:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'font-size="16" fill="#555">'
            f'{tick_str}</text>'
        )

    # NEW badge: red pill + grade list
    new_grades = new_per_wall.get(name, [])
    if new_grades:
        badge_y = y + (48 if tick_str else 24)
        grade_txt = " ".join(new_grades)
        pill_w = max(60, len(grade_txt) * 8 + 16)
        labels.append(
            f'<rect x="{x - pill_w/2:.1f}" y="{badge_y - 14:.1f}" '
            f'width="{pill_w:.0f}" height="16" rx="8" fill="#D62728" fill-opacity="0.88"/>'
        )
        labels.append(
            f'<text x="{x:.1f}" y="{badge_y:.1f}" '
            f'text-anchor="middle" font-family="sans-serif" '
            f'font-size="11" font-weight="bold" fill="white">'
            f'NEW {grade_txt}</text>'
        )

# Add a legend
legend = [
    f'<rect x="20" y="20" width="220" height="115" rx="6" fill="white" fill-opacity="0.85" stroke="#ccc"/>',
    f'<text x="30" y="42" font-family="sans-serif" font-size="16" font-weight="bold" fill="#333">Ticks per area</text>',
]
for i, (label, col) in enumerate([("0 ticks", heat_colour(0, max_ticks)),
                                    (f"{max_ticks//2}", heat_colour(max_ticks//2, max_ticks)),
                                    (f"{max_ticks} ticks", heat_colour(max_ticks, max_ticks))]):
    lx, ly = 30 + i*65, 55
    legend.append(f'<rect x="{lx}" y="{ly}" width="55" height="18" rx="3" fill="{col}" stroke="#aaa"/>')
    legend.append(f'<text x="{lx+27}" y="{ly+30}" text-anchor="middle" font-family="sans-serif" font-size="13" fill="#333">{label}</text>')

# NEW badge legend entry
total_new = sum(len(v) for v in new_per_wall.values())
legend.append(f'<rect x="30" y="98" width="80" height="14" rx="7" fill="#D62728" fill-opacity="0.88"/>')
legend.append(f'<text x="70" y="109" text-anchor="middle" font-family="sans-serif" font-size="11" font-weight="bold" fill="white">NEW</text>')
legend.append(f'<text x="120" y="109" font-family="sans-serif" font-size="12" fill="#333">set in last {NEW_DAYS}d ({total_new})</text>')

overlay = "\n".join(labels + legend)
svg = svg.replace("</svg>", f"<g id='labels'>\n{overlay}\n</g>\n</svg>")

# Fix SVG to have explicit viewBox so it renders at the right size
svg = svg.replace(
    '<svg xmlns="http://www.w3.org/2000/svg"',
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {int(W)} {int(H)}"'
)

with open(SVG_OUT, "w", encoding="utf-8") as f:
    f.write(svg)

print(f"Saved annotated map to {SVG_OUT}")
import subprocess
subprocess.Popen(["start", SVG_OUT], shell=True)
