from datetime import datetime
from typing import List, Tuple
from schemas import FinalItinerary

def parse_iso(time_str: str) -> datetime:
    """Parse ISO datetime string."""
    return datetime.fromisoformat(time_str)

# Airport to City mapping for location validation matching
AIRPORT_TO_CITY = {
    "lhr": "london",
    "lgw": "london",
    "lcy": "london",
    "jfk": "new york",
    "lga": "new york",
    "ewr": "new york",
    "bom": "mumbai",
    "del": "delhi",
    "blr": "bangalore",
    "dxb": "dubai",
    "sin": "singapore",
    "cdg": "paris",
    "ory": "paris"
}

def resolve_location(loc: str) -> str:
    """Standardizes locations to city names (e.g. airport codes like LHR to London)."""
    val = loc.strip().lower()
    return AIRPORT_TO_CITY.get(val, val)

def validate_itinerary(itinerary: FinalItinerary) -> List[str]:
    """
    Scans the chronological timeline for time, space, and budget conflicts.
    Returns a list of error messages (empty if itinerary is valid).
    """
    errors = []
    
    # 1. Location / Space Validation
    flight_dest = resolve_location(itinerary.flight.destination)
    hotel_loc = resolve_location(itinerary.hotel.location)
    
    if flight_dest != hotel_loc:
        errors.append(
            f"Location Conflict: Flight destination is '{itinerary.flight.destination}', "
            f"but hotel is located in '{itinerary.hotel.location}'."
        )
        
    # 2. Time Validation (Chronological consistency of events)
    timeline = itinerary.timeline
    for i in range(len(timeline) - 1):
        t1 = parse_iso(timeline[i].timestamp)
        t2 = parse_iso(timeline[i+1].timestamp)
        if t1 > t2:
            errors.append(
                f"Chronological Conflict: Event '{timeline[i].event_type}' @ {timeline[i].timestamp} "
                f"occurs after event '{timeline[i+1].event_type}' @ {timeline[i+1].timestamp}."
            )
            
    # Find specific key events
    outbound_arrival = next((e for e in timeline if e.event_type == "FLIGHT_ARRIVAL" and resolve_location(e.location) == hotel_loc), None)
    hotel_checkin = next((e for e in timeline if e.event_type == "HOTEL_CHECK_IN"), None)
    hotel_checkout = next((e for e in timeline if e.event_type == "HOTEL_CHECK_OUT"), None)
    inbound_departure = next((e for e in timeline if e.event_type == "FLIGHT_DEPARTURE" and resolve_location(e.location) == hotel_loc), None)
    
    if outbound_arrival and hotel_checkin:
        arr_time = parse_iso(outbound_arrival.timestamp)
        checkin_time = parse_iso(hotel_checkin.timestamp)
        if arr_time > checkin_time:
            errors.append("Scheduling Conflict: Hotel check-in occurs before the outbound flight arrives.")
            
    if hotel_checkout and inbound_departure:
        checkout_time = parse_iso(hotel_checkout.timestamp)
        dep_time = parse_iso(inbound_departure.timestamp)
        if checkout_time > dep_time:
            errors.append("Scheduling Conflict: Hotel check-out occurs after the return flight departs.")
            
    return errors

def simulate_disruption(itinerary: FinalItinerary, canceled_flight_id: str) -> dict:
    """
    Simulates a flight cancellation and programmatically calculates the blast radius
    and the patching instructions for only the broken leg.
    """
    if itinerary.flight.flight_id != canceled_flight_id:
        raise ValueError(f"Flight '{canceled_flight_id}' is not part of this itinerary.")
        
    blast_radius = [
        f"Outbound Flight Leg ({itinerary.flight.airline} {itinerary.flight.flight_id}) has been canceled.",
        f"Inbound Flight Leg ({itinerary.flight.airline} {itinerary.flight.flight_id}) has been canceled.",
        f"Hotel stay at {itinerary.hotel.name} is PRESERVED, but check-in/out times must be re-anchored to the new flight times."
    ]
    
    # Calculate flight details and prompt
    patch_instruction = (
        f"Search alternative flights from {itinerary.flight.origin} to {itinerary.flight.destination} "
        f"departing on {itinerary.flight.outbound_departure_time[:10]} and returning on {itinerary.flight.inbound_departure_time[:10]}, "
        f"excluding flight {canceled_flight_id}."
    )
    
    return {
        "blast_radius": blast_radius,
        "patch_instruction": patch_instruction,
        "canceled_flight_id": canceled_flight_id
    }
