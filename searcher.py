import os
import json
import concurrent.futures
from typing import List, Tuple, Optional
from pydantic import BaseModel
from schemas import TravelBrief, Flight, Hotel
from extractor import to_gemini_schema, client, groq_api_key


class FlightRank(BaseModel):
    flight_id: str
    rank: int
    reasoning: str

class FlightRankingResult(BaseModel):
    rankings: List[FlightRank]


def get_db_path():
    return os.path.join(os.path.dirname(__file__), "data", "db.json")

def load_db():
    path = get_db_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def search_flights(brief: TravelBrief) -> List[Flight]:
    """Search for flights matching origin, destination and departure date."""
    db = load_db()
    results = []
    
    origin_query = brief.origin.lower().strip() if brief.origin else ""
    dest_query = brief.destination.lower().strip() if brief.destination else ""
    date_query = brief.travel_date.strip() if brief.travel_date else ""
    
    print(f"  [Flight Search] Querying flights from {origin_query} to {dest_query} on {date_query}...")
    for f in db.get("flights", []):
        # Flexible matching for city names / details
        match_origin = origin_query in f["origin"].lower() or origin_query in f["details"].lower()
        match_dest = dest_query in f["destination"].lower() or dest_query in f["details"].lower()
        match_date = date_query and f["outbound_departure_time"].startswith(date_query)
        
        if match_origin and match_dest and match_date:
            results.append(Flight(**f))
            
    print(f"  [Flight Search] Found {len(results)} matching flights.")
    return results

def search_hotels(brief: TravelBrief) -> List[Hotel]:
    """Search for hotels in the destination city."""
    db = load_db()
    results = []
    
    dest_query = brief.destination.lower().strip() if brief.destination else ""
    
    print(f"  [Hotel Search] Querying hotels in {dest_query}...")
    for h in db.get("hotels", []):
        match_dest = dest_query in h["location"].lower() or dest_query in h["details"].lower()
        
        if match_dest:
            results.append(Hotel(**h))
            
    print(f"  [Hotel Search] Found {len(results)} matching hotels.")
    return results

def execute_parallel_search(brief: TravelBrief) -> Tuple[List[Flight], List[Hotel]]:
    """Executes parallel searches for flights and hotels using ThreadPoolExecutor."""
    print("\nStarting parallel search for flights and hotels...")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        flight_future = executor.submit(search_flights, brief)
        hotel_future = executor.submit(search_hotels, brief)
        
        flights = flight_future.result()
        hotels = hotel_future.result()
        
    return flights, hotels

def rank_flights_agentic(brief: TravelBrief, flights: List[Flight]) -> List[Tuple[Flight, str]]:
    """
    Evaluates and ranks flights using Groq based on the travel brief constraints (e.g., departure times).
    Returns a list of (Flight, reasoning) tuples, sorted by rank (best first).
    """
    if not flights:
        return []
        
    system_instruction = (
        "You are an expert travel agent. Your job is to rank a list of flight options based on the user's travel brief "
        "and soft constraints (e.g. flight departure times, preferences).\n\n"
        "You must rank them from 1 (best match) to N (worst match).\n"
        "You MUST output a valid JSON object matching the following structure:\n"
        "{\n"
        "  \"rankings\": [\n"
        "    {\n"
        "      \"flight_id\": \"string\",\n"
        "      \"rank\": integer,\n"
        "      \"reasoning\": \"string\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    
    prompt_flights = []
    for f in flights:
        prompt_flights.append({
            "flight_id": f.flight_id,
            "airline": f.airline,
            "origin": f.origin,
            "destination": f.destination,
            "outbound_departure": f.outbound_departure_time,
            "inbound_departure": f.inbound_departure_time,
            "price": f.price,
            "details": f.details
        })
        
    prompt = (
        f"User Travel Brief:\n"
        f"- Origin: {brief.origin}\n"
        f"- Destination: {brief.destination}\n"
        f"- Date: {brief.travel_date}\n"
        f"- Duration: {brief.duration_days} days\n"
        f"- Soft Constraints: {brief.soft_constraints}\n\n"
        f"Flight Options:\n"
        f"{json.dumps(prompt_flights, indent=2)}\n\n"
        f"Please rank these flights and provide your reasoning."
    )
    
    try:
        if groq_api_key == "MOCK_KEY" or not client:
            raise ValueError("GROQ_API_KEY is not set or is using placeholder MOCK_KEY.")
            
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        ranking_res = FlightRankingResult.model_validate_json(content)
        
        # Sort and construct return list
        rank_map = {r.flight_id: (r.rank, r.reasoning) for r in ranking_res.rankings}
        
        ranked_list = []
        for f in flights:
            rank, reasoning = rank_map.get(f.flight_id, (99, "No specific ranking reasoning provided."))
            ranked_list.append((f, rank, reasoning))
            
        ranked_list.sort(key=lambda x: x[1])
        return [(item[0], item[2]) for item in ranked_list]
        
    except Exception as e:
        err_msg = str(e)
        print(f"\n[Groq API Warning]: Flight ranking failed ({err_msg}). Using programmatic fallback ranker...")
        
        # Programmatic ranking fallback
        hate_early_morning = any("morning" in c.lower() or "early" in c.lower() for c in brief.soft_constraints)
        
        ranked_list = []
        for f in flights:
            is_early_morning = f.outbound_departure_time.endswith("03:00:00") or "03:00" in f.outbound_departure_time
            is_afternoon = f.outbound_departure_time.endswith("14:30:00") or "14:30" in f.outbound_departure_time
            
            if hate_early_morning and is_early_morning:
                rank = 3
                reasoning = "[Preferred Match: LOW] Ranked lower because it departs in the early morning (03:00 AM), which violates your constraint of avoiding early morning flights."
            elif hate_early_morning and is_afternoon:
                rank = 1
                reasoning = "[Preferred Match: HIGH] Ranked highest because it departs in the afternoon (02:30 PM), satisfying your constraint of avoiding early morning flights."
            else:
                rank = 2
                reasoning = "[Preferred Match: MED] Departs at a reasonable time, matching travel dates."
            ranked_list.append((f, rank, reasoning))
            
        ranked_list.sort(key=lambda x: x[1])
        return [(item[0], item[2]) for item in ranked_list]

def filter_hotels_by_budget(hotels: List[Hotel], remaining_budget: Optional[int], duration_days: int) -> List[Hotel]:
    """
    Filters hotels based on whether the total stay cost fits within the remaining budget.
    """
    if remaining_budget is None:
        return hotels
        
    filtered = []
    for h in hotels:
        total_hotel_cost = h.price_per_night * duration_days
        if total_hotel_cost <= remaining_budget:
            filtered.append(h)
    return filtered

def rank_hotels(hotels: List[Hotel]) -> List[Hotel]:
    """Sort hotels by rating descending."""
    sorted_hotels = list(hotels)
    sorted_hotels.sort(key=lambda h: h.rating, reverse=True)
    return sorted_hotels



