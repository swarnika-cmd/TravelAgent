from datetime import datetime, timedelta
from schemas import TravelBrief, Flight, Hotel, ItineraryEvent, FinalItinerary

def parse_iso(time_str: str) -> datetime:
    """Parse a simple ISO-8601 formatted time string."""
    return datetime.fromisoformat(time_str)

def format_iso(dt: datetime) -> str:
    """Format a datetime into a simple ISO-8601 string."""
    return dt.isoformat()

def assemble_itinerary(brief: TravelBrief, flight: Flight, hotel: Hotel) -> FinalItinerary:
    """
    Programmatically builds a list of discrete events for flights and hotel stays,
    sorts them chronologically, and calculates the total cost.
    """
    events = []
    
    # 1. Outbound Flight Departure
    events.append(ItineraryEvent(
        timestamp=flight.outbound_departure_time,
        event_type="FLIGHT_DEPARTURE",
        description=f"Outbound Flight {flight.flight_id} ({flight.airline}) departs from {flight.origin} to {flight.destination}",
        location=flight.origin,
        details={"airline": flight.airline, "flight_id": flight.flight_id, "departure": flight.outbound_departure_time}
    ))
    
    # 2. Outbound Flight Arrival
    events.append(ItineraryEvent(
        timestamp=flight.outbound_arrival_time,
        event_type="FLIGHT_ARRIVAL",
        description=f"Outbound Flight {flight.flight_id} ({flight.airline}) arrives at {flight.destination}",
        location=flight.destination,
        details={"airline": flight.airline, "flight_id": flight.flight_id, "arrival": flight.outbound_arrival_time}
    ))
    
    # 3. Hotel Check-in (1 hour after outbound flight arrival)
    arr_dt = parse_iso(flight.outbound_arrival_time)
    checkin_dt = arr_dt + timedelta(hours=1)
    events.append(ItineraryEvent(
        timestamp=format_iso(checkin_dt),
        event_type="HOTEL_CHECK_IN",
        description=f"Check-in at {hotel.name} ({hotel.location})",
        location=hotel.name,
        details={"hotel_id": hotel.hotel_id, "rating": hotel.rating, "price_per_night": hotel.price_per_night}
    ))
    
    # 4. Hotel Check-out (3 hours before inbound flight departure)
    inb_dep_dt = parse_iso(flight.inbound_departure_time)
    checkout_dt = inb_dep_dt - timedelta(hours=3)
    events.append(ItineraryEvent(
        timestamp=format_iso(checkout_dt),
        event_type="HOTEL_CHECK_OUT",
        description=f"Check-out from {hotel.name}",
        location=hotel.name,
        details={"hotel_id": hotel.hotel_id}
    ))
    
    # 5. Inbound Flight Departure
    events.append(ItineraryEvent(
        timestamp=flight.inbound_departure_time,
        event_type="FLIGHT_DEPARTURE",
        description=f"Inbound Flight {flight.flight_id} ({flight.airline}) departs from {flight.destination} to {flight.origin}",
        location=flight.destination,
        details={"airline": flight.airline, "flight_id": flight.flight_id, "departure": flight.inbound_departure_time}
    ))
    
    # 6. Inbound Flight Arrival
    events.append(ItineraryEvent(
        timestamp=flight.inbound_arrival_time,
        event_type="FLIGHT_ARRIVAL",
        description=f"Inbound Flight {flight.flight_id} ({flight.airline}) arrives at {flight.origin}",
        location=flight.origin,
        details={"airline": flight.airline, "flight_id": flight.flight_id, "arrival": flight.inbound_arrival_time}
    ))
    
    # Sort all events chronologically by timestamp
    events.sort(key=lambda x: x.timestamp)
    
    total_cost = flight.price + (hotel.price_per_night * brief.duration_days)
    
    return FinalItinerary(
        flight=flight,
        hotel=hotel,
        total_cost=total_cost,
        timeline=events
    )
