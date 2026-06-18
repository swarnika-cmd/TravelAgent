"""
All LLM-backed reasoning. Thin wrapper around Google Gemini.

Live every call:
  extract_updates       parse chat message -> Brief field updates + intent signals
  suggest_destinations  given vibe/budget/origin -> 3 city picks

Cached to data/cache/llm/:
  generate_activities   6 real things to do in city
  generate_restaurants  4 real restaurants in city
  generate_hotels       5 city-realistic hotels with proper price tiers
  generate_transit      best mode/duration/price between two cities
"""
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

from schemas import Brief, Activity, Restaurant, DestinationSuggestion, Hotel

load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()

# Model fallback chain: try in order, fall through on overload / transient failure.
# Override with GEMINI_MODEL env var (comma-separated for multiple).
DEFAULT_MODELS = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash"]
_env_models = os.getenv("GEMINI_MODEL", "").strip()
MODEL_CHAIN = [m.strip() for m in _env_models.split(",") if m.strip()] or DEFAULT_MODELS

CACHE_DIR = Path(__file__).parent / "data" / "cache" / "llm"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not GEMINI_KEY or GEMINI_KEY.startswith("your_"):
        return None
    try:
        from google import genai
        _client = genai.Client(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"[llm] init failed: {e}")
    return _client


def _ask_json(system: str, user: str) -> Optional[Dict[str, Any]]:
    """Call Gemini with JSON-mode. Walks the model fallback chain on transient errors."""
    c = _get_client()
    if c is None:
        return None
    try:
        from google.genai import types
    except Exception as e:
        print(f"[llm] sdk missing: {e}")
        return None

    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        temperature=0.2,
    )
    last_err = None
    for model in MODEL_CHAIN:
        try:
            resp = c.models.generate_content(model=model, contents=user, config=config)
            return json.loads(resp.text)
        except Exception as e:
            last_err = e
            msg = str(e)
            # Only fall through on overload / transient codes; bail on hard errors
            if not any(s in msg for s in ("503", "UNAVAILABLE", "429", "overload", "RESOURCE_EXHAUSTED")):
                print(f"[llm] {model} failed (non-transient): {e}")
                break
            print(f"[llm] {model} overloaded, trying next model...")
    print(f"[llm] all models exhausted. last error: {last_err}")
    return None


def _cache_path(prefix: str, value: str) -> Path:
    h = hashlib.sha1(value.lower().encode()).hexdigest()[:12]
    return CACHE_DIR / f"{prefix}_{h}.json"


def _cached_json(prefix: str, value: str, system: str, user: str) -> Dict[str, Any]:
    """Disk-cache wrapper. Returns the parsed JSON dict (empty on failure)."""
    path = _cache_path(prefix, value)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data = _ask_json(system, user) or {}
    if data:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


# ----- 1. Brief extraction ----------------------------------------------------

EXTRACT_SYSTEM = """You are a travel-brief field extractor.
Given the conversation so far + the current partial brief + the user's NEW message, output a json object with any fields the user has now provided or changed. Leave fields you didn't learn out of the json entirely.

Output json shape (include only fields the user just gave/updated):
{
  "origin": "city name",
  "destinations": [{"city": "city name", "nights": integer}],
  "travel_date": "YYYY-MM-DD",
  "duration_days": integer,
  "traveller_count": integer,
  "budget_max_inr": integer,
  "budget_mode": "cap|any|cheapest",
  "vibe": "adventure|relaxation|heritage|religious|party|nature|family|honeymoon|food",
  "visited_already": ["city","city"],
  "selected_from_suggestions": "city the user picked from the previous suggestions",
  "rejected_suggestions": ["city","city"],
  "change_intent": "cancel_flight|delay_flight|change_dates|new_trip|none"
}

Rules:
- Today is {today}. Resolve relative dates ("next Friday") to YYYY-MM-DD.
- ORIGIN vs DESTINATIONS — MOST IMPORTANT, do not confuse:
    * "<X> to <Y>" / "<X> -> <Y>": X is ORIGIN, Y is DESTINATION. Always.
    * "from <X>" -> origin. "to <Y>" / "visiting <Y>" -> destination.
    * If origin is a state, map to its travel hub city:
        Punjab -> Chandigarh; Kerala -> Kochi; Rajasthan -> Jaipur; Karnataka -> Bangalore;
        Tamil Nadu -> Chennai; West Bengal -> Kolkata; Maharashtra -> Mumbai; Gujarat -> Ahmedabad;
        Uttarakhand -> Dehradun; Himachal -> Chandigarh; J&K -> Srinagar; Telangana -> Hyderabad.
    * NEVER apply state-splitting to origin.
- DESTINATION state-splitting:
    * If destination is a state (Kerala, Rajasthan, Himachal, Tamil Nadu, etc.), produce a MULTI-CITY plan covering the best cities for the vibe + duration. Distribute nights sensibly.
        Examples (5-day): Kerala+nature -> [Munnar 2, Alleppey 2, Kochi 1]; Rajasthan+heritage -> [Jaipur 2, Udaipur 2, Jodhpur 1]; Himachal+adventure -> [Manali 3, Kasol 2]; Punjab+religious -> [Amritsar 3, Anandpur Sahib 2].
        <=3 days: 1-2 cities. 4-6 days: 2-3 cities. 7+ days: 3-4 cities.
    * Specific city -> one entry, nights = duration_days.
    * Multiple specific cities -> one entry per city in order, split nights.
- Fix typos (Banglore->Bangalore, Bombay->Mumbai, Calcutta->Kolkata, Madras->Chennai).
- NUMBERS — never confuse these:
    * "N days" / "for N days" / "N-day trip" -> duration_days=N. NEVER traveller_count.
    * "N people" / "N persons" / "N of us" / "we are N" / "for N" (with no "days") / "family of N" / "couple" (=2) -> traveller_count.
    * If unsure whether a bare number refers to days or travellers, default to duration_days (people are almost always phrased as "people"/"persons"/"family of"/"couple").
- BUDGET parsing:
    * "40k" / "40,000" / "₹40000" -> budget_max_inr=40000, budget_mode="cap".
    * "1 lakh" / "1L" -> 100000, "cap".
    * "no budget" / "any budget" / "doesn't matter" -> budget_mode="any" (omit budget_max_inr).
    * "cheapest" / "as cheap as possible" / "spend less" -> budget_mode="cheapest" (omit budget_max_inr).
    * If user already chose any/cheapest in earlier turns, re-emit the same mode; do NOT re-ask.
- "I've been to Goa" -> visited_already: ["Goa"].
- "show me more" with no new info -> rejected_suggestions: <list of cities last offered>.
- If a plan exists and user says "my flight got cancelled" -> change_intent: cancel_flight.
- Output ONLY the json object."""


def extract_updates(history: List[Dict[str, str]], brief: Brief,
                    last_suggestions: List[str], user_msg: str) -> Dict[str, Any]:
    history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history[-10:])
    suggestions_text = ", ".join(last_suggestions) if last_suggestions else "(none)"
    user = (
        f"Conversation so far:\n{history_text}\n\n"
        f"Current partial brief: {brief.model_dump_json()}\n"
        f"Cities I last suggested: {suggestions_text}\n\n"
        f"NEW user message: {user_msg}"
    )
    today = datetime.now().strftime("%Y-%m-%d")
    return _ask_json(EXTRACT_SYSTEM.replace("{today}", today), user) or {}


# ----- 2. Destination suggestion ---------------------------------------------

SUGGEST_SYSTEM = """You are an Indian travel expert. Given the user's partial brief and a list of cities they DON'T want, recommend EXACTLY 3 specific Indian cities that fit.

Output ONLY a json object: {"suggestions": [{"city": str, "why": "one short sentence", "rough_cost_inr": int}]}

Rules:
- Match the vibe: adventure->Manali/Spiti/Rishikesh; religious->Varanasi/Amritsar/Tirupati; heritage->Jaipur/Udaipur/Hampi; party->Goa/Pondicherry; nature->Munnar/Ooty/Coorg; honeymoon->Udaipur/Munnar/Andaman; food->Lucknow/Hyderabad/Amritsar.
- Spread the picks for variety (not 3 hill stations).
- rough_cost_inr is the realistic total trip cost from origin (flights + hotels + activities) for the duration, NOT per-day."""


def suggest_destinations(brief: Brief, exclude: List[str]) -> List[DestinationSuggestion]:
    user = (
        f"Origin: {brief.origin}\n"
        f"Vibe: {brief.vibe or 'unspecified'}\n"
        f"Duration: {brief.duration_days or 'unspecified'} days\n"
        f"Budget cap (INR): {brief.budget_max_inr or 'unspecified'}\n"
        f"Travellers: {brief.traveller_count}\n"
        f"Travel date: {brief.travel_date or 'unspecified'}\n"
        f"Exclude these cities: {', '.join(exclude) or '(none)'}\n\n"
        f"Suggest 3 specific Indian cities."
    )
    data = _ask_json(SUGGEST_SYSTEM, user) or {}
    out: List[DestinationSuggestion] = []
    for s in (data.get("suggestions") or [])[:3]:
        try:
            out.append(DestinationSuggestion(
                city=s["city"],
                why=s.get("why", ""),
                rough_cost_inr=int(s["rough_cost_inr"]) if s.get("rough_cost_inr") else None,
            ))
        except Exception:
            continue
    return out


# ----- 3. Activities (cached) ------------------------------------------------

ACTIVITY_SYSTEM = """You are an Indian-travel expert. Return EXACTLY 6 real things to do in the given Indian city — temples, viewpoints, treks, markets, museums, day-trip spots from there, anything real travellers actually do.

If the place is small/obscure, fall back to nearby attractions within a day-trip radius. Always return 6 entries unless the place is clearly not in India.

Output ONLY a json object:
{"activities":[{"name":str,"type":"heritage|adventure|food|culture|nature|sightseeing|beach|shopping|nightlife","duration_hours":float,"price_inr":int,"best_time":"morning|afternoon|evening"}]}

Spread the 6 across morning/afternoon/evening (2 of each)."""


def generate_activities(city: str) -> List[Activity]:
    data = _cached_json("act", city, ACTIVITY_SYSTEM, f"City: {city}")
    return [Activity(city=city, **a) for a in data.get("activities", []) if "name" in a]


# ----- 4. Restaurants (cached) -----------------------------------------------

RESTAURANT_SYSTEM = """You are an Indian food expert. Return EXACTLY 4 real eating places in the given Indian city — dhabas, cafes, restaurants, sweet shops, street food spots.

If the place is small/obscure, give the kind of food it's known for and a representative local eatery name. Always return 4 entries unless the place is clearly not in India.

CRITICAL: restaurants must be IN the requested city. Do NOT use the name of another city in the restaurant name (e.g., for Alleppey do not name a restaurant "Munnar X" or "Kochi X" — the establishment must actually be in Alleppey).

Output ONLY a json object:
{"restaurants":[{"name":str,"cuisine":str,"price_per_person_inr":int,"meal_type":"breakfast|lunch|dinner|all-day"}]}

Mix across breakfast / lunch / dinner / all-day."""


def generate_restaurants(city: str) -> List[Restaurant]:
    data = _cached_json("res", city, RESTAURANT_SYSTEM, f"City: {city}")
    return [Restaurant(city=city, **r) for r in data.get("restaurants", []) if "name" in r]


# ----- 5. Hotels (cached) ----------------------------------------------------

HOTEL_SYSTEM = """You are an Indian hotel expert. Return EXACTLY 5 realistic hotels in the given Indian city with REAL CITY-APPROPRIATE PRICES.

Pricing must match the city's actual cost level:
- Tier-1 metros (Mumbai, Delhi, Bangalore, Chennai, Kolkata, Hyderabad): budget ~3500-6000, mid ~7000-12000, luxury ~18000-35000
- Tourist hotspots (Goa, Jaipur, Udaipur, Agra, Manali): budget ~2000-4000, mid ~5000-9000, luxury ~14000-25000
- Hill stations / small towns (Munnar, Pithoragarh, Alleppey, Pondicherry, Coorg, Shimla, Kasol): budget ~1200-2500, mid ~3500-6500, luxury ~9000-18000
- Religious / pilgrimage towns (Rishikesh, Varanasi, Tirupati, Anandpur Sahib): budget ~800-2000, mid ~3000-5500, luxury ~7000-14000

Use REAL hotel names you know (Taj Mahal Palace, Spice Tree Munnar, etc.) otherwise realistic-sounding names.

Output ONLY a json object:
{"hotels":[{"name":str,"price_per_night_inr":int,"rating":float (7.0-9.8)}]}

Spread across budget / mid / luxury tiers."""


def generate_hotels(city: str) -> List[Hotel]:
    data = _cached_json("hotel", city, HOTEL_SYSTEM, f"City: {city}")
    out: List[Hotel] = []
    for i, h in enumerate(data.get("hotels", [])):
        try:
            out.append(Hotel(
                hotel_id=f"AI-{city[:3].upper()}-H{i+1:02d}",
                name=h["name"], city=city,
                price_per_night_inr=int(h["price_per_night_inr"]),
                rating=float(h.get("rating", 8.0)),
            ))
        except Exception:
            continue
    return out


# ----- 6. Inter-city transit (cached) ----------------------------------------

TRANSIT_SYSTEM = """You are an Indian transport expert. Pick the most common realistic way travelers go between two Indian cities.

Rules:
- < 250 km: train or cab (3-6h typical).
- 250-600 km: train (6-12h) or flight if available.
- 600-1200 km: flight (1.5-3h including airport) unless there's a famous overnight train.
- > 1200 km (e.g. Amritsar to Munnar): ALWAYS pick mode="flight". Never recommend 30+ hour bus rides.
- duration_hours includes transfers; for flights add 3h airport time.

Output ONLY a json object: {"mode":"train|bus|flight|cab","duration_hours":float,"price_inr":int,"note":"one sentence"}"""


def generate_transit(from_city: str, to_city: str) -> Optional[Dict[str, Any]]:
    data = _cached_json("transit", f"{from_city}_to_{to_city}", TRANSIT_SYSTEM,
                        f"From {from_city} to {to_city}")
    return data or None
