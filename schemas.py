"""
Data models — single source of truth for shape.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal


# ----- Trip brief -------------------------------------------------------------

class CityStop(BaseModel):
    city: str
    nights: int


class Brief(BaseModel):
    origin: Optional[str] = None
    destinations: List[CityStop] = []
    travel_date: Optional[str] = None       # YYYY-MM-DD
    duration_days: Optional[int] = None
    traveller_count: int = 1
    budget_max_inr: Optional[int] = None
    budget_mode: str = "none"               # none | cap | any | cheapest
    vibe: Optional[str] = None              # adventure | relaxation | heritage | religious | party | nature | family | honeymoon | food

    @property
    def destination(self) -> Optional[str]:
        return self.destinations[0].city if self.destinations else None

    @property
    def budget_resolved(self) -> bool:
        return self.budget_mode != "none"

    @property
    def is_complete(self) -> bool:
        return bool(self.origin and self.destinations and self.travel_date
                    and self.duration_days and self.duration_days > 0)


# ----- Itinerary pieces -------------------------------------------------------

class Flight(BaseModel):
    flight_id: str
    airline: str
    origin: str
    destination: str
    depart_time: str
    arrive_time: str
    price_inr: int
    stops: int = 0


class Hotel(BaseModel):
    hotel_id: str
    name: str
    city: str
    price_per_night_inr: int
    rating: float


class Activity(BaseModel):
    name: str
    city: str
    type: str
    duration_hours: float
    price_inr: int
    best_time: Literal["morning", "afternoon", "evening"] = "afternoon"


class Restaurant(BaseModel):
    name: str
    city: str
    cuisine: str
    price_per_person_inr: int
    meal_type: Literal["breakfast", "lunch", "dinner", "all-day"] = "all-day"


class TimelineEvent(BaseModel):
    time: str            # HH:MM
    kind: str            # FLIGHT_DEPART | FLIGHT_ARRIVE | HOTEL_CHECKIN | ACTIVITY | MEAL | TRANSIT_DEPART | TRANSIT_ARRIVE
    title: str
    note: str = ""
    cost_inr: int = 0


class DayPlan(BaseModel):
    day_number: int
    date: str
    city: str
    events: List[TimelineEvent] = []
    cost_inr: int = 0


class DestinationSuggestion(BaseModel):
    city: str
    why: str
    rough_cost_inr: Optional[int] = None


class SimilarTraveler(BaseModel):
    summary: str
    chosen: List[str] = []
    budget_inr: Optional[int] = None
    similarity: float = 0.0


class Itinerary(BaseModel):
    brief: Brief
    flight: Optional[Flight] = None
    hotels: List[Hotel] = []
    days: List[DayPlan] = []
    total_cost_inr: int = 0
    similar_travelers: List[SimilarTraveler] = []


# ----- Agent reply ------------------------------------------------------------

class AgentReply(BaseModel):
    text: str
    suggestions: List[DestinationSuggestion] = []
    itinerary: Optional[Itinerary] = None
    changed_itinerary: Optional[Itinerary] = None


# ----- Conversation state -----------------------------------------------------

class ConversationState(BaseModel):
    session_id: str
    history: List[Dict[str, str]] = []
    brief: Brief = Field(default_factory=Brief)
    visited_already: List[str] = []
    last_suggestions: List[str] = []
    itinerary: Optional[Itinerary] = None
    llm_calls: int = 0
