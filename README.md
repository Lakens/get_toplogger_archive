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

## Using the database in R

```r
library(DBI)
library(RSQLite)

con <- dbConnect(SQLite(), "P:/Backups/Toplogger/toplogger.db")
sessions <- dbReadTable(con, "sessions")
ticks    <- dbReadTable(con, "ticks")
dbDisconnect(con)
```
