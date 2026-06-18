"""
Day-by-day itinerary assembly. Supports single and multi-city trips.

build(brief, flight, hotels) -> (days, total_cost). One hotel per CityStop in
brief.destinations. Activities/restaurants are fetched per city via llm.
Inter-city transit is inserted on the first day of each non-first segment.
"""
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from collections import defaultdict

import llm
from schemas import Brief, Flight, Hotel, Activity, Restaurant, DayPlan, TimelineEvent

SLOT_TIMES = {"morning": "09:00", "afternoon": "13:00", "evening": "18:00"}
MEAL_FOR_SLOT = {"morning": "breakfast", "afternoon": "lunch", "evening": "dinner"}


def _slot_activities(activities: List[Activity], days: int) -> dict:
    """Distribute activities across days; no activity repeats.
    Override LLM best_time when impractical: anything >4h must be morning;
    anything 2.5-4h must be morning or afternoon (never evening)."""
    by_slot = defaultdict(list)
    for a in sorted(activities, key=lambda x: -x.duration_hours):
        forced_time = a.best_time
        if a.duration_hours > 4:
            forced_time = "morning"
        elif a.duration_hours > 2.5 and a.best_time == "evening":
            forced_time = "afternoon"
        by_slot[forced_time].append(a)

    plan: dict = {d: {} for d in range(days)}
    for slot in ("morning", "afternoon", "evening"):
        for d in range(days):
            if by_slot[slot]:
                plan[d][slot] = by_slot[slot].pop(0)
            else:
                for other in ("morning", "afternoon", "evening"):
                    if by_slot[other]:
                        plan[d][slot] = by_slot[other].pop(0)
                        break
    return plan


def _pick_meal(restaurants: List[Restaurant], meal: str, day_index: int) -> Optional[Restaurant]:
    strict = [r for r in restaurants if r.meal_type == meal]
    fallback = [r for r in restaurants if r.meal_type == "all-day"]
    candidates = strict or fallback or restaurants
    return candidates[day_index % len(candidates)] if candidates else None


def _flight_events(flight: Flight, traveller_count: int) -> Tuple[List[TimelineEvent], int]:
    dep_h = flight.depart_time.split("T")[1][:5]
    arr_h = flight.arrive_time.split("T")[1][:5]
    events = [
        TimelineEvent(time=dep_h, kind="FLIGHT_DEPART",
                      title=f"{flight.airline} {flight.flight_id} {flight.origin} -> {flight.destination}",
                      note=f"{flight.stops} stops", cost_inr=flight.price_inr),
        TimelineEvent(time=arr_h, kind="FLIGHT_ARRIVE",
                      title=f"Arrive at {flight.destination}"),
    ]
    return events, flight.price_inr * traveller_count


def _transit_events(prev_city: str, to_city: str, day_start: datetime,
                    traveller_count: int) -> Tuple[List[TimelineEvent], int, datetime]:
    info = llm.generate_transit(prev_city, to_city) or {}
    mode = info.get("mode", "bus")
    duration = float(info.get("duration_hours", 6.0))
    price = int(info.get("price_inr", 800))
    depart_dt = day_start.replace(hour=8, minute=0)
    arrive_dt = depart_dt + timedelta(hours=duration)
    events = [
        TimelineEvent(time=depart_dt.strftime("%H:%M"), kind="TRANSIT_DEPART",
                      title=f"{mode.title()} {prev_city} -> {to_city}",
                      note=f"~{duration}h", cost_inr=price),
        TimelineEvent(time=arrive_dt.strftime("%H:%M"), kind="TRANSIT_ARRIVE",
                      title=f"Arrive at {to_city}"),
    ]
    return events, price * traveller_count, arrive_dt


def _build_segment(brief: Brief, city: str, nights: int, start_date: datetime,
                   day_offset: int, is_first_segment: bool,
                   flight: Optional[Flight], hotel: Optional[Hotel],
                   prev_city: Optional[str]) -> Tuple[List[DayPlan], int]:
    activities = llm.generate_activities(city)
    restaurants = llm.generate_restaurants(city)
    slotted = _slot_activities(activities, nights)
    day_plans: List[DayPlan] = []
    segment_cost = 0

    for d in range(nights):
        date = (start_date + timedelta(days=d)).strftime("%Y-%m-%d")
        events: List[TimelineEvent] = []
        day_cost = 0
        transit_arrive_dt: Optional[datetime] = None

        # Day-1 entrance: flight or ground transit from prev_city
        if d == 0 and flight:
            evs, c = _flight_events(flight, brief.traveller_count)
            events.extend(evs); day_cost += c
        elif d == 0 and prev_city:
            evs, c, transit_arrive_dt = _transit_events(
                prev_city, city, start_date, brief.traveller_count)
            events.extend(evs); day_cost += c

        # Hotel check-in (1h after the latest arrival on the day)
        if d == 0 and hotel:
            if flight:
                ci = (datetime.fromisoformat(flight.arrive_time) + timedelta(hours=1)).strftime("%H:%M")
            elif transit_arrive_dt:
                ci = (transit_arrive_dt + timedelta(hours=1)).strftime("%H:%M")
            else:
                ci = "14:00"
            events.append(TimelineEvent(
                time=ci, kind="HOTEL_CHECKIN",
                title=f"Check in at {hotel.name}", cost_inr=hotel.price_per_night_inr,
            ))

        # Hotel charged per ROOM, not per person: 1-3 people = 1 room, 4-6 = 2, etc.
        if hotel:
            rooms = max(1, (brief.traveller_count + 2) // 3)
            day_cost += hotel.price_per_night_inr * rooms

        # Activities + meals — skip slots before the traveller has arrived
        for slot, time_str in SLOT_TIMES.items():
            slot_dt = datetime.combine(start_date.date() + timedelta(days=d),
                                       datetime.strptime(time_str, "%H:%M").time())
            if transit_arrive_dt and slot_dt < transit_arrive_dt:
                continue

            act = slotted.get(d, {}).get(slot)
            if act:
                events.append(TimelineEvent(
                    time=time_str, kind="ACTIVITY", title=act.name,
                    note=f"{act.type}, ~{act.duration_hours}h",
                    cost_inr=act.price_inr * brief.traveller_count,
                ))
                day_cost += act.price_inr * brief.traveller_count

            r = _pick_meal(restaurants, MEAL_FOR_SLOT[slot], day_index=d)
            if r:
                events.append(TimelineEvent(
                    time=time_str, kind="MEAL", title=r.name,
                    note=f"{r.cuisine}, ~₹{r.price_per_person_inr}/pp",
                    cost_inr=r.price_per_person_inr * brief.traveller_count,
                ))
                day_cost += r.price_per_person_inr * brief.traveller_count

        events.sort(key=lambda e: e.time)
        day_plans.append(DayPlan(day_number=day_offset + d, date=date, city=city,
                                 events=events, cost_inr=day_cost))
        segment_cost += day_cost

    return day_plans, segment_cost


def build(brief: Brief, flight: Optional[Flight],
          hotels: List[Optional[Hotel]]) -> Tuple[List[DayPlan], int]:
    """Build day-plans across all city stops. hotels is parallel to brief.destinations."""
    all_days: List[DayPlan] = []
    total_cost = 0
    cur_date = datetime.fromisoformat(brief.travel_date)
    day_counter = 1
    prev_city: Optional[str] = None

    for i, stop in enumerate(brief.destinations):
        hotel = hotels[i] if i < len(hotels) else None
        is_first = (i == 0)
        # On the first segment, if there's no flight, fall back to ground transit FROM origin
        first_leg_prev = brief.origin if (is_first and not flight) else (prev_city if not is_first else None)
        days, cost = _build_segment(
            brief, stop.city, stop.nights, cur_date, day_counter,
            is_first_segment=is_first,
            flight=flight if is_first else None,
            hotel=hotel,
            prev_city=first_leg_prev,
        )
        all_days.extend(days)
        total_cost += cost
        cur_date += timedelta(days=stop.nights)
        day_counter += stop.nights
        prev_city = stop.city

    return all_days, total_cost
