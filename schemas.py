from pydantic import BaseModel, model_validator
from typing import Optional, Tuple, List

class TravelBrief(BaseModel):
    origin: Optional[str] = None
    destination: Optional[str] = None
    travel_date: Optional[str] = None
    duration_days: Optional[int] = None
    traveller_count: Optional[int] = 1
    budget_range: Optional[Tuple[int, int]] = None
    accommodation_preferences: List[str] = []
    soft_constraints: List[str] = []
    is_complete: bool = False

    @model_validator(mode='after')
    def check_completeness(self) -> 'TravelBrief':
        # Check that origin, destination, travel_date, and duration_days are present and valid
        has_origin = bool(self.origin and self.origin.strip())
        has_destination = bool(self.destination and self.destination.strip())
        has_date = bool(self.travel_date and self.travel_date.strip())
        has_duration = self.duration_days is not None and self.duration_days > 0
        
        # Determine overall completeness
        self.is_complete = bool(has_origin and has_destination and has_date and has_duration)
        return self

class Flight(BaseModel):
    flight_id: str
    airline: str
    origin: str
    destination: str
    outbound_departure_time: str
    outbound_arrival_time: str
    inbound_departure_time: str
    inbound_arrival_time: str
    price: int
    details: str

class Hotel(BaseModel):
    hotel_id: str
    name: str
    location: str
    price_per_night: int
    rating: float
    preferences: List[str]
    details: str

class ItineraryEvent(BaseModel):
    timestamp: str  # ISO-8601 string
    event_type: str  # e.g., FLIGHT_DEPARTURE, FLIGHT_ARRIVAL, HOTEL_CHECK_IN, HOTEL_CHECK_OUT
    description: str
    location: str
    details: dict

class FinalItinerary(BaseModel):
    flight: Flight
    hotel: Hotel
    total_cost: int
    timeline: List[ItineraryEvent]

