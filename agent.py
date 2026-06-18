"""
Conversation orchestrator. ONE function: respond(state, user_msg) -> (state, AgentReply).

Flow:
  1. Extract field updates from the user's message via LLM.
  2. If a plan already exists and change_intent != none, handle the change.
  3. Otherwise apply updates and ask for the next missing field.
  4. When destination is missing but vibe is set, suggest 3 cities.
  5. Once everything is filled, build the itinerary and validate it.
"""
import re
from copy import deepcopy
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import llm
import searcher
import personalization
import itinerary as itin
import critic
import storage
from schemas import (
    Brief, ConversationState, AgentReply, DestinationSuggestion,
    Itinerary, Flight, Hotel, CityStop,
)

VIBE_PROMPT = (
    "What kind of trip are you in the mood for? Some options: "
    "adventure, relaxation, heritage, religious, party, nature, family, honeymoon, food. "
    "Or, if you have a city in mind already, just tell me."
)


# ----- Helpers ----------------------------------------------------------------

def _ask(state: ConversationState, text: str) -> AgentReply:
    state.history.append({"role": "assistant", "content": text})
    return AgentReply(text=text)


def _format_suggestions(suggestions: List[DestinationSuggestion]) -> str:
    return "\n\n".join(
        f"**{i}. {s.city}**"
        + (f" (~₹{s.rough_cost_inr:,})" if s.rough_cost_inr else "")
        + f" — {s.why}"
        for i, s in enumerate(suggestions, 1)
    )


def _rebalance_nights(brief: Brief) -> None:
    """If sum of stop nights doesn't match duration_days, rescale proportionally."""
    if not brief.destinations or not brief.duration_days:
        return
    total = sum(s.nights for s in brief.destinations)
    if total == brief.duration_days or total <= 0:
        return
    ratio = brief.duration_days / total
    new_nights = [max(1, round(s.nights * ratio)) for s in brief.destinations]
    new_nights[-1] = max(1, new_nights[-1] + brief.duration_days - sum(new_nights))
    for s, n in zip(brief.destinations, new_nights):
        s.nights = n


def _apply_updates(state: ConversationState, updates: dict) -> None:
    b = state.brief
    for f in ("origin", "travel_date", "vibe"):
        v = updates.get(f)
        if v:
            setattr(b, f, str(v).strip())

    for f in ("duration_days", "traveller_count"):
        if updates.get(f) is not None:
            try: setattr(b, f, int(updates[f]))
            except Exception: pass

    if updates.get("budget_max_inr") is not None:
        try:
            b.budget_max_inr = int(updates["budget_max_inr"])
            b.budget_mode = "cap"
        except Exception: pass
    bm = updates.get("budget_mode")
    if bm in ("cap", "any", "cheapest"):
        b.budget_mode = bm
        if bm in ("any", "cheapest"):
            b.budget_max_inr = None

    raw_dests = updates.get("destinations") or []
    new_stops: List[CityStop] = []
    for entry in raw_dests:
        try:
            if isinstance(entry, dict):
                city = str(entry.get("city", "")).strip()
                nights = int(entry.get("nights") or 0)
            elif isinstance(entry, str):
                city, nights = entry.strip(), 0
            else:
                continue
            if city:
                new_stops.append(CityStop(city=city, nights=max(1, nights)))
        except Exception:
            continue
    if new_stops:
        b.destinations = new_stops

    sel = updates.get("selected_from_suggestions")
    if sel and not b.destinations:
        b.destinations = [CityStop(city=sel.strip(), nights=b.duration_days or 3)]

    for c in updates.get("visited_already") or []:
        c = c.strip()
        if c and c not in state.visited_already:
            state.visited_already.append(c)
    for c in updates.get("rejected_suggestions") or []:
        if c not in state.visited_already:
            state.visited_already.append(c)

    _rebalance_nights(b)


# ----- Planning ---------------------------------------------------------------

def _pick_hotel(city: str, checkin: str, nights: int, traveller_count: int,
                remaining_budget: int, budget_mode: str) -> Optional[Hotel]:
    hotels = searcher.find_hotels(city, checkin, nights)
    if not hotels:
        return None
    rooms = max(1, (traveller_count + 2) // 3)   # 1-3 people = 1 room, 4-6 = 2, etc.
    if budget_mode == "cheapest":
        return sorted(hotels, key=lambda h: h.price_per_night_inr)[0]
    if budget_mode == "any":
        # No budget given -> mid-tier, not the most expensive
        by_price = sorted(hotels, key=lambda h: h.price_per_night_inr)
        return by_price[len(by_price) // 2]
    affordable = [h for h in hotels
                  if h.price_per_night_inr * nights * rooms <= remaining_budget]
    if affordable:
        return sorted(affordable, key=lambda h: -h.rating)[0]
    return sorted(hotels, key=lambda h: h.price_per_night_inr)[0]


def _book_first_leg(brief: Brief) -> Optional[Flight]:
    """Ask the LLM what the realistic mode for origin -> first city is.
    If it's a flight, search for flights. Otherwise return None and let
    itinerary.build insert a ground-transit event instead."""
    info = llm.generate_transit(brief.origin, brief.destinations[0].city) or {}
    mode = (info.get("mode") or "flight").lower()
    if mode != "flight":
        return None    # itinerary builder will treat origin as prev_city for first segment
    flights = searcher.find_flights(brief.origin, brief.destinations[0].city, brief.travel_date)
    return sorted(flights, key=lambda f: f.price_inr)[0] if flights else None


def _build_itinerary(brief: Brief, flight: Optional[Flight] = None,
                     hotels: Optional[List[Hotel]] = None,
                     force_skip_flight_decision: bool = False) -> Itinerary:
    """Build (or rebuild) an itinerary. If flight/hotels are passed, reuse them
    instead of re-searching — used by change management."""
    if flight is None and not force_skip_flight_decision:
        flight = _book_first_leg(brief)

    rooms = max(1, (brief.traveller_count + 2) // 3)

    if hotels is None:
        cap = brief.budget_max_inr or 10**9
        spent = (flight.price_inr * brief.traveller_count) if flight else 0
        hotels = []
        cur_date = datetime.fromisoformat(brief.travel_date)
        for stop in brief.destinations:
            h = _pick_hotel(stop.city, cur_date.strftime("%Y-%m-%d"),
                            stop.nights, brief.traveller_count,
                            cap - spent, brief.budget_mode)
            hotels.append(h)
            if h:
                spent += h.price_per_night_inr * stop.nights * rooms
            cur_date += timedelta(days=stop.nights)

    days, total = itin.build(brief, flight, hotels)
    similar = personalization.retrieve(brief, k=3)
    return Itinerary(
        brief=brief, flight=flight,
        hotels=[h for h in hotels if h],
        days=days, total_cost_inr=total,
        similar_travelers=similar,
    )


# ----- Change management ------------------------------------------------------

def _handle_change(state: ConversationState, intent: str, user_msg: str) -> AgentReply:
    it = state.itinerary
    if not it:
        return _ask(state, "Plan a trip first, then I can help with changes.")

    if intent == "cancel_flight":
        flights = searcher.find_flights(it.brief.origin,
                                        it.brief.destinations[0].city,
                                        it.brief.travel_date)
        alternatives = [f for f in flights if it.flight is None or f.flight_id != it.flight.flight_id]
        if not alternatives:
            return _ask(state, "No alternative flights are available for that route/date.")
        new_flight = sorted(alternatives, key=lambda f: f.price_inr)[0]
        new_it = _build_itinerary(it.brief, flight=new_flight, hotels=it.hotels)
        state.itinerary = new_it
        msg = (f"I cancelled the original flight and re-booked you on **{new_flight.airline} "
               f"{new_flight.flight_id}** (₹{new_flight.price_inr:,}). The rest of the itinerary "
               f"is unchanged; check-in time has been re-anchored to the new arrival.")
        state.history.append({"role": "assistant", "content": msg})
        return AgentReply(text=msg, changed_itinerary=new_it)

    if intent == "delay_flight":
        hours = 3
        m = re.search(r"(\d+)\s*hour", user_msg.lower())
        if m:
            hours = int(m.group(1))
        if not it.flight:
            return _ask(state, "No flight on this trip to delay.")
        delayed = deepcopy(it.flight)
        delayed.depart_time = (datetime.fromisoformat(it.flight.depart_time)
                               + timedelta(hours=hours)).isoformat(timespec="minutes")
        delayed.arrive_time = (datetime.fromisoformat(it.flight.arrive_time)
                               + timedelta(hours=hours)).isoformat(timespec="minutes")
        new_it = _build_itinerary(it.brief, flight=delayed, hotels=it.hotels)
        state.itinerary = new_it
        msg = f"Pushed your flight back {hours}h and re-anchored everything downstream."
        state.history.append({"role": "assistant", "content": msg})
        return AgentReply(text=msg, changed_itinerary=new_it)

    if intent == "change_dates":
        m = re.search(r"\d{4}-\d{2}-\d{2}", user_msg)
        if not m:
            return _ask(state, "What new date would you like? Reply with a YYYY-MM-DD date.")
        state.brief.travel_date = m.group(0)
        new_it = _build_itinerary(state.brief)
        state.itinerary = new_it
        msg = f"Re-planned everything for {m.group(0)}."
        state.history.append({"role": "assistant", "content": msg})
        return AgentReply(text=msg, changed_itinerary=new_it)

    if intent == "new_trip":
        state.__dict__.update(ConversationState(session_id=state.session_id).__dict__)
        return _ask(state, "Sure, let's plan a new trip! Where will you start from?")

    return _ask(state, "I can help with cancellations, delays, or changing dates. What would you like to do?")


# ----- Main loop --------------------------------------------------------------

def _summarize_plan(state: ConversationState, it: Itinerary, issues: List[str]) -> str:
    b = state.brief
    cities_label = " → ".join(s.city for s in b.destinations)
    hotel_total = sum(h.price_per_night_inr * s.nights
                      for h, s in zip(it.hotels, b.destinations))

    over_budget = bool(b.budget_mode == "cap" and b.budget_max_inr
                       and it.total_cost_inr > int(b.budget_max_inr * 1.1))
    if over_budget:
        over = it.total_cost_inr - b.budget_max_inr
        msg = (
            f"⚠️ **Heads up — your budget of ₹{b.budget_max_inr:,} won't cover this trip.**\n\n"
            f"The cheapest realistic plan I could build for **{cities_label}** comes to "
            f"**₹{it.total_cost_inr:,}** (over by ₹{over:,}). Biggest line items:\n"
            f"- Flight: ₹{(it.flight.price_inr if it.flight else 0):,}\n"
            f"- Hotels ({len(it.hotels)} city stays, {b.duration_days} nights): ₹{hotel_total:,}\n\n"
            f"You can bump your budget, shorten the trip, or pick a cheaper region. "
            f"Otherwise the full plan is below."
        )
    else:
        if b.budget_mode == "cheapest":
            tag = " (cheapest realistic option)"
        elif b.budget_mode == "cap" and b.budget_max_inr:
            tag = f", within your ₹{b.budget_max_inr:,} budget"
        else:
            tag = ""
        msg = (
            f"All set! Here's your **{b.duration_days}-day plan covering {cities_label}** "
            f"(total ~₹{it.total_cost_inr:,}{tag}). "
            f"If your flight gets delayed or cancelled, just tell me — I'll re-plan."
        )
    other = [i for i in issues if "Estimated cost" not in i]
    if other:
        msg += "\n\n**Other notes:**\n" + "\n".join(f"- {x}" for x in other)
    return msg


def respond(state: ConversationState, user_msg: str) -> Tuple[ConversationState, AgentReply]:
    state.history.append({"role": "user", "content": user_msg})

    if not storage.check_rate_limit(state):
        return state, AgentReply(text="You've hit the per-session call limit. Clear the chat to start over.")

    updates = llm.extract_updates(state.history, state.brief, state.last_suggestions, user_msg)
    storage.record_llm_call(state)

    if state.itinerary:
        intent = (updates.get("change_intent") or "none").lower()
        if intent in ("cancel_flight", "delay_flight", "change_dates", "new_trip"):
            return state, _handle_change(state, intent, user_msg)

    _apply_updates(state, updates)
    b = state.brief

    # Ask one missing thing at a time
    if not b.origin:
        return state, _ask(state, "Where will you start your trip from?")
    if not b.travel_date:
        return state, _ask(state, "When would you like to travel? (any date or 'next month')")
    if not b.duration_days:
        return state, _ask(state, "How many days will the trip last?")
    if not b.budget_resolved:
        return state, _ask(state, "Roughly what's your total budget in INR? (or say 'no budget' / 'cheapest possible')")
    if not b.destination:
        if not b.vibe:
            return state, _ask(state, VIBE_PROMPT)
        suggestions = llm.suggest_destinations(b, exclude=state.visited_already)
        storage.record_llm_call(state)
        state.last_suggestions = [s.city for s in suggestions]
        if not suggestions:
            return state, _ask(state, "I couldn't think of fresh options — could you tell me a city you'd like to go to?")
        budget_str = f"₹{b.budget_max_inr:,}" if b.budget_max_inr else b.budget_mode
        text = (
            f"Here are 3 picks for a {b.vibe} trip from {b.origin}, {b.duration_days} days, budget {budget_str}:\n\n"
            f"{_format_suggestions(suggestions)}\n\n"
            f"Which one would you like, or tell me you've been to some and I'll suggest more."
        )
        state.history.append({"role": "assistant", "content": text})
        return state, AgentReply(text=text, suggestions=suggestions)

    # All info present — plan the trip
    it = _build_itinerary(b)
    state.itinerary = it
    issues = critic.validate(it)
    msg = _summarize_plan(state, it, issues)
    state.history.append({"role": "assistant", "content": msg})
    return state, AgentReply(text=msg, itinerary=it)
