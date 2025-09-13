import os, json, pathlib, requests
from rapidfuzz import process, fuzz

import logging
import random

import time

from functools import cache
from cachetools import TTLCache, cached
from xml.dom import NamespaceErr

logger = logging.getLogger(__name__)

# custom TTL cache with jittered expiry
class JitteredTTLCache(TTLCache):
    def __init__(self, maxsize=1024, ttl=900, jitter=60):
        super().__init__(maxsize=maxsize, ttl=int(ttl) + int(jitter))
        self.base_ttl = int(ttl)
        self.jitter = int(jitter)
        self._expiries = {}

    def __setitem__(self, key, value):
        expiry = time.monotonic() + (self.base_ttl + random.randint(-self.jitter, self.jitter))
        self._expiries[key] = expiry
        return super().__setitem__(key, value)

    def __getitem__(self, key):
        expiry = self._expiries.get(key)
        if expiry is not None and time.monotonic() >= expiry:
            self._expiries.pop(key, None)
            super().pop(key, None)
            raise KeyError(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        try:
            return self.__getitem__(key)
        except KeyError:
            return default

    def pop(self, key, *args):
        self._expiries.pop(key, None)
        return super().pop(key, *args)

    def popitem(self):
        k, v = super().popitem()
        self._expiries.pop(k, None)
        return k, v

    def clear(self):
        self._expiries.clear()
        super().clear()

def _load_app_key() -> str | None:
    """Read the TfL API key from an env var or Docker secret."""
    key = os.getenv("TFL_APP_KEY")
    if key:
        return key

    secret_path = "/run/secrets/tfl_app_key"
    try:
        with open(secret_path) as fh:
            return fh.read().strip()
    except FileNotFoundError:
        return None


APP_KEY = _load_app_key()

_SESSION = requests.Session()

CACHE   = pathlib.Path.home() / ".cache/tfl_tube_stations.json"

_STATION_CACHE = JitteredTTLCache(maxsize=1024, ttl=900, jitter=60)

_LAST_CALL = 0.0

def _rate_limited(min_interval=0.1):
    """Decorator factory to ensure a minimum interval between calls."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            global _LAST_CALL
            since_last = time.monotonic() - _LAST_CALL
            if since_last < min_interval:
                time.sleep(min_interval - since_last)
            result = func(*args, **kwargs)
            _LAST_CALL = time.monotonic()
            return result
        return wrapper
    return decorator

def _refresh_cache() -> list[dict]:
    params = {
        "modes": "tube",
        "stopType": "NaptanMetroStation",
        "useStopPointHierarchy": "false",
        "app_key": APP_KEY,
    }

    url     = "https://api.tfl.gov.uk/StopPoint/Mode/tube/"

    data = _SESSION.get(url, params=params, timeout=60).json()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, indent=2))
    return data

def _load_stations(force_update: bool = False) -> list[dict]:

    if os.path.exists('data/stations_naptan.json'):
        return json.load(open('data/stations_naptan.json', 'r'))

    if force_update or not CACHE.exists():
        return _refresh_cache()
    return json.loads(CACHE.read_text())['stopPoints']

def _station_records(obj):
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except Exception:
            return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if "stopPoints" in obj and isinstance(obj["stopPoints"], list):
            return obj["stopPoints"]
        return list(obj.values())
    return []

_STATIONS = _station_records(_load_stations())

def list_station_names() -> list[str]:
    """Alphabetical ‘Oxford Circus’, ‘Ealing Broadway’, …"""
    return sorted(sp["commonName"] for sp in _STATIONS)

def best_station_match(user_text: str, *, min_score: int = 80) -> tuple[str, str] | None:
    """
    Return (name, naptanId) for the closest match, or None if below threshold.
    tweak `processor` / `scorer` in `process.extractOne` for different heuristics.
    """

    names = {sp["commonName"]: sp["naptanId"] for sp in _STATIONS}
    matches = process.extract(user_text, names.keys(), scorer=fuzz.WRatio, limit = 10)
    for match in matches:
        if match and (match[1] >= min_score) and names[match[0]].startswith("940G"):
            return match[0], names[match[0]]
    return None

@cache
def _naptan_for_station(name: str) -> str:
    """
    Resolve a human-readable Underground station name to its NaPTAN code
    using /StopPoint/Search.  Raises ValueError if no Tube station is found.
    """
    url = f"https://api.tfl.gov.uk/StopPoint/Search/{name}"
    params = {"modes": "tube", "app_key": APP_KEY}

    try:
        r = _SESSION.get(url, params=params, timeout=30)
        r.raise_for_status()
    except Exception as e:
        raise ValueError(f"Connection failed: {e}")

    for match in r.json().get("matches", []):
        nid = match["id"]
        # Tube stations always start 940G…  (Bakerloo = 940GZZLU… etc.)
        if nid.startswith("940G"):
            return nid

    raise ValueError(f"No Tube station called “{name}” was found")

@cached(_STATION_CACHE)
@_rate_limited(min_interval=0.1)
def _live_crowding(naptan: str) -> dict:
    """
    Return the latest crowd-level payload for a London Underground station.
    Example field:  {'percentageOfBaseline': 0.31, 'timeUtc': '2025-07-14T09:30:00Z', …}
    """

    url = f"https://api.tfl.gov.uk/crowding/{naptan}/Live"
    params = {"app_key": APP_KEY}

    try:
        r = _SESSION.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return data
        raise ValueError("Unexpected response format")
    except requests.RequestException as e:
        logger.error("Request for %s failed: %s", naptan, e)
    except ValueError as e:
        logger.error("Invalid response for %s: %s", naptan, e)
    return {"dataAvailable": False, "percentageOfBaseline": 1.0}


def live_crowding(dodgy_station_name: str) -> float:
    try:
        station = best_station_match(dodgy_station_name)
        if not station:
            logger.error("No station match for %s", dodgy_station_name)
            return 1.0
        response = _live_crowding(station[1])
        if response.get("dataAvailable"):
            return response.get("percentageOfBaseline", 1.0)
    except Exception as e:
        logger.error("Error retrieving crowding for %s: %s", dodgy_station_name, e)
    return 1.0

if __name__ == "__main__":

    # print(_live_crowding(best_station_match("Holborn")[0]))
    # print(_live_crowding(best_station_match("King's Cross")[0]))
    # print(_live_crowding(best_station_match("South Kensington")[0]))

    # lines = json.load(open('data/london_underground_lines.json', 'r'))
    # picc = lines['Piccadilly']

    # stations_plain = set()
    # for l in picc:
    #     stations_plain.update(l)

    # stations_naptan = {}
    # for station in stations_plain:
    #     stations_naptan[station] = _naptan_for_station(station)

    names = {sp["commonName"]: sp["naptanId"] for sp in _STATIONS}

    print(names)

    json.dump(_STATIONS, open('data/stations_naptan.json', 'w'))
