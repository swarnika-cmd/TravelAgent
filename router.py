from abc import ABC, abstractmethod
from schemas import TravelBrief
from searcher import execute_parallel_search, rank_flights_agentic, filter_hotels_by_budget, rank_hotels, search_alternative_flights
from itinerary import assemble_itinerary
from critic import validate_itinerary, simulate_disruption

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
            
            if not flights:
                raise ValueError("No matching flights found for the destination.")
            if not hotels:
                raise ValueError("No matching hotels found for the destination.")
                
            # 2. Get ranked flights based on constraints
            ranked_flights = rank_flights_agentic(brief, flights)
            
            # --- STEP 1: Select Flight ---
            print(f"\n============================================================")
            print(f"                   STEP 1: SELECT A FLIGHT")
            print(f"============================================================")
            print("Please select one of the following flight options:")
            print("-" * 60)
            for idx, (f, reasoning) in enumerate(ranked_flights, 1):
                print(f"{idx}. [{f.flight_id}] {f.airline} - Price: {f.price:,} INR")
                print(f"   Route: {f.origin} -> {f.destination}")
                print(f"   Outbound Departure: {f.outbound_departure_time.replace('T', ' ')}")
                print(f"   Inbound Departure:  {f.inbound_departure_time.replace('T', ' ')}")
                print(f"   Advisor Note: {reasoning}")
                print("-" * 60)
                
            flight_idx = 0
            try:
                choice = input(f"Choose a flight option (1-{len(ranked_flights)}) [default: 1]: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(ranked_flights):
                    flight_idx = int(choice) - 1
                else:
                    if choice != "":
                        print(f"Invalid option. Defaulting to Option 1.")
            except (EOFError, OSError):
                print("Non-interactive session detected. Defaulting to Option 1.")
                
            selected_flight = ranked_flights[flight_idx][0]
            print(f"\n--> Selected Flight: {selected_flight.airline} ({selected_flight.flight_id})")
            
            # --- STEP 2: Filter and Select Hotel ---
            max_budget = brief.budget_range[1] if (brief.budget_range and len(brief.budget_range) > 1) else None
            remaining_budget = None
            if max_budget is not None:
                remaining_budget = max_budget - selected_flight.price
                
            budget_hotels = filter_hotels_by_budget(hotels, remaining_budget, brief.duration_days)
            if not budget_hotels:
                raise ValueError(
                    f"No hotels found within the remaining budget of {remaining_budget:,} INR (Total: {max_budget:,} - Flight: {selected_flight.price:,} INR)."
                )
                
            ranked_hotels = rank_hotels(budget_hotels)
            
            print(f"\n============================================================")
            print(f"                   STEP 2: SELECT A HOTEL")
            print(f"============================================================")
            if max_budget is not None:
                print(f"Remaining Budget for Hotel: {remaining_budget:,} INR (Total Budget: {max_budget:,} - Flight: {selected_flight.price:,} INR)")
            else:
                print("Remaining Budget for Hotel: No Limit")
            print(f"Showing hotels in {brief.destination} matching your budget:")
            print("-" * 60)
            
            for idx, h in enumerate(ranked_hotels, 1):
                total_stay = h.price_per_night * brief.duration_days
                print(f"{idx}. [{h.hotel_id}] {h.name} - Price: {h.price_per_night:,} INR/night (Total: {total_stay:,} INR for {brief.duration_days} nights)")
                print(f"   Rating: {h.rating} stars | Features: {', '.join(h.preferences)}")
                print(f"   Details: {h.details}")
                print("-" * 60)
                
            hotel_idx = 0
            try:
                choice = input(f"Choose a hotel option (1-{len(ranked_hotels)}) [default: 1]: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(ranked_hotels):
                    hotel_idx = int(choice) - 1
                else:
                    if choice != "":
                        print(f"Invalid option. Defaulting to Option 1.")
            except (EOFError, OSError):
                print("Non-interactive session detected. Defaulting to Option 1.")
                
            selected_hotel = ranked_hotels[hotel_idx]
            print(f"\n--> Selected Hotel: {selected_hotel.name} ({selected_hotel.hotel_id})")
            
            # --- STEP 3: Stitch selected elements into a chronological itinerary ---
            itinerary = assemble_itinerary(brief, selected_flight, selected_hotel)
            
            # Validate itinerary using the critic scanner
            validation_errors = validate_itinerary(itinerary)
            
            print("\n" + "=" * 60)
            print("               FINAL CHRONOLOGICAL ITINERARY")
            print("=" * 60)
            print(f"  Flight: {selected_flight.airline} ({selected_flight.flight_id}) - {selected_flight.origin} to {selected_flight.destination}")
            print(f"  Hotel:  {selected_hotel.name} ({selected_hotel.location}) - Rating: {selected_hotel.rating} stars")
            print(f"  Total Cost: {itinerary.total_cost:,} INR (Flight: {selected_flight.price:,} + Hotel: {selected_hotel.price_per_night * brief.duration_days:,} INR)")
            print("-" * 60)
            print("  Timeline:")
            for idx, event in enumerate(itinerary.timeline, 1):
                clean_time = event.timestamp.replace("T", " ")
                print(f"  {idx:02d}. [{event.event_type}] @ {clean_time}")
                print(f"      Location: {event.location}")
                print(f"      Details:  {event.description}")
            print("=" * 60)
            
            if validation_errors:
                print("\n[CRITIC WARNING] Itinerary validation failed with conflicts:")
                for err in validation_errors:
                    print(f"  - {err}")
            else:
                print("\n[CRITIC SUCCESS] Itinerary successfully validated. 0 conflicts found.")
                
            print("\nFinalItinerary Model (Structured JSON):")
            print(itinerary.model_dump_json(indent=2))
            
            # --- PHASE 3: Reactive Disruption Loop ---
            simulate_choice = "n"
            try:
                simulate_choice = input("\nWould you like to simulate a flight cancellation to test Phase 3 Change Management? (y/n) [default: n]: ").strip().lower()
            except (EOFError, OSError):
                print("\nNon-interactive session detected. Skipping simulated cancellation.")
                
            if simulate_choice == "y":
                print(f"\n[PHASE 3] Simulating cancellation of Outbound Flight {selected_flight.flight_id}...")
                disruption = simulate_disruption(itinerary, selected_flight.flight_id)
                
                print("\n" + "=" * 60)
                print("               DISRUPTION BLAST RADIUS ANALYSIS")
                print("=" * 60)
                for leg in disruption["blast_radius"]:
                    print(f"  * {leg}")
                print(f"\n  Patching Instruction: \"{disruption['patch_instruction']}\"")
                print("=" * 60)
                
                # Re-search flights excluding the canceled flight
                alt_flights = search_alternative_flights(brief, selected_flight.flight_id)
                
                # Re-calculate remaining budget for flights: Total budget - hotel cost
                remaining_flight_budget = None
                if max_budget is not None:
                    hotel_cost = selected_hotel.price_per_night * brief.duration_days
                    remaining_flight_budget = max_budget - hotel_cost
                    print(f"\nRemaining Budget for Flight leg: {remaining_flight_budget:,} INR (Total: {max_budget:,} - Hotel Stay: {hotel_cost:,} INR)")
                else:
                    print("\nRemaining Budget for Flight leg: No Limit")
                    
                # Filter alternative flights by budget
                valid_alt_flights = [f for f in alt_flights if remaining_flight_budget is None or f.price <= remaining_flight_budget]
                
                if not valid_alt_flights:
                    print("\n[ERROR] No alternative flights found within the remaining budget. Cannot patch the itinerary.")
                    return
                    
                # Rank the valid alternative flights
                ranked_alts = rank_flights_agentic(brief, valid_alt_flights)
                
                print(f"\n============================================================")
                print(f"             PHASE 3: SELECT REPLACEMENT FLIGHT")
                print(f"============================================================")
                print(f"Please select an alternative flight to patch the timeline:")
                print("-" * 60)
                for idx, (f, reasoning) in enumerate(ranked_alts, 1):
                    print(f"{idx}. [{f.flight_id}] {f.airline} - Price: {f.price:,} INR (Fits budget leg)")
                    print(f"   Route: {f.origin} -> {f.destination}")
                    print(f"   Outbound Departure: {f.outbound_departure_time.replace('T', ' ')}")
                    print(f"   Inbound Departure:  {f.inbound_departure_time.replace('T', ' ')}")
                    print(f"   Advisor Note: {reasoning}")
                    print("-" * 60)
                    
                alt_idx = 0
                try:
                    choice = input(f"Choose a replacement flight option (1-{len(ranked_alts)}) [default: 1]: ").strip()
                    if choice.isdigit() and 1 <= int(choice) <= len(ranked_alts):
                        alt_idx = int(choice) - 1
                    else:
                        if choice != "":
                            print(f"Invalid option. Defaulting to Option 1.")
                except (EOFError, OSError):
                    print("Non-interactive session detected. Defaulting to Option 1.")
                    
                patched_flight = ranked_alts[alt_idx][0]
                print(f"\n--> Selected Replacement Flight: {patched_flight.airline} ({patched_flight.flight_id})")
                
                # Assemble the new patched itinerary (re-anchors the hotel stay timelines)
                patched_itinerary = assemble_itinerary(brief, patched_flight, selected_hotel)
                
                # Validate the patched itinerary
                patched_errors = validate_itinerary(patched_itinerary)
                
                print("\n" + "=" * 60)
                print("            PATCHED CHRONOLOGICAL ITINERARY")
                print("=" * 60)
                print(f"  Flight (Patched): {patched_flight.airline} ({patched_flight.flight_id}) - {patched_flight.origin} to {patched_flight.destination}")
                print(f"  Hotel (Preserved): {selected_hotel.name} ({selected_hotel.location}) - Rating: {selected_hotel.rating} stars")
                print(f"  Total Cost: {patched_itinerary.total_cost:,} INR (Flight: {patched_flight.price:,} + Hotel: {selected_hotel.price_per_night * brief.duration_days:,} INR)")
                print("-" * 60)
                print("  Timeline (Re-anchored):")
                for idx, event in enumerate(patched_itinerary.timeline, 1):
                    clean_time = event.timestamp.replace("T", " ")
                    print(f"  {idx:02d}. [{event.event_type}] @ {clean_time}")
                    print(f"      Location: {event.location}")
                    print(f"      Details:  {event.description}")
                print("=" * 60)
                
                if patched_errors:
                    print("\n[CRITIC WARNING] Patched itinerary validation failed with conflicts:")
                    for err in patched_errors:
                        print(f"  - {err}")
                else:
                    print("\n[CRITIC SUCCESS] Patched itinerary successfully validated. 0 conflicts found.")
                    
                print("\nPatchedItinerary Model (Structured JSON):")
                print(patched_itinerary.model_dump_json(indent=2))
            
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
