from abc import ABC, abstractmethod
from schemas import TravelBrief
from searcher import execute_parallel_search, select_best_options
from itinerary import assemble_itinerary

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
        
        try:
            # 1. Execute parallel search for flights and hotels
            flights, hotels = execute_parallel_search(brief)
            
            # 2. Select the best flight and hotel based on constraints (programmatic + agentic LLM)
            flight, hotel = select_best_options(brief, flights, hotels)
            
            # 3. Stitch selected elements into a chronological itinerary
            itinerary = assemble_itinerary(brief, flight, hotel)
            
            print("\n" + "=" * 60)
            print("               FINAL CHRONOLOGICAL ITINERARY")
            print("=" * 60)
            print(f"  Flight: {flight.airline} ({flight.flight_id}) - {flight.origin} to {flight.destination}")
            print(f"  Hotel:  {hotel.name} ({hotel.location}) - Rating: {hotel.rating} stars")
            print(f"  Total Cost: {itinerary.total_cost:,} INR (Flight: {flight.price:,} + Hotel: {hotel.price_per_night * brief.duration_days:,} INR)")
            print("-" * 60)
            print("  Timeline:")
            for idx, event in enumerate(itinerary.timeline, 1):
                clean_time = event.timestamp.replace("T", " ")
                print(f"  {idx:02d}. [{event.event_type}] @ {clean_time}")
                print(f"      Location: {event.location}")
                print(f"      Details:  {event.description}")
            print("=" * 60)
            
            print("\nFinalItinerary Model (Structured JSON):")
            print(itinerary.model_dump_json(indent=2))
            
        except Exception as e:
            print(f"\n[ERROR] Search initialization or itinerary assembly failed: {e}")

class TravelRouter:
    @staticmethod
    def route(brief: TravelBrief) -> RoutingStrategy:
        """Deterministic programmatic router using the Strategy/Factory pattern."""
        if not brief.is_complete:
            return ClarificationStrategy()
        else:
            return SearchInitializationStrategy()

