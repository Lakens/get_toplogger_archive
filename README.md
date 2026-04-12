# get_toplogger_archive

Syncs your personal [TopLogger](https://toplogger.nu) climbing data to a local SQLite database for use in R, Python, or other tools.

## What it does

- Authenticates via a refresh token (no reCAPTCHA, no scraping)
- Fetches all-time session history and per-session tick data via the TopLogger GraphQL API
- Stores everything in a portable SQLite database
- Runs silently on a weekly schedule; notifies you only when re-authentication is needed

## Database schema

| Table      | Contents |
|------------|----------|
| `gyms`     | Gyms you have climbed at |
| `sessions` | One row per gym visit — date, grade trend, session grade, max grade, total tries |
| `climbs`   | Climb metadata — name, grade, color, wall, set/removed dates |
| `ticks`    | One row per climb logged per session — tick type, repeat, grade |

Grades are stored both as raw TopLogger integers and as Font scale strings (e.g. `6b+`).

## Setup

### 1. Install dependencies

```bash
pip install requests
```

### 2. Get your refresh token

1. Log into [app.toplogger.nu](https://app.toplogger.nu) in Chrome
2. Press **F12** → **Application** tab → **Local Storage** → `https://app.toplogger.nu`
3. Find the key whose value starts with `{"access":...}`
4. Copy the full value and save it as `tokens.json` in this folder

### 3. Configure paths

Edit the top of `sync_toplogger.py` to set your preferred database path:

```python
DB_PATH = "P:/Backups/Toplogger/toplogger.db"
```

### 4. Run

```bash
python sync_toplogger.py          # interactive
python sync_toplogger.py --silent # for scheduled/background runs
```

## Scheduled sync (Windows Task Scheduler)

The included `schedule_sync.ps1` script registers a weekly Sunday 16:00 task:

```powershell
powershell -ExecutionPolicy Bypass -File schedule_sync.ps1
```

## Re-authentication

The refresh token expires roughly every two weeks. When it does:

- A `AUTH_NEEDED.md` file appears in your database folder with step-by-step instructions
- A Windows notification is shown (if running silently)

## Gym floorplan map

`annotate_map.py` generates an SVG heatmap of a gym's floorplan, coloured by how many times you've ticked each wall area.

### What it produces

- Each wall region is filled with a white-to-orange heat colour (more ticks = deeper orange)
- Area numbers and tick counts are overlaid at the correct label positions
- A legend is added in the top-left corner
- Output is saved to `P:/Backups/Toplogger/monk_rotterdam_annotated.svg` and opened automatically

### How to get the data it needs

The script needs two things from the TopLogger API. Both are printed if you add a debug query, but the easiest way is to inspect the app:

**1. The floorplan SVG URL**

1. Open [app.toplogger.nu](https://app.toplogger.nu) and navigate to your gym's wall map
2. Press **F12** → **Network** tab → filter by **Img** or **Fetch/XHR**
3. Look for a request to `uploads.toplogger.nu/gyms/<gym-slug>/floorplans/…svg`
4. Copy that URL and download the file — save it as `monk_rotterdam_floorplan.svg` (or rename the variable `SVG_IN` at the top of the script)

Alternatively, run `sync_toplogger.py` first; it queries the `gyms` table which contains the gym slug. The floorplan URL follows the pattern:
```
https://uploads.toplogger.nu/gyms/<gym-slug>/floorplans/<floorplan-id>.svg
```

**2. The wall label positions**

Each wall in TopLogger has `labelX` and `labelY` fields (0–1 fractions of the SVG viewport). Fetch them by running this against the GraphQL API after a successful token refresh:

```graphql
query {
  gym(id: YOUR_GYM_ID) {
    walls {
      name
      idOnFloorplan
      labelX
      labelY
    }
  }
}
```

The `walls` list at the top of `annotate_map.py` was generated from this query for Monk Rotterdam (gym id 567). To use a different gym, replace the list with your gym's data and update `SVG_IN`/`SVG_OUT`.

### New boulders

The map highlights boulders set in the **last 7 days** with a red NEW badge showing the grades (e.g. `NEW 6a+ 6b`). The legend counts how many new boulders are across the whole gym.

This works because TopLogger stores the date each boulder was set (`in_at`) and its planned removal date (`out_at`). After your weekly sync, the map automatically reflects whatever was set or replaced since the previous run.

To change the new-boulder window, edit `NEW_DAYS` at the top of the script:

```python
NEW_DAYS = 7   # default: flag boulders set in the last week
```

You can also query new boulders directly from the database:

```python
import sqlite3
conn = sqlite3.connect("P:/Backups/Toplogger/toplogger.db")
rows = conn.execute("""
    SELECT wall, grade_font, hold_color, date(in_at) as set_date
    FROM climbs
    WHERE climb_type = 'boulder'
      AND date(in_at) >= date('now', '-7 days')
      AND (out_at IS NULL OR date(out_at) > date('now'))
    ORDER BY in_at DESC
""").fetchall()
for r in rows:
    print(r)
conn.close()
```

Or in R:

```r
library(DBI); library(RSQLite); library(dplyr)
con <- dbConnect(SQLite(), "P:/Backups/Toplogger/toplogger.db")
new_boulders <- tbl(con, "climbs") |>
  filter(climb_type == "boulder",
         in_at >= as.character(Sys.Date() - 7),
         is.na(out_at) | out_at > as.character(Sys.Date())) |>
  select(wall, grade_font, hold_color, in_at) |>
  arrange(desc(in_at)) |>
  collect()
dbDisconnect(con)
```

Because `out_at` is also stored, you can equally query **which boulders were recently removed** — useful for understanding how quickly a gym rotates its routes:

```python
rows = conn.execute("""
    SELECT wall, grade_font, hold_color, date(out_at) as removed_date
    FROM climbs
    WHERE climb_type = 'boulder'
      AND date(out_at) >= date('now', '-30 days')
    ORDER BY out_at DESC
""").fetchall()
```

### Running it

```bash
pip install requests   # already installed if you ran sync_toplogger.py
python annotate_map.py
```

The script reads tick counts and set dates directly from the local SQLite database, so `sync_toplogger.py` must have been run at least once first.

---

## Using the database in R

```r
library(DBI)
library(RSQLite)

con <- dbConnect(SQLite(), "P:/Backups/Toplogger/toplogger.db")
sessions <- dbReadTable(con, "sessions")
ticks    <- dbReadTable(con, "ticks")
dbDisconnect(con)
```
