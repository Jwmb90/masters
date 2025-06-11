import time
import requests

# Caching variables
_cached_mapping = None
_last_scrape = 0
CACHE_DURATION = 600  # seconds

# ESPN golf API endpoints
API_PLAYERS_URL = "https://site.web.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard/players"

def get_leaderboard_data(tournament_id="401703515"):
    """
    Fetches and parses the ESPN Golf Leaderboard via the unofficial ESPN API.
    Returns a list of dicts with keys: 'player', 'score', 'today', and 'thru'.
    On error, returns an empty list.
    """
    params = {
        "region": "us",    # your region
        "lang": "en",      # language
        "event": tournament_id
    }
    try:
        resp = requests.get(API_PLAYERS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print("Error fetching data from ESPN API:", e)
        return []

    leaderboard = []
    # The API returns a top-level "competitors" list
    for comp in data.get("competitors", []):
        # Name is under comp["athlete"]["displayName"]
        athlete = comp.get("athlete", {})
        player_name = athlete.get("displayName") or athlete.get("fullName") or "N/A"

        # Stats is a list of stat objects; pull out total, today, and thru
        stats = comp.get("stats", [])
        score = today = thru = "N/A"
        for s in stats:
            key = s.get("name", "").lower()
            # ESPN uses "total", "today", "thru" as the stat names
            if key == "total":
                score = s.get("displayValue") or s.get("value")
            elif key == "today":
                today = s.get("displayValue") or s.get("value")
            elif key == "thru":
                thru = s.get("displayValue") or s.get("value")

        leaderboard.append({
            "player": player_name,
            "score": score,
            "today": today,
            "thru": thru
        })

    return leaderboard

def get_leaderboard_mapping_cached(tournament_id="401703515"):
    """
    Returns a dict mapping player -> {score, today, thru},
    refreshing the cache if older than CACHE_DURATION.
    """
    global _cached_mapping, _last_scrape
    now = time.time()
    if _cached_mapping is None or (now - _last_scrape) > CACHE_DURATION:
        data = get_leaderboard_data(tournament_id)
        _cached_mapping = {
            entry["player"]: {
                "score": entry["score"],
                "today": entry["today"],
                "thru": entry["thru"]
            }
            for entry in data
        }
        _last_scrape = now
    return _cached_mapping

def force_refresh_leaderboard(tournament_id="401703515"):
    """
    Immediately refreshes the cache for the given tournament
    and returns the raw leaderboard list.
    """
    global _cached_mapping, _last_scrape
    data = get_leaderboard_data(tournament_id)
    _cached_mapping = {
        entry["player"]: {
            "score": entry["score"],
            "today": entry["today"],
            "thru": entry["thru"]
        }
        for entry in data
    }
    _last_scrape = time.time()
    return data
