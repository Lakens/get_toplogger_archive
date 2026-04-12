"""
Toplogger data extractor using GraphQL API.
Authenticates via refresh token (stored in TOPLOGGER_REFRESH_TOKEN env var).
Usage: python fetch_toplogger.py
"""

import json
import os
from datetime import date
import requests

ENDPOINT = "https://app.toplogger.nu/graphql"


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


REFRESH_MUTATION = """
mutation authSigninRefreshToken($refreshToken: JWT!) {
  tokens: authSigninRefreshToken(refreshToken: $refreshToken) {
    access { token expiresAt }
    refresh { token expiresAt }
  }
}
"""

USER_ME_QUERY = """
query userMeStore {
  userMe {
    id
    firstName
    lastName
    email
    gym { id name nameSlug }
    gymUserFavorites {
      gym { id name nameSlug }
    }
  }
}
"""

CLIMBS_QUERY = """
query climbs($gymId: ID!, $climbType: ClimbType!, $userId: ID) {
  climbs(gymId: $gymId, climbType: $climbType) {
    data {
      id
      name
      grade
      climbType
      holds
      wall { id nameLoc }
      holdColor { id color nameLoc }
      inAt
      outAt
      outPlannedAt
      climbUser(userId: $userId) {
        tickType
        totalTries
        tickedFirstAtDate
        triedFirstAtDate
        grade
      }
    }
  }
}
"""


TOKENS_FILE = os.path.join(os.path.dirname(__file__), "tokens.json")

def get_access_token(refresh_token):
    data = gql(REFRESH_MUTATION, {"refreshToken": refresh_token}, token=refresh_token)
    tokens = data["tokens"]
    print(f"Access token valid until: {tokens['access']['expiresAt']}")
    print(f"Refresh token valid until: {tokens['refresh']['expiresAt']}")
    # Persist rotated tokens for next run
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    return tokens["access"]["token"]


def load_refresh_token():
    """Load refresh token from file (preferred) or env var."""
    if os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE) as f:
            tokens = json.load(f)
        return tokens["refresh"]["token"]
    return os.environ.get("TOPLOGGER_REFRESH_TOKEN")


def main():
    refresh_token = load_refresh_token()
    if not refresh_token:
        refresh_token = input("Paste refresh token: ").strip()

    print("Getting access token...")
    access_token = get_access_token(refresh_token)

    print("\nFetching user info...")
    me = gql(USER_ME_QUERY, token=access_token)["userMe"]
    print(f"Logged in as: {me['firstName']} {me['lastName']} ({me['email']})")
    print(f"Home gym: {me['gym']['name']} (id={me['gym']['id']})")

    user_id = me["id"]
    gym_id = me["gym"]["id"]
    today = date.today().isoformat()

    for climb_type in ["boulder", "route"]:
        print(f"\nFetching {climb_type}s from {me['gym']['name']}...")
        data = gql(CLIMBS_QUERY, {"gymId": gym_id, "climbType": climb_type, "userId": user_id}, token=access_token)
        climbs = data["climbs"]["data"]

        # Filter to climbs ticked today
        today_ticks = [
            c for c in climbs
            if c.get("climbUser")
            and c["climbUser"].get("tickedFirstAtDate")
            and c["climbUser"]["tickedFirstAtDate"].startswith(today)
        ]

        print(f"Climbed today ({today}): {len(today_ticks)} {climb_type}(s)")
        for c in today_ticks:
            cu = c["climbUser"]
            grade = c.get("grade", "?")
            color = c.get("holdColor", {}).get("nameLoc", "?")
            wall = c.get("wall", {}).get("nameLoc", "?")
            tick = cu.get("tickType", "?")
            tries = cu.get("totalTries", "?")
            print(f"  - {color} | Grade {grade} | Wall: {wall} | Tick: {tick} | Tries: {tries}")

        fname = f"today_{climb_type}s.json"
        with open(fname, "w") as f:
            json.dump(today_ticks, f, indent=2)
        print(f"  Saved to {fname}")

    # Also save all climbs for reference
    print("\nFetching all climbs for full history...")
    for climb_type in ["boulder", "route"]:
        data = gql(CLIMBS_QUERY, {"gymId": gym_id, "climbType": climb_type, "userId": user_id}, token=access_token)
        climbs = data["climbs"]["data"]
        all_ticked = [c for c in climbs if c.get("climbUser") and c["climbUser"].get("tickedFirstAtDate")]
        fname = f"all_{climb_type}s_ticked.json"
        with open(fname, "w") as f:
            json.dump(all_ticked, f, indent=2)
        print(f"  {climb_type}: {len(all_ticked)} total ticks -> saved to {fname}")


if __name__ == "__main__":
    main()
