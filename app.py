"""
Streamlit chat UI.

Run: streamlit run app.py
"""
import uuid
import importlib
import streamlit as st

# Force-reload backend modules on every script run so code edits don't need a restart
import agent, storage, llm, searcher, itinerary, critic, personalization
for m in (llm, searcher, itinerary, critic, personalization, storage, agent):
    importlib.reload(m)

from agent import respond
from storage import load, save, clear

st.set_page_config(page_title="Travel Agent", page_icon="✈️", layout="wide")

# --- session ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())[:8]
if "state" not in st.session_state:
    st.session_state.state = load(st.session_state.session_id)


def reset_chat():
    clear(st.session_state.session_id)
    st.session_state.session_id = str(uuid.uuid4())[:8]
    st.session_state.state = load(st.session_state.session_id)


# --- Sidebar ---
with st.sidebar:
    st.title("✈️ Travel Agent")
    st.caption("Chat with me about your trip.")
    st.divider()
    state = st.session_state.state
    b = state.brief
    st.markdown("**Trip so far**")
    st.markdown(f"- Origin: `{b.origin or '—'}`")
    if b.destinations:
        cities_str = ", ".join(f"{s.city} ({s.nights}n)" for s in b.destinations)
        st.markdown(f"- Cities: `{cities_str}`")
    else:
        st.markdown("- Cities: `—`")
    st.markdown(f"- Date: `{b.travel_date or '—'}`")
    st.markdown(f"- Duration: `{b.duration_days or '—'} days`")
    st.markdown(f"- Budget: `₹{b.budget_max_inr:,}`" if b.budget_max_inr else "- Budget: `—`")
    st.markdown(f"- Vibe: `{b.vibe or '—'}`")
    st.markdown(f"- Travellers: `{b.traveller_count}`")
    if state.visited_already:
        st.caption(f"Excluded (visited/rejected): {', '.join(state.visited_already)}")
    st.divider()
    st.caption(f"LLM calls used: {state.llm_calls} / 80")
    if st.button("🗑️ Clear chat & start over", use_container_width=True):
        reset_chat()
        st.rerun()
    if not searcher.is_live_mode():
        st.warning("Sky-Scrapper key missing — using mock flights/hotels.")

# --- Main pane ---
state = st.session_state.state

st.title("Plan a trip")

# Replay history
for msg in state.history:
    role = msg["role"]
    with st.chat_message(role):
        st.markdown(msg["content"])

# If an itinerary exists, render it under the chat
if state.itinerary:
    it = state.itinerary
    with st.expander(f"🗺️ Your trip plan — total ₹{it.total_cost_inr:,}", expanded=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Origin", it.brief.origin or "—")
        cities_label = " → ".join(s.city for s in it.brief.destinations) if it.brief.destinations else "—"
        c2.metric("Cities", cities_label)
        c3.metric("Duration", f"{it.brief.duration_days} days")
        c4.metric("Travellers", it.brief.traveller_count)
        c5.metric("Total", f"₹{it.total_cost_inr:,}", delta=f"cap ₹{it.brief.budget_max_inr:,}" if it.brief.budget_max_inr else None,
                  delta_color="inverse" if it.brief.budget_max_inr and it.total_cost_inr > it.brief.budget_max_inr else "normal")

        tab1, tab2 = st.tabs(["📅 Day plan", "🛏️ Bookings"])

        with tab1:
            for dp in it.days:
                with st.container(border=True):
                    st.subheader(f"Day {dp.day_number} — {dp.city}")
                    st.caption(f"{dp.date}  ·  ~₹{dp.cost_inr:,}")
                    icon = {"FLIGHT_DEPART": "🛫", "FLIGHT_ARRIVE": "🛬",
                            "HOTEL_CHECKIN": "🛎️", "ACTIVITY": "🎯", "MEAL": "🍽️",
                            "TRANSIT_DEPART": "🚆", "TRANSIT_ARRIVE": "🚉"}
                    for ev in dp.events:
                        emoji = icon.get(ev.kind, "•")
                        line = f"{emoji} **{ev.time}**  &nbsp; {ev.title}"
                        if ev.note:
                            line += f"  _({ev.note})_"
                        st.markdown(line)

        with tab2:
            travellers = it.brief.traveller_count
            rooms = max(1, (travellers + 2) // 3)
            if it.flight:
                f = it.flight
                with st.container(border=True):
                    st.markdown(f"**🛫 {f.airline} — {f.flight_id}**")
                    st.caption(f"{f.origin} → {f.destination} · {f.depart_time.replace('T',' ')} · {f.stops} stops")
                    c_a, c_b = st.columns(2)
                    c_a.metric("Per ticket", f"₹{f.price_inr:,}")
                    c_b.metric(f"× {travellers} pax", f"₹{f.price_inr * travellers:,}")
            else:
                with st.container(border=True):
                    st.markdown("**🚆 No flight — using ground transit**")
                    st.caption(f"From {it.brief.origin} → {it.brief.destinations[0].city}. See Day 1 for the transit details.")
            for i, h in enumerate(it.hotels):
                stop = it.brief.destinations[i] if i < len(it.brief.destinations) else None
                nights = stop.nights if stop else 1
                with st.container(border=True):
                    st.markdown(f"**🛏️ {h.name}**")
                    st.caption(f"{h.city} · rating {h.rating} · {nights} nights · {rooms} room(s)")
                    c_a, c_b = st.columns(2)
                    c_a.metric("Per night / room", f"₹{h.price_per_night_inr:,}")
                    c_b.metric("Stay total", f"₹{h.price_per_night_inr * nights * rooms:,}")

# Welcome message if history empty
if not state.history:
    with st.chat_message("assistant"):
        st.markdown(
            "Hi! I'm your travel planner. Tell me anything about your trip — even just "
            "*'I want to plan a trip'* works. I'll ask whatever I need.\n\n"
            "**Examples:**\n"
            "- *I want a 5-day adventure trip from Bangalore, budget 50000*\n"
            "- *Plan a religious trip from Delhi for 4 days under 25k*\n"
            "- *Honeymoon from Mumbai in August*"
        )

# Input
prompt = st.chat_input("Tell me about your trip, or ask a follow-up...")
if prompt:
    state, reply = respond(state, prompt)
    save(state)
    st.session_state.state = state
    st.rerun()
