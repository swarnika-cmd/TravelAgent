import unittest
from unittest.mock import patch
from datetime import datetime

from schemas import TravelBrief, Flight, Hotel, ItineraryEvent, FinalItinerary
from critic import validate_itinerary, simulate_disruption
from searcher import rank_flights_agentic, filter_hotels_by_budget, rank_hotels

class TestTravelAgentMVP(unittest.TestCase):

    def test_travel_brief_completeness(self):
        # Incomplete brief
        brief = TravelBrief(origin="Mumbai", destination="London")
        self.assertFalse(brief.is_complete)

        # Complete brief
        brief_complete = TravelBrief(
            origin="Mumbai",
            destination="London",
            travel_date="2026-07-15",
            duration_days=6
        )
        self.assertTrue(brief_complete.is_complete)

    def test_critic_validation_success(self):
        flight = Flight(
            flight_id="FL-001",
            airline="Test Air",
            origin="Mumbai",
            destination="London",
            outbound_departure_time="2026-07-15T08:00:00",
            outbound_arrival_time="2026-07-15T14:00:00",
            inbound_departure_time="2026-07-21T18:00:00",
            inbound_arrival_time="2026-07-22T02:00:00",
            price=50000,
            details="Test Flight"
        )
        hotel = Hotel(
            hotel_id="HT-001",
            name="Test Hotel",
            location="London",
            price_per_night=5000,
            rating=4.5,
            preferences=["quiet"],
            details="Test Hotel"
        )
        timeline = [
            ItineraryEvent(
                timestamp="2026-07-15T08:00:00",
                event_type="FLIGHT_DEPARTURE",
                description="Depart",
                location="Mumbai",
                details={}
            ),
            ItineraryEvent(
                timestamp="2026-07-15T14:00:00",
                event_type="FLIGHT_ARRIVAL",
                description="Arrive",
                location="London",
                details={}
            ),
            ItineraryEvent(
                timestamp="2026-07-15T15:00:00",
                event_type="HOTEL_CHECK_IN",
                description="Check-in",
                location="Test Hotel",
                details={}
            ),
            ItineraryEvent(
                timestamp="2026-07-21T12:00:00",
                event_type="HOTEL_CHECK_OUT",
                description="Check-out",
                location="Test Hotel",
                details={}
            ),
            ItineraryEvent(
                timestamp="2026-07-21T18:00:00",
                event_type="FLIGHT_DEPARTURE",
                description="Depart back",
                location="London",
                details={}
            ),
            ItineraryEvent(
                timestamp="2026-07-22T02:00:00",
                event_type="FLIGHT_ARRIVAL",
                description="Arrive home",
                location="Mumbai",
                details={}
            )
        ]
        itinerary = FinalItinerary(
            flight=flight,
            hotel=hotel,
            total_cost=80000,
            timeline=timeline
        )
        errors = validate_itinerary(itinerary)
        self.assertEqual(len(errors), 0)

    def test_critic_validation_location_conflict(self):
        # Hotel location (Paris) does not match Flight destination (London)
        flight = Flight(
            flight_id="FL-001",
            airline="Test Air",
            origin="Mumbai",
            destination="London",
            outbound_departure_time="2026-07-15T08:00:00",
            outbound_arrival_time="2026-07-15T14:00:00",
            inbound_departure_time="2026-07-21T18:00:00",
            inbound_arrival_time="2026-07-22T02:00:00",
            price=50000,
            details="Test Flight"
        )
        hotel = Hotel(
            hotel_id="HT-001",
            name="Test Hotel",
            location="Paris",
            price_per_night=5000,
            rating=4.5,
            preferences=["quiet"],
            details="Test Hotel"
        )
        timeline = [] # Empty for location test
        itinerary = FinalItinerary(
            flight=flight,
            hotel=hotel,
            total_cost=80000,
            timeline=timeline
        )
        errors = validate_itinerary(itinerary)
        self.assertTrue(any("Location Conflict" in e for e in errors))

    def test_critic_validation_chronology_conflict(self):
        flight = Flight(
            flight_id="FL-001",
            airline="Test Air",
            origin="Mumbai",
            destination="London",
            outbound_departure_time="2026-07-15T08:00:00",
            outbound_arrival_time="2026-07-15T14:00:00",
            inbound_departure_time="2026-07-21T18:00:00",
            inbound_arrival_time="2026-07-22T02:00:00",
            price=50000,
            details="Test Flight"
        )
        hotel = Hotel(
            hotel_id="HT-001",
            name="Test Hotel",
            location="London",
            price_per_night=5000,
            rating=4.5,
            preferences=["quiet"],
            details="Test Hotel"
        )
        timeline = [
            ItineraryEvent(
                timestamp="2026-07-15T14:00:00",
                event_type="FLIGHT_ARRIVAL",
                description="Arrive",
                location="London",
                details={}
            ),
            ItineraryEvent(
                timestamp="2026-07-15T08:00:00", # Chronology error: arrives before it departs in timeline order
                event_type="FLIGHT_DEPARTURE",
                description="Depart",
                location="Mumbai",
                details={}
            )
        ]
        itinerary = FinalItinerary(
            flight=flight,
            hotel=hotel,
            total_cost=80000,
            timeline=timeline
        )
        errors = validate_itinerary(itinerary)
        self.assertTrue(any("Chronological Conflict" in e for e in errors))

    def test_critic_validation_checkin_checkout_conflicts(self):
        flight = Flight(
            flight_id="FL-001",
            airline="Test Air",
            origin="Mumbai",
            destination="London",
            outbound_departure_time="2026-07-15T08:00:00",
            outbound_arrival_time="2026-07-15T14:00:00",
            inbound_departure_time="2026-07-21T18:00:00",
            inbound_arrival_time="2026-07-22T02:00:00",
            price=50000,
            details="Test Flight"
        )
        hotel = Hotel(
            hotel_id="HT-001",
            name="Test Hotel",
            location="London",
            price_per_night=5000,
            rating=4.5,
            preferences=["quiet"],
            details="Test Hotel"
        )
        
        # Scheduling Conflict: Check-in before flight arrival
        timeline_checkin_early = [
            ItineraryEvent(
                timestamp="2026-07-15T13:00:00",
                event_type="HOTEL_CHECK_IN",
                description="Check-in early",
                location="London",
                details={}
            ),
            ItineraryEvent(
                timestamp="2026-07-15T14:00:00",
                event_type="FLIGHT_ARRIVAL",
                description="Arrive",
                location="London",
                details={}
            )
        ]
        itinerary = FinalItinerary(
            flight=flight,
            hotel=hotel,
            total_cost=80000,
            timeline=timeline_checkin_early
        )
        errors = validate_itinerary(itinerary)
        self.assertTrue(any("Scheduling Conflict: Hotel check-in occurs before" in e for e in errors))

        # Scheduling Conflict: Check-out after flight departs
        timeline_checkout_late = [
            ItineraryEvent(
                timestamp="2026-07-21T18:00:00",
                event_type="FLIGHT_DEPARTURE",
                description="Depart back",
                location="London",
                details={}
            ),
            ItineraryEvent(
                timestamp="2026-07-21T19:00:00",
                event_type="HOTEL_CHECK_OUT",
                description="Check-out late",
                location="London",
                details={}
            )
        ]
        itinerary_late = FinalItinerary(
            flight=flight,
            hotel=hotel,
            total_cost=80000,
            timeline=timeline_checkout_late
        )
        errors_late = validate_itinerary(itinerary_late)
        self.assertTrue(any("Scheduling Conflict: Hotel check-out occurs after" in e for e in errors_late))

    def test_critic_disruption_simulation(self):
        flight = Flight(
            flight_id="FL-001",
            airline="Test Air",
            origin="Mumbai",
            destination="London",
            outbound_departure_time="2026-07-15T08:00:00",
            outbound_arrival_time="2026-07-15T14:00:00",
            inbound_departure_time="2026-07-21T18:00:00",
            inbound_arrival_time="2026-07-22T02:00:00",
            price=50000,
            details="Test Flight"
        )
        hotel = Hotel(
            hotel_id="HT-001",
            name="Test Hotel",
            location="London",
            price_per_night=5000,
            rating=4.5,
            preferences=["quiet"],
            details="Test Hotel"
        )
        itinerary = FinalItinerary(
            flight=flight,
            hotel=hotel,
            total_cost=80000,
            timeline=[]
        )
        
        disruption = simulate_disruption(itinerary, "FL-001")
        self.assertEqual(disruption["canceled_flight_id"], "FL-001")
        self.assertTrue(any("Test Air FL-001) has been canceled." in r for r in disruption["blast_radius"]))
        self.assertIn("excluding flight FL-001.", disruption["patch_instruction"])

        with self.assertRaises(ValueError):
            simulate_disruption(itinerary, "NON_EXISTENT_FLIGHT")

    def test_searcher_budget_filtering_and_ranking(self):
        hotels = [
            Hotel(hotel_id="HT-1", name="Hotel A", location="London", price_per_night=10000, rating=4.5, preferences=[], details=""),
            Hotel(hotel_id="HT-2", name="Hotel B", location="London", price_per_night=5000, rating=4.0, preferences=[], details=""),
            Hotel(hotel_id="HT-3", name="Hotel C", location="London", price_per_night=15000, rating=4.8, preferences=[], details="")
        ]
        
        # 6 nights. Remaining budget = 40,000 INR
        # Total cost: HT-1: 60k (Exceeds), HT-2: 30k (Fits), HT-3: 90k (Exceeds)
        filtered = filter_hotels_by_budget(hotels, remaining_budget=40000, duration_days=6)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].hotel_id, "HT-2")

        # Sorting hotels by rating descending
        ranked = rank_hotels(hotels)
        self.assertEqual(ranked[0].hotel_id, "HT-3") # 4.8 rating
        self.assertEqual(ranked[1].hotel_id, "HT-1") # 4.5 rating
        self.assertEqual(ranked[2].hotel_id, "HT-2") # 4.0 rating

if __name__ == '__main__':
    unittest.main()
