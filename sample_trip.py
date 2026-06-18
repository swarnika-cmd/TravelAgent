"""
A ready-made sample trip — so the web UI can be explored offline, with no
Gemini/RapidAPI keys. Hand-built to mirror real agent output exactly (same
shapes as itinerary.build), a Bangalore -> Kerala nature run.

Used by server.py's POST /api/sample. Importing this module pulls in nothing
beyond schemas, so it stays optional to the server.
"""
from datetime import datetime, timedelta

from schemas import (
    Brief, CityStop, ConversationState, Flight, Hotel, DayPlan,
    TimelineEvent, Itinerary, SimilarTraveler,
)


def _ev(time, kind, title, note="", cost=0):
    return TimelineEvent(time=time, kind=kind, title=title, note=note, cost_inr=cost)


def sample_state(sid: str) -> ConversationState:
    start = datetime(2026, 7, 12)
    brief = Brief(
        origin="Bangalore",
        destinations=[CityStop(city="Munnar", nights=2),
                      CityStop(city="Alleppey", nights=2),
                      CityStop(city="Kochi", nights=1)],
        travel_date=start.strftime("%Y-%m-%d"),
        duration_days=5,
        traveller_count=3,
        budget_mode="any",
        vibe="nature",
    )
    flight = Flight(
        flight_id="6E-643", airline="IndiGo", origin="BLR", destination="COK",
        depart_time=f"{brief.travel_date}T06:30:00",
        arrive_time=f"{brief.travel_date}T07:45:00",
        price_inr=4180, stops=0,
    )
    hotels = [
        Hotel(hotel_id="AI-MUN-H02", name="Spice Tree Munnar", city="Munnar",
              price_per_night_inr=6800, rating=9.1),
        Hotel(hotel_id="AI-ALL-H01", name="Lake Canopy Houseboat", city="Alleppey",
              price_per_night_inr=7400, rating=8.8),
        Hotel(hotel_id="AI-KOC-H03", name="Forte Kochi", city="Kochi",
              price_per_night_inr=5200, rating=8.6),
    ]

    days = [
        DayPlan(day_number=1, date=start.strftime("%Y-%m-%d"), city="Munnar", cost_inr=21540, events=[
            _ev("06:30", "FLIGHT_DEPART", "IndiGo 6E-643 BLR -> COK", "0 stops", 4180),
            _ev("07:45", "FLIGHT_ARRIVE", "Arrive at COK"),
            _ev("08:30", "TRANSIT_DEPART", "Cab COK -> Munnar", "~4.0h", 3200),
            _ev("12:30", "TRANSIT_ARRIVE", "Arrive at Munnar"),
            _ev("13:30", "HOTEL_CHECKIN", "Check in at Spice Tree Munnar", "", 6800),
            _ev("13:00", "MEAL", "Saravana Bhavan", "South Indian, ~₹250/pp", 750),
            _ev("18:00", "ACTIVITY", "Tea Museum & sunset point", "nature, ~2.0h", 600),
            _ev("18:00", "MEAL", "Rapsy Restaurant", "Kerala, ~₹350/pp", 1050),
        ]),
        DayPlan(day_number=2, date=(start + timedelta(days=1)).strftime("%Y-%m-%d"), city="Munnar", cost_inr=10180, events=[
            _ev("09:00", "ACTIVITY", "Eravikulam National Park", "nature, ~3.5h", 1500),
            _ev("09:00", "MEAL", "SN Restaurant", "veg, ~₹200/pp", 600),
            _ev("13:00", "ACTIVITY", "Kolukkumalai tea estate trek", "adventure, ~3.0h", 2400),
            _ev("13:00", "MEAL", "Eastend Eatery", "multi-cuisine, ~₹400/pp", 1200),
            _ev("18:00", "MEAL", "The Tea Sanctuary cafe", "cafe, ~₹300/pp", 900),
        ]),
        DayPlan(day_number=3, date=(start + timedelta(days=2)).strftime("%Y-%m-%d"), city="Alleppey", cost_inr=13050, events=[
            _ev("08:00", "TRANSIT_DEPART", "Cab Munnar -> Alleppey", "~4.5h", 3600),
            _ev("12:30", "TRANSIT_ARRIVE", "Arrive at Alleppey"),
            _ev("13:30", "HOTEL_CHECKIN", "Board Lake Canopy Houseboat", "", 7400),
            _ev("13:00", "MEAL", "Thaff Restaurant", "seafood, ~₹450/pp", 1350),
            _ev("18:00", "ACTIVITY", "Backwater sunset cruise", "nature, ~2.0h", 0),
            _ev("18:00", "MEAL", "Onboard Kerala thali dinner", "Kerala, ~₹300/pp", 900),
        ]),
        DayPlan(day_number=4, date=(start + timedelta(days=3)).strftime("%Y-%m-%d"), city="Alleppey", cost_inr=11290, events=[
            _ev("09:00", "ACTIVITY", "Houseboat backwater day-cruise", "nature, ~5.0h", 0),
            _ev("09:00", "MEAL", "Onboard breakfast", "Kerala, ~₹200/pp", 600),
            _ev("13:00", "MEAL", "Halais Restaurant", "biryani, ~₹350/pp", 1050),
            _ev("18:00", "ACTIVITY", "Marari Beach evening walk", "beach, ~2.0h", 0),
            _ev("18:00", "MEAL", "Chakara seafood shack", "seafood, ~₹500/pp", 1500),
        ]),
        DayPlan(day_number=5, date=(start + timedelta(days=4)).strftime("%Y-%m-%d"), city="Kochi", cost_inr=9760, events=[
            _ev("08:00", "TRANSIT_DEPART", "Cab Alleppey -> Kochi", "~1.5h", 1800),
            _ev("09:30", "TRANSIT_ARRIVE", "Arrive at Kochi"),
            _ev("10:30", "HOTEL_CHECKIN", "Check in at Forte Kochi", "", 5200),
            _ev("13:00", "ACTIVITY", "Fort Kochi & Chinese fishing nets", "heritage, ~2.5h", 300),
            _ev("13:00", "MEAL", "Kashi Art Cafe", "cafe, ~₹400/pp", 1200),
            _ev("18:00", "ACTIVITY", "Kathakali performance, Greenix", "culture, ~1.5h", 1500),
            _ev("18:00", "MEAL", "Oceanos Restaurant", "seafood, ~₹450/pp", 1350),
        ]),
    ]
    total = sum(d.cost_inr for d in days)

    similar = [
        SimilarTraveler(summary="Couple, late 20s, Mumbai; short curated getaways, comfort-focused",
                        chosen=["Goa", "Udaipur", "Andaman", "Munnar"], budget_inr=75000, similarity=0.74),
        SimilarTraveler(summary="Solo female, 31, photographer from Bangalore; avoids crowds, off-beat picks",
                        chosen=["Hampi", "Pondicherry", "Spiti", "Gokarna"], budget_inr=50000, similarity=0.69),
        SimilarTraveler(summary="Family of 4 from Delhi, heritage + nature, prefer trains",
                        chosen=["Jaipur", "Munnar", "Rishikesh", "Coorg"], budget_inr=60000, similarity=0.63),
    ]

    itinerary = Itinerary(brief=brief, flight=flight, hotels=hotels, days=days,
                          total_cost_inr=total, similar_travelers=similar)

    history = [
        {"role": "user", "content": "Bangalore to Kerala for 5 days, 3 of us, nature trip, no budget cap"},
        {"role": "assistant", "content": "Kerala it is. For a 5-day nature trip I've picked **Munnar (2n) -> Alleppey (2n) -> Kochi (1n)** — tea country, backwaters, then a day in Fort Kochi. Full plan is on the board. Tell me if a flight slips and I'll re-anchor everything."},
    ]

    return ConversationState(
        session_id=sid, history=history, brief=brief,
        visited_already=[], last_suggestions=[],
        itinerary=itinerary, llm_calls=2,
    )
