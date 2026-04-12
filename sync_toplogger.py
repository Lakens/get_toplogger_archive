"""
Toplogger -> SQLite sync.
Fetches all-time session history and ticks, stores in P:/Backups/Toplogger/toplogger.db

Tables:
  gyms       - gyms you've climbed at
  sessions   - one row per gym visit (climbDay), with grade stats
  ticks      - one row per climb attempted/completed per session
  climbs     - climb metadata (name, grade, color, wall)

Usage:
  python sync_toplogger.py            # interactive, prints progress
  python sync_toplogger.py --silent   # for scheduled runs; logs to sync_log.txt
                                      # shows Windows notification if re-auth needed

Re-run any time to refresh; all writes are upserts (safe to re-run).
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
import requests

SILENT = "--silent" in sys.argv
LOG_DIR = "P:/Backups/Toplogger"
LOG_FILE = os.path.join(LOG_DIR, "sync_log.txt")
AUTH_INSTRUCTIONS_FILE = os.path.join(LOG_DIR, "AUTH_NEEDED.md")

# Set up logging: always write to file; also print to console if not silent
handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
if not SILENT:
    handlers.append(logging.StreamHandler(sys.stdout))
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%Y-%m-%d %H:%M", handlers=handlers)
log = logging.getLogger()


def notify_windows(title, message):
    """Show a Windows toast notification via PowerShell."""
    ps = f"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Warning
$n.Visible = $true
$n.ShowBalloonTip(15000, '{title}', '{message}', [System.Windows.Forms.ToolTipIcon]::Warning)
Start-Sleep -Seconds 2
$n.Dispose()
"""
    subprocess.Popen(["powershell", "-WindowStyle", "Hidden", "-Command", ps])


def write_auth_instructions():
    """Write a step-by-step guide for refreshing the token."""
    instructions = """# Toplogger Sync: Re-authentication Needed

Your Toplogger refresh token has expired. Follow these steps to get a new one:

## Steps

1. Open **Google Chrome** (or any Chromium browser)
2. Go to [https://app.toplogger.nu](https://app.toplogger.nu) and log in if needed
3. Press **F12** to open Developer Tools
4. Click the **Application** tab (top menu in DevTools)
5. In the left sidebar, expand **Local Storage** and click `https://app.toplogger.nu`
6. Find the key named **`auth`** (or similar — look for a value that starts with `{"access":`)
7. **Copy the entire value** (it looks like: `{"access":{"token":"eyJ..."},"refresh":{"token":"eyJ..."}}`)
8. Open this file in a text editor:
   `C:\\Users\\dlakens\\Documents\\toplogger\\tokens.json`
9. **Replace the entire contents** of that file with the value you copied in step 7
10. Save the file

The next scheduled sync (Sunday 16:00) will pick it up automatically,
or run manually: `python C:\\Users\\dlakens\\Documents\\toplogger\\sync_toplogger.py`

## Delete this file when done
Once the sync runs successfully, you can delete this file.
"""
    with open(AUTH_INSTRUCTIONS_FILE, "w", encoding="utf-8") as f:
        f.write(instructions)
    log.info(f"Auth instructions written to {AUTH_INSTRUCTIONS_FILE}")

ENDPOINT   = "https://app.toplogger.nu/graphql"
DB_PATH    = "P:/Backups/Toplogger/toplogger.db"
TOKENS_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")

# ---------------------------------------------------------------------------
# Grade conversion: Toplogger stores grades as round(decimal * 100)
# where decimal steps in 1/6 increments: 6.0=6a, 6.17=6a+, 6.33=6b, etc.
# ---------------------------------------------------------------------------
_GRADE_STEPS = [
    (3.00,"3"),  (3.17,"3+"), (3.33,"3b"),(3.50,"3b+"),(3.67,"3c"),(3.83,"3c+"),
    (4.00,"4"),  (4.17,"4+"), (4.33,"4b"),(4.50,"4b+"),(4.67,"4c"),(4.83,"4c+"),
    (5.00,"5a"), (5.17,"5a+"),(5.33,"5b"),(5.50,"5b+"),(5.67,"5c"),(5.83,"5c+"),
    (6.00,"6a"), (6.17,"6a+"),(6.33,"6b"),(6.50,"6b+"),(6.67,"6c"),(6.83,"6c+"),
    (7.00,"7a"), (7.17,"7a+"),(7.33,"7b"),(7.50,"7b+"),(7.67,"7c"),(7.83,"7c+"),
    (8.00,"8a"), (8.17,"8a+"),(8.33,"8b"),(8.50,"8b+"),(8.67,"8c"),(8.83,"8c+"),
    (9.00,"9a"),
]
FONT_GRADES = {round(d * 100): label for d, label in _GRADE_STEPS}

def to_font(grade):
    if not grade:
        return None
    grade = int(grade)
    if grade == 0:
        return "ungraded"
    closest = min(FONT_GRADES.keys(), key=lambda k: abs(k - grade))
    return FONT_GRADES[closest]


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def gql(query, variables=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(ENDPOINT, json={"query": query, "variables": variables or {}}, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise Exception(json.dumps(data["errors"], indent=2))
    return data["data"]


def get_access_token():
    if not os.path.exists(TOKENS_FILE):
        raise FileNotFoundError(f"tokens.json not found at {TOKENS_FILE}")
    with open(TOKENS_FILE) as f:
        tokens = json.load(f)
    refresh = tokens["refresh"]["token"]
    try:
        data = gql("""
            mutation authSigninRefreshToken($refreshToken: JWT!) {
              tokens: authSigninRefreshToken(refreshToken: $refreshToken) {
                access { token expiresAt }
                refresh { token expiresAt }
              }
            }
        """, {"refreshToken": refresh}, token=refresh)
    except Exception as e:
        raise AuthExpiredError(str(e))
    new_tokens = data["tokens"]
    with open(TOKENS_FILE, "w") as f:
        json.dump(new_tokens, f, indent=2)
    return new_tokens["access"]["token"]


class AuthExpiredError(Exception):
    pass


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gyms (
            id          TEXT PRIMARY KEY,
            name        TEXT,
            name_slug   TEXT
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id                          TEXT PRIMARY KEY,
            stats_at_date               TEXT,
            gym_id                      TEXT,
            gym_name                    TEXT,
            boulders_grade_trend        INTEGER,
            boulders_grade_trend_font   TEXT,
            boulders_grade              INTEGER,
            boulders_grade_font         TEXT,
            boulders_grade_max          INTEGER,
            boulders_grade_max_font     TEXT,
            boulders_total_tries        INTEGER,
            routes_grade_trend          INTEGER,
            routes_grade                INTEGER,
            routes_grade_max            INTEGER,
            routes_total_tries          INTEGER,
            title                       TEXT,
            description                 TEXT,
            grade_distribution_boulders TEXT,
            grade_distribution_routes   TEXT,
            synced_at                   TEXT,
            FOREIGN KEY (gym_id) REFERENCES gyms(id)
        );

        CREATE TABLE IF NOT EXISTS climbs (
            id              TEXT PRIMARY KEY,
            gym_id          TEXT,
            name            TEXT,
            grade           INTEGER,
            grade_font      TEXT,
            climb_type      TEXT,
            hold_color      TEXT,
            hold_color_hex  TEXT,
            wall            TEXT,
            in_at           TEXT,
            out_at          TEXT,
            out_planned_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS ticks (
            id                      TEXT PRIMARY KEY,
            climb_id                TEXT,
            session_id              TEXT,
            gym_id                  TEXT,
            tick_type               INTEGER,
            total_tries             INTEGER,
            grade                   INTEGER,
            grade_font              TEXT,
            ticked_first_at_date    TEXT,
            tried_first_at_date     TEXT,
            points                  REAL,
            points_expire_at_date   TEXT,
            was_repeat              INTEGER,
            FOREIGN KEY (climb_id) REFERENCES climbs(id),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_date  ON sessions(stats_at_date);
        CREATE INDEX IF NOT EXISTS idx_sessions_gym   ON sessions(gym_id);
        CREATE INDEX IF NOT EXISTS idx_ticks_session  ON ticks(session_id);
        CREATE INDEX IF NOT EXISTS idx_ticks_climb    ON ticks(climb_id);
        CREATE INDEX IF NOT EXISTS idx_ticks_date     ON ticks(ticked_first_at_date);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Fetch & sync gyms
# ---------------------------------------------------------------------------
def sync_gyms(conn, token):
    log.info("Syncing gyms...")
    data = gql("{ gymUsersMe { gym { id name nameSlug } } }", token=token)
    gyms = [g["gym"] for g in data["gymUsersMe"]]
    for g in gyms:
        conn.execute("""
            INSERT INTO gyms(id, name, name_slug) VALUES(?,?,?)
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, name_slug=excluded.name_slug
        """, (g["id"], g["name"], g["nameSlug"]))
    conn.commit()
    log.info(f"  {len(gyms)} gyms synced")
    return gyms


# ---------------------------------------------------------------------------
# Fetch & sync all-time sessions
# ---------------------------------------------------------------------------
SESSIONS_QUERY = """
query climbDaysAllTime($userId: ID!) {
  climbDays(userId: $userId, gymIdNotNull: true) {
    id
    statsAtDate
    bouldersGrade
    bouldersDayGrade
    bouldersDayGradeMax
    bouldersTotalTries
    routesGrade
    routesDayGrade
    routesDayGradeMax
    routesTotalTries
    title
    description
    gym { id name }
    gradeDistributionBoulders
    gradeDistributionRoutes
  }
}
"""

def sync_sessions(conn, token, user_id):
    log.info("Syncing sessions (all-time)...")
    data = gql(SESSIONS_QUERY, {"userId": user_id}, token=token)
    sessions = data["climbDays"]
    synced_at = datetime.now(timezone.utc).isoformat()
    for s in sessions:
        conn.execute("""
            INSERT INTO sessions(
                id, stats_at_date, gym_id, gym_name,
                boulders_grade_trend, boulders_grade_trend_font,
                boulders_grade, boulders_grade_font,
                boulders_grade_max, boulders_grade_max_font,
                boulders_total_tries,
                routes_grade_trend,
                routes_grade, routes_grade_max, routes_total_tries,
                title, description,
                grade_distribution_boulders, grade_distribution_routes,
                synced_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                boulders_grade_trend=excluded.boulders_grade_trend,
                boulders_grade_trend_font=excluded.boulders_grade_trend_font,
                boulders_grade=excluded.boulders_grade,
                boulders_grade_font=excluded.boulders_grade_font,
                boulders_grade_max=excluded.boulders_grade_max,
                boulders_grade_max_font=excluded.boulders_grade_max_font,
                boulders_total_tries=excluded.boulders_total_tries,
                routes_grade_trend=excluded.routes_grade_trend,
                routes_grade=excluded.routes_grade,
                routes_grade_max=excluded.routes_grade_max,
                routes_total_tries=excluded.routes_total_tries,
                title=excluded.title,
                description=excluded.description,
                grade_distribution_boulders=excluded.grade_distribution_boulders,
                grade_distribution_routes=excluded.grade_distribution_routes,
                synced_at=excluded.synced_at
        """, (
            s["id"], s["statsAtDate"],
            s.get("gym", {}).get("id") if s.get("gym") else None,
            s.get("gym", {}).get("name") if s.get("gym") else None,
            s.get("bouldersGrade"), to_font(s.get("bouldersGrade")),
            s.get("bouldersDayGrade"), to_font(s.get("bouldersDayGrade")),
            s.get("bouldersDayGradeMax"), to_font(s.get("bouldersDayGradeMax")),
            s.get("bouldersTotalTries"),
            s.get("routesGrade"),
            s.get("routesDayGrade"), s.get("routesDayGradeMax"),
            s.get("routesTotalTries"),
            s.get("title"), s.get("description"),
            json.dumps(s.get("gradeDistributionBoulders")),
            json.dumps(s.get("gradeDistributionRoutes")),
            synced_at
        ))
    conn.commit()
    log.info(f"  {len(sessions)} sessions synced")
    return sessions


# ---------------------------------------------------------------------------
# Fetch & sync ticks (climbUsers per session via climbUserDays)
# ---------------------------------------------------------------------------
TICKS_QUERY = """
query climbDayTicks($userId: ID!) {
  climbDays(userId: $userId, gymIdNotNull: true) {
    id
    statsAtDate
    gym { id }
    climbUserDaysBoulders: climbUserDays(climbType: "boulder") {
      id
      tickType
      wasRepeat
      climb {
        id name grade climbType
        holdColor { nameLoc color }
        wall { nameLoc }
        inAt outAt outPlannedAt
        gym { id }
      }
    }
    climbUserDaysRoutes: climbUserDays(climbType: "route") {
      id
      tickType
      wasRepeat
      climb {
        id name grade climbType
        holdColor { nameLoc color }
        wall { nameLoc }
        inAt outAt outPlannedAt
        gym { id }
      }
    }
  }
}
"""

def sync_ticks(conn, token, user_id):
    log.info("Syncing per-session ticks (this may take a moment)...")
    data = gql(TICKS_QUERY, {"userId": user_id}, token=token)
    sessions = data["climbDays"]

    tick_count = 0
    climb_count = 0

    for session in sessions:
        session_id = session["id"]
        gym_id = session.get("gym", {}).get("id") if session.get("gym") else None
        all_ticks = (session.get("climbUserDaysBoulders") or []) + (session.get("climbUserDaysRoutes") or [])

        for t in all_ticks:
            climb = t.get("climb")
            if not climb:
                continue

            # Upsert climb metadata
            conn.execute("""
                INSERT INTO climbs(id, gym_id, name, grade, grade_font, climb_type,
                                   hold_color, hold_color_hex, wall, in_at, out_at, out_planned_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, grade=excluded.grade, grade_font=excluded.grade_font,
                    hold_color=excluded.hold_color, hold_color_hex=excluded.hold_color_hex,
                    wall=excluded.wall, out_at=excluded.out_at, out_planned_at=excluded.out_planned_at
            """, (
                climb["id"],
                climb.get("gym", {}).get("id") if climb.get("gym") else gym_id,
                climb.get("name"),
                climb.get("grade"), to_font(climb.get("grade")),
                climb.get("climbType"),
                climb.get("holdColor", {}).get("nameLoc") if climb.get("holdColor") else None,
                climb.get("holdColor", {}).get("color") if climb.get("holdColor") else None,
                climb.get("wall", {}).get("nameLoc") if climb.get("wall") else None,
                climb.get("inAt"), climb.get("outAt"), climb.get("outPlannedAt"),
            ))
            climb_count += 1

            # Upsert tick
            conn.execute("""
                INSERT INTO ticks(id, climb_id, session_id, gym_id,
                                  tick_type, grade, grade_font,
                                  ticked_first_at_date, was_repeat)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    tick_type=excluded.tick_type,
                    ticked_first_at_date=excluded.ticked_first_at_date,
                    was_repeat=excluded.was_repeat
            """, (
                t["id"], climb["id"], session_id, gym_id,
                t.get("tickType"),
                climb.get("grade"), to_font(climb.get("grade")),
                session.get("statsAtDate"),
                1 if t.get("wasRepeat") else 0,
            ))
            tick_count += 1

    conn.commit()
    log.info(f"  {tick_count} ticks and {climb_count} climbs synced")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    log.info("=== Toplogger sync started ===")

    try:
        log.info("Authenticating...")
        token = get_access_token()
    except AuthExpiredError as e:
        log.error("Authentication failed — refresh token has expired.")
        write_auth_instructions()
        notify_windows(
            "Toplogger Sync: Login Needed",
            f"Refresh token expired. See {AUTH_INSTRUCTIONS_FILE} for instructions."
        )
        sys.exit(1)
    except FileNotFoundError as e:
        log.error(f"tokens.json not found: {e}")
        write_auth_instructions()
        notify_windows("Toplogger Sync: Setup Needed", str(e))
        sys.exit(1)

    try:
        log.info("Fetching user info...")
        me = gql("{ userMe { id firstName lastName email } }", token=token)["userMe"]
        user_id = me["id"]
        log.info(f"User: {me['firstName']} {me['lastName']}")

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        init_db(conn)

        sync_gyms(conn, token)
        sync_sessions(conn, token, user_id)
        sync_ticks(conn, token, user_id)

        for table in ["gyms", "sessions", "climbs", "ticks"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            log.info(f"  {table}: {count} rows")

        oldest = conn.execute("SELECT MIN(stats_at_date) FROM sessions").fetchone()[0]
        newest = conn.execute("SELECT MAX(stats_at_date) FROM sessions").fetchone()[0]
        log.info(f"  Session range: {oldest} to {newest}")
        conn.close()

        # Remove stale auth instructions if sync succeeded
        if os.path.exists(AUTH_INSTRUCTIONS_FILE):
            os.remove(AUTH_INSTRUCTIONS_FILE)

        log.info("=== Sync complete ===")

    except Exception as e:
        log.error(f"Sync failed: {e}", exc_info=True)
        if SILENT:
            notify_windows("Toplogger Sync Failed", str(e)[:100])
        sys.exit(1)


if __name__ == "__main__":
    main()
