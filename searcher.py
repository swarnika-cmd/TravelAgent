"""
Live flight + hotel search via Sky-Scrapper (RapidAPI).
Mock fallback when key is missing or quota is exhausted.
Caches all live responses for 6 hours under data/cache/api/.
"""
import os
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional
import requests
from dotenv import load_dotenv

import llm
from schemas import Flight, Hotel

load_dotenv()
KEY = os.getenv("RAPIDAPI_KEY", "").strip()
HOST = os.getenv("RAPIDAPI_HOST", "sky-scrapper.p.rapidapi.com").strip()
BASE = f"https://{HOST}"
CACHE = Path(__file__).parent / "data" / "cache" / "api"
CACHE.mkdir(parents=True, exist_ok=True)
TTL_SECONDS = 6 * 3600

IATA = {
    "delhi": "DEL", "new delhi": "DEL", "mumbai": "BOM", "bombay": "BOM",
    "bangalore": "BLR", "bengaluru": "BLR", "chennai": "MAA", "madras": "MAA",
    "kolkata": "CCU", "calcutta": "CCU", "hyderabad": "HYD", "goa": "GOI",
    "jaipur": "JAI", "ahmedabad": "AMD", "pune": "PNQ", "kochi": "COK",
    "lucknow": "LKO", "varanasi": "VNS", "udaipur": "UDR", "agra": "AGR",
    "amritsar": "ATQ", "srinagar": "SXR",
}


def _iata(s: str) -> str:
    s = (s or "").strip().lower()
    if len(s) == 3 and s.isalpha():
        return s.upper()
    return IATA.get(s, s[:3].upper())


def is_live_mode() -> bool:
    return bool(KEY) and not KEY.startswith("your_")


def _cache_path(prefix: str, params: dict) -> Path:
    h = hashlib.sha1((prefix + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:12]
    return CACHE / f"{prefix}_{h}.json"


def _get(endpoint: str, params: dict) -> Optional[dict]:
    cp = _cache_path(endpoint.replace("/", "_"), params)
    if cp.exists() and time.time() - cp.stat().st_mtime < TTL_SECONDS:
        try:
            return json.loads(cp.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        r = requests.get(f"{BASE}{endpoint}",
                         headers={"x-rapidapi-key": KEY, "x-rapidapi-host": HOST},
                         params=params, timeout=12)
        if r.status_code != 200:
            return None
        d = r.json()
        cp.write_text(json.dumps(d), encoding="utf-8")
        return d
    except Exception:
        return None


# ----- Flights ----------------------------------------------------------------

_MOCK_BASE_PRICE = {
    ("DEL", "BOM"): 5500, ("BOM", "DEL"): 5500,
    ("BLR", "DEL"): 6800, ("DEL", "BLR"): 6800,
    ("BOM", "GOI"): 3500, ("GOI", "BOM"): 3500,
    ("BLR", "GOI"): 4200, ("GOI", "BLR"): 4200,
    ("DEL", "JAI"): 4200, ("DEL", "AGR"): 3800,
    ("BOM", "BLR"): 4500,
}
_MOCK_TIMES = [("06:30", "08:45"), ("10:15", "12:30"),
               ("14:00", "16:15"), ("18:45", "21:00")]
_MOCK_AIRLINES = ["IndiGo", "Air India", "Vistara", "SpiceJet"]


def _mock_flights(origin: str, destination: str, date: str) -> List[Flight]:
    o, d = _iata(origin), _iata(destination)
    base = _MOCK_BASE_PRICE.get((o, d), 6500)
    return [
        Flight(
            flight_id=f"MOCK-{o}{d}-{i+1:02d}",
            airline=_MOCK_AIRLINES[i],
            origin=o, destination=d,
            depart_time=f"{date}T{dep}:00",
            arrive_time=f"{date}T{arr}:00",
            price_inr=int(base * (0.9 + 0.15 * i)),
            stops=0,
        )
        for i, (dep, arr) in enumerate(_MOCK_TIMES)
    ]


def find_flights(origin: str, destination: str, date: str) -> List[Flight]:
    if not is_live_mode():
        return _mock_flights(origin, destination, date)

    o, d = _iata(origin), _iata(destination)
    orig_payload = _get("/api/v1/flights/searchAirport", {"query": o})
    dest_payload = _get("/api/v1/flights/searchAirport", {"query": d})

    def _first(payload, *keys):
        try:
            items = (payload or {}).get("data") or []
            if not items:
                return None
            for k in keys:
                v = items[0].get(k)
                if v:
                    return v
            return None
        except Exception:
            return None

    res = _get("/api/v2/flights/searchFlights", {
        "originSkyId": _first(orig_payload, "skyId") or o,
        "destinationSkyId": _first(dest_payload, "skyId") or d,
        "originEntityId": _first(orig_payload, "entityId") or "",
        "destinationEntityId": _first(dest_payload, "entityId") or "",
        "date": date, "adults": 1, "currency": "INR", "market": "IN", "countryCode": "IN",
    })
    itineraries = ((res or {}).get("data") or {}).get("itineraries") or []
    if not itineraries:
        return _mock_flights(origin, destination, date)

    out: List[Flight] = []
    for i, it in enumerate(itineraries[:8]):
        try:
            leg = (it.get("legs") or [])[0]
            airline = ((leg.get("carriers") or {}).get("marketing") or [{}])[0].get("name", "?")
            out.append(Flight(
                flight_id=it.get("id", f"LIVE-{i:03d}"),
                airline=airline, origin=o, destination=d,
                depart_time=leg.get("departure", f"{date}T00:00:00"),
                arrive_time=leg.get("arrival", f"{date}T00:00:00"),
                price_inr=int((it.get("price") or {}).get("raw") or 0),
                stops=leg.get("stopCount", 0),
            ))
        except Exception:
            continue
    return out or _mock_flights(origin, destination, date)


# ----- Hotels -----------------------------------------------------------------

def _mock_hotels(city: str) -> List[Hotel]:
    """When live API is unavailable, ask the LLM for city-realistic hotels."""
    hotels = llm.generate_hotels(city)
    if hotels:
        return hotels
    c = city.title()
    return [Hotel(hotel_id=f"MOCK-{c[:3].upper()}-01",
                  name=f"{c} Local Stay", city=c,
                  price_per_night_inr=3000, rating=8.0)]


def find_hotels(city: str, checkin: str, nights: int) -> List[Hotel]:
    if not is_live_mode():
        return _mock_hotels(city)
    loc = _get("/api/v1/hotels/searchDestinationOrHotel", {"query": city})
    eid = (loc or {}).get("data", [{}])[0].get("entityId") if loc and loc.get("data") else None
    if not eid:
        return _mock_hotels(city)
    checkout = (datetime.fromisoformat(checkin) + timedelta(days=nights)).strftime("%Y-%m-%d")
    res = _get("/api/v1/hotels/searchHotels", {
        "entityId": eid, "checkin": checkin, "checkout": checkout,
        "adults": 1, "rooms": 1, "currency": "INR", "market": "IN", "countryCode": "IN",
    })
    raw_hotels = ((res or {}).get("data") or {}).get("hotels") or []
    if not raw_hotels:
        return _mock_hotels(city)
    out = []
    for h in raw_hotels[:10]:
        try:
            out.append(Hotel(
                hotel_id=str(h.get("hotelId", "")),
                name=h.get("name", "?"), city=city,
                price_per_night_inr=int((h.get("price") or {}).get("rawPrice") or 0),
                rating=float((h.get("reviewsSummary") or {}).get("score") or 0),
            ))
        except Exception:
            continue
    return out or _mock_hotels(city)
