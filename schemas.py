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
