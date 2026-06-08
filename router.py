from abc import ABC, abstractmethod
from schemas import TravelBrief

class RoutingStrategy(ABC):
    @abstractmethod
    def execute(self, brief: TravelBrief) -> None:
        """Execute the logic associated with the routing decision."""
        pass

class ClarificationStrategy(RoutingStrategy):
    def execute(self, brief: TravelBrief) -> None:
        """Route to clarification if critical fields are missing."""
        missing_fields = []
        if not brief.origin or not brief.origin.strip():
            missing_fields.append("origin (departure location)")
        if not brief.destination or not brief.destination.strip():
            missing_fields.append("destination")
        if not brief.travel_date or not brief.travel_date.strip():
            missing_fields.append("travel date")
        if brief.duration_days is None or brief.duration_days <= 0:
            missing_fields.append("duration of stay (in days)")
            
        print("\n--- [ClarificationStrategy] ---")
        print("Routing Decision: CLARIFICATION REQUIRED")
        print("Reason: Travel Brief is missing critical parameters required for search handoff.")
        print(f"Missing fields: {', '.join(missing_fields)}")
        print("Action: Prompt the user for the missing details.")

class SearchInitializationStrategy(RoutingStrategy):
    def execute(self, brief: TravelBrief) -> None:
        """Route to parallel search initialization if all critical fields exist."""
        print("\n--- [SearchInitializationStrategy] ---")
        print("Routing Decision: SEARCH INITIALIZATION")
        print("Reason: Travel Brief is complete. Handing off parameters to parallel flight and hotel search engines.")
        print("Parameter Handoff Data:")
        print(f"  - Origin: {brief.origin}")
        print(f"  - Destination: {brief.destination}")
        print(f"  - Dates/Departure: {brief.travel_date}")
        print(f"  - Duration: {brief.duration_days} days")
        print(f"  - Travellers: {brief.traveller_count}")
        if brief.budget_range:
            print(f"  - Budget Range: Min={brief.budget_range[0]}, Max={brief.budget_range[1]}")
        else:
            print("  - Budget Range: Not specified")
        if brief.accommodation_preferences:
            print(f"  - Accommodation Preferences: {', '.join(brief.accommodation_preferences)}")
        else:
            print("  - Accommodation Preferences: None specified")
        if brief.soft_constraints:
            print(f"  - Soft Constraints / Requirements:")
            for constraint in brief.soft_constraints:
                print(f"    * \"{constraint}\"")
        else:
            print("  - Soft Constraints / Requirements: None specified")

class TravelRouter:
    @staticmethod
    def route(brief: TravelBrief) -> RoutingStrategy:
        """Deterministic programmatic router using the Strategy/Factory pattern."""
        if not brief.is_complete:
            return ClarificationStrategy()
        else:
            return SearchInitializationStrategy()
