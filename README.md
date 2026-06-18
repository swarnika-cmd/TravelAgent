# Agentic Travel Planner

A chat-style travel agent for India. Tell it anything about your trip — even just "I want to plan a trip" — and it asks the right follow-up questions, suggests destinations that fit your vibe, plans the day-by-day itinerary, and handles disruptions (delays, cancellations) when you tell it about them.

## How it actually works

There is **no model training**. The agent is a small Python state machine wrapped around three things:

1. **Google Gemini** — language understanding, smart questions, destination suggestion, on-demand activity / restaurant / hotel / transit generation for any Indian city. Uses a fallback chain: `gemini-3.1-flash-lite` → `gemini-2.5-flash-lite` → `gemini-2.5-flash`, auto-falling through on overload.
2. **Sky-Scrapper (RapidAPI)** — live flight and hotel prices, with mock fallback when the key is missing or quota exhausted.
3. **Sentence-transformers + FAISS** — semantic retrieval over the Kaggle Indian Travel Survey for personalization (falls back to 5 hand-written personas if the index isn't built).

## Files

```
app.py              Streamlit chat UI
agent.py            Conversation orchestrator — single respond() function
schemas.py          Pydantic models
llm.py              All Gemini calls (extract, suggest, generate)
searcher.py         Sky-Scrapper client (live + mock)
itinerary.py        Day-by-day plan builder
critic.py           Conflict detector
personalization.py  RAG retriever (+ index builder)
storage.py          Session save/load + rate limiter
data/sessions/      Saved conversations (per session)
data/cache/         API + LLM response cache
data/raw/           Drop Kaggle CSVs here
```

## Setup

```bash
pip install -r requirements.txt
```

Create `.env`:

```
GEMINI_API_KEY=AIzaSy...           # from https://aistudio.google.com/apikey
RAPIDAPI_KEY=your_rapidapi_key     # from https://rapidapi.com (optional)
RAPIDAPI_HOST=sky-scrapper.p.rapidapi.com
```

Optional override of the model chain:

```
GEMINI_MODEL=gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemini-2.5-flash
```

Without a RapidAPI key, flight/hotel search falls back to mock data — the rest of the agent still works.

## Run

```bash
streamlit run app.py
```

Opens at http://localhost:8501.

## Optional: build the personalization index

If you've put the Kaggle Indian Travel Survey CSV at `data/raw/travel_survey.csv`:

```bash
python personalization.py build
```

This produces a FAISS index used by the personalization retriever. Without it, you get 5 hand-written representative personas.

## How the chat flow works

1. Agent asks for whatever's missing — one thing at a time.
2. If you give a city, it uses it. If you only give a vibe (adventure / heritage / religious / etc.), it suggests 3 specific Indian cities.
3. If you reply "I've already been to X" or "show me more", it excludes those and suggests fresh ones.
4. Once origin / destination / date / duration / budget are all filled, it plans.
5. After planning, type "my flight got cancelled" / "delay 3 hours" / "change to 2026-08-15" — it detects the intent and re-plans.

## Per-session rate limit

Each chat session is capped at 80 LLM calls (configurable in `storage.py`). Click "Clear chat & start over" in the sidebar to reset.

## Assignment coverage

| Requirement | Where |
|---|---|
| Travel Brief Intake | `llm.extract_updates` in every turn |
| Agentic Search | `searcher` (live + mock) + `llm.generate_*` for unknown cities |
| Itinerary Assembly | `itinerary.build` |
| Conflict Resolution | `critic.validate` |
| Change Management | `agent._handle_change` (cancel / delay / dates / new) |
| Traveller Dashboard | `app.py` with timeline, bookings, personalization panel, chat |
