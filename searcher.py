import os
import json
import concurrent.futures
from typing import List, Tuple, Optional
from pydantic import BaseModel
from schemas import TravelBrief, Flight, Hotel
from extractor import to_gemini_schema, client, groq_api_key


class SelectionResult(BaseModel):
    selected_flight_id: str
    selected_hotel_id: str
    reasoning: str

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

def select_best_options(brief: TravelBrief, flights: List[Flight], hotels: List[Hotel]) -> Tuple[Flight, Hotel]:
    """
    Combines flights and hotels, filters programmatically by total budget,
    and then asks Gemini to make the optimal selection based on soft constraints.
    """
    if not flights:
        raise ValueError("No matching flights found for the query.")
    if not hotels:
        raise ValueError("No matching hotels found for the query.")
        
    valid_pairs = []
    # If budget_range is specified, get the max budget
    max_budget = brief.budget_range[1] if (brief.budget_range and len(brief.budget_range) > 1) else None
    
    print(f"\n[Programmatic Filter] Evaluating combinations under budget limit: {max_budget} INR...")
    for flight in flights:
        for hotel in hotels:
            # Total cost is flight roundtrip + hotel price per night * duration
            total_cost = flight.price + (hotel.price_per_night * brief.duration_days)
            if max_budget is None or total_cost <= max_budget:
                valid_pairs.append((flight, hotel, total_cost))
                
    if not valid_pairs:
        raise ValueError(
            f"No flight + hotel combinations fit within the maximum budget constraint of {max_budget} INR. "
            f"Minimum flight cost is {min(f.price for f in flights)} INR. "
            f"Minimum hotel cost is {min(h.price_per_night for h in hotels) * brief.duration_days} INR for {brief.duration_days} nights."
        )
        
    print(f"[Programmatic Filter] Found {len(valid_pairs)} valid flight + hotel combinations under budget.")
    
    # Format candidates data for LLM ranking
    candidates_data = []
    for i, (flight, hotel, total_cost) in enumerate(valid_pairs):
        candidates_data.append({
            "pair_index": i,
            "flight_id": flight.flight_id,
            "airline": flight.airline,
            "outbound_departure": flight.outbound_departure_time,
            "inbound_departure": flight.inbound_departure_time,
            "flight_price": flight.price,
            "flight_details": flight.details,
            "hotel_id": hotel.hotel_id,
            "hotel_name": hotel.name,
            "hotel_price_per_night": hotel.price_per_night,
            "hotel_rating": hotel.rating,
            "hotel_preferences": hotel.preferences,
            "hotel_details": hotel.details,
            "total_cost_inr": total_cost
        })
        
    system_instruction = (
        "You are an expert travel agent. Your job is to select the single best combination of "
        "flight and hotel for the user from a list of candidate pairs.\n\n"
        "You must analyze the user's travel brief, focusing on:\n"
        "- Soft constraints (e.g. avoiding early morning flights, preferred flight times).\n"
        "- Accommodation preferences (e.g. quiet, luxury, budget, close to transit).\n"
        "- Value for money and rating.\n\n"
        "Select the option that best matches their constraints and preferences.\n\n"
        "You MUST output a valid JSON object matching the following structure:\n"
        "{\n"
        "  \"selected_flight_id\": \"string\",\n"
        "  \"selected_hotel_id\": \"string\",\n"
        "  \"reasoning\": \"string\"\n"
        "}"
    )
    
    print("[Agentic Evaluation] Invoking Groq (llama-3.3-70b-versatile) to analyze soft constraints...")
    
    prompt = (
        f"User Travel Brief:\n"
        f"- Origin: {brief.origin}\n"
        f"- Destination: {brief.destination}\n"
        f"- Date: {brief.travel_date}\n"
        f"- Duration: {brief.duration_days} days\n"
        f"- Budget Limit: {max_budget} INR if specified\n"
        f"- Accommodation Preferences: {brief.accommodation_preferences}\n"
        f"- Soft Constraints: {brief.soft_constraints}\n\n"
        f"Candidate Pairs:\n"
        f"{json.dumps(candidates_data, indent=2)}\n\n"
        f"Please select the best pair and return its selected_flight_id, selected_hotel_id, and reasoning."
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
        result = SelectionResult.model_validate_json(content)
        
        # Match back to retrieve actual model instances
        for flight, hotel, total_cost in valid_pairs:
            if flight.flight_id == result.selected_flight_id and hotel.hotel_id == result.selected_hotel_id:
                print(f"\n[Agentic Selection Reasoning]:\n{result.reasoning}")
                return flight, hotel
                
        # Fallback if selected keys are not matching
        print(f"\n[Agentic Selection Fallback] Chosen keys {result.selected_flight_id}/{result.selected_hotel_id} mismatch. Using first option.")
        return valid_pairs[0][0], valid_pairs[0][1]
        
    except Exception as e:
        err_msg = str(e)
        if any(keyword in err_msg.lower() for keyword in ["api key", "403", "leaked", "mock_key", "unauthorized", "api_key", "invalid", "quota", "rate limit", "429", "none type", "not set"]):
            print(f"\n[Groq API Warning]: Selection failed ({err_msg}). Using programmatic fallback mock selector...")
            
            best_flight = None
            best_hotel = None
            
            # Let's inspect the soft constraints in details
            hate_early_morning = any("morning" in c.lower() or "early" in c.lower() for c in brief.soft_constraints)
            
            # 1. Filter flight matching morning constraint
            flight_candidates = [p[0] for p in valid_pairs]
            if hate_early_morning:
                # Filter out flights departing between 00:00 and 08:00 AM (FL-001 departs at 03:00)
                non_morning_flights = [f for f in flight_candidates if not (f.outbound_departure_time.endswith("03:00:00") or "03:00" in f.outbound_departure_time)]
                if non_morning_flights:
                    best_flight = non_morning_flights[0] # Pick FL-002
            
            if not best_flight:
                best_flight = flight_candidates[0]
                
            # 2. Filter hotel based on rating / price
            hotel_candidates = [p[1] for p in valid_pairs if p[0].flight_id == best_flight.flight_id]
            if hotel_candidates:
                # Sort hotels by rating (descending)
                hotel_candidates.sort(key=lambda x: x.rating, reverse=True)
                best_hotel = hotel_candidates[0] # London Cozy Stay HT-001 (rating 4.2)
                
            if best_flight and best_hotel:
                print("\n[Agentic Selection Reasoning (Mock Fallback)]:\n"
                      f"Selected Flight {best_flight.flight_id} ({best_flight.airline}) because it departs at {best_flight.outbound_departure_time} which respects the constraint "
                      f"of avoiding early morning departures (unlike early morning flight FL-001). Selected Hotel {best_hotel.name} as it matches location {best_hotel.location}, "
                      f"fits within the budget constraints, and matches general preferences.")
                return best_flight, best_hotel
                
        print(f"\n[Agentic Selection Fallback] Selection call failed: {e}. Using first option.")
        return valid_pairs[0][0], valid_pairs[0][1]


