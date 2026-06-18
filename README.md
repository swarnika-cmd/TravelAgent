# Agentic Travel Planner

A chat-style travel planner for India. Tell it anything about your trip — even just *"I want to plan a trip"* — and it asks the right follow-up questions, suggests destinations that fit your vibe, plans the day-by-day itinerary, and handles disruptions (delays, cancellations) when you tell it about them.

## What it does

```
USER  Bangalore to Kerala for 5 days with 3 people, no budget
AGENT What kind of trip — adventure, religious, nature, party...?

USER  nature
AGENT Picks Munnar (2n) + Alleppey (2n) + Kochi (1n) for you.
      Plans Day 1...5 with morning/afternoon/evening activities,
      breakfast/lunch/dinner picks, inter-city transit.
      Total ₹47,820 (mid-tier, per-room hotels, train inter-city).

USER  my flight got cancelled
AGENT Re-books the next-cheapest flight and re-anchors all check-ins.
```

## Architecture

No model training, no heavy backend. A small Python state machine around three free services:

1. **Google Gemini** — language understanding, destination suggestion, and on-demand generation of activities / restaurants / hotels / transit for any Indian city.
   Fallback chain: `gemini-3.1-flash-lite` → `gemini-2.5-flash-lite` → `gemini-2.5-flash`. Auto-walks the chain on 503 / overload.
2. **Sky-Scrapper (RapidAPI)** — live flight + hotel prices. Mocks gracefully when the key is missing or quota is gone.
3. **Sentence-transformers + FAISS** — local semantic retrieval over the Kaggle Indian Travel Survey for the "people like you" personalization. Falls back to 5 hand-written personas if you haven't built the index.

## Files

```
app.py              Streamlit chat UI (single file)
agent.py            Conversation orchestrator — one respond() function
schemas.py          Pydantic models
llm.py              All Gemini calls (extract, suggest, generate)
searcher.py         Sky-Scrapper client (live + mock)
itinerary.py        Day-by-day plan assembly
critic.py           Conflict detector (chronology, budget, tight gaps)
personalization.py  RAG retriever + index builder
storage.py          Per-session JSON persistence + LLM rate limiter
requirements.txt    Python deps
```

Runtime artifacts in `data/cache/`, `data/sessions/`, `data/raw/` are gitignored.

## Setup

```bash
pip install -r requirements.txt
```

Create `.env`:

```
GEMINI_API_KEY=AIzaSy...                           # https://aistudio.google.com/apikey
RAPIDAPI_KEY=your_rapidapi_key                     # https://rapidapi.com  (optional)
RAPIDAPI_HOST=sky-scrapper.p.rapidapi.com
```

Optional — override the Gemini model chain:

```
GEMINI_MODEL=gemini-3.1-flash-lite,gemini-2.5-flash-lite,gemini-2.5-flash
```

Without a RapidAPI key, flights/hotels come from mocks (the LLM still generates city-realistic hotel options). Everything else still works.

## Run

```bash
streamlit run app.py
```

Opens at http://localhost:8501.

Try these:

- *"Bangalore to Mysore for 3 days with 3 people, cheapest possible"*
- *"I want a 5-day adventure trip from Delhi, no budget"*
- *"Couple from Mumbai going to Kerala in August, 7 days, ₹80000"*
- *"Plan a religious trip from Chennai for 4 days under 25k"*

## Web UI — "Safar"

A second, design-led frontend lives in `web/`, served by a tiny stdlib HTTP
server. **No extra dependencies, no build step** — it talks to the same
`agent.respond()` the Streamlit app uses.

```bash
python server.py            # http://127.0.0.1:8000
python server.py --port 9000
```

The trip is presented as a journey on a **split-flap departure board** with a
day-by-day route line, boarding-pass / reservation tickets, and the
"travellers like you" matches. The conversation drives everything from a side
rail.

No Gemini key yet? Click **Explore a sample trip** (or `POST /api/sample`) to
load a complete Bangalore → Kerala itinerary and tour the whole interface
offline. Add `GEMINI_API_KEY` to chat live.

### Quick plan, trip actions & more

Beyond the chat, a few structured controls drive the **real** planner directly
(no LLM needed for the mechanics — they call `agent._apply_updates`,
`_build_itinerary` and `_handle_change`):

- **Quick plan** — dropdowns for origin, destination, date, days, travellers,
  vibe and budget. Pick a destination and it builds the itinerary on the spot;
  leave it on *"Let AI suggest"* to hand off to the chat (needs a key).
- **Trip actions** — once a plan exists: rebook a cancelled flight, delay it by
  2/3/6h, change the travel date, or start over. Each re-anchors the itinerary.
- **Share** — copies a `?sid=` link to the exact trip. **Print** — a print
  stylesheet lays the itinerary out cleanly for paper or PDF.
- `?quick=1` opens the quick-plan panel on load; `?sid=…` opens a shared trip.

| Route | Does |
|---|---|
| `GET /` | the app (`web/index.html`) |
| `GET /api/state?sid=` | current conversation state + runtime flags |
| `POST /api/chat` | `{sid, message}` → agent reply + new state |
| `POST /api/reset` | clear the session |
| `POST /api/sample` | seed a ready-made sample trip (needs `sample_trip.py`) |
| `POST /api/brief` | `{sid, updates}` → apply structured brief fields (no LLM) |
| `POST /api/plan` | build the itinerary from the current brief |
| `POST /api/action` | a disruption: `cancel_flight` / `delay_flight` / `change_dates` / `new_trip` |

## How the chat flow works

1. Agent asks for whatever's missing — **one thing at a time** (origin / dates / duration / budget / vibe).
2. If you give a state ("Kerala", "Rajasthan"), it picks **multiple cities** in that state matched to the vibe and distributes nights sensibly.
3. If you only give a vibe (no destination), it **suggests 3 specific cities**; "I've been to X" or "show me more" excludes them.
4. Once every required field is filled, it plans and shows the full itinerary.
5. After the plan exists, type something like *"my flight got cancelled"* / *"delay 3 hours"* / *"change to 2026-08-15"* and the agent re-plans the affected leg.

## How the cost is calculated

Realistic, not naive:

- **Flight** — only if the LLM says flight is the right mode for the route distance. Otherwise ground transit (train/bus/cab) is inserted on Day 1. Flight cost × travellers.
- **Hotels** — per **room**, not per person. 1-3 people = 1 room, 4-6 = 2 rooms, etc.
- **Activities + meals** — per person.
- **Inter-city transit** — train under ~600 km, flight over ~1200 km, cab/bus in between.
- **Budget mode** controls hotel pick: `cap` = best-rated within budget; `cheapest` = cheapest available; `any` = mid-tier (not max luxury); `none` = agent asks first.

## Personalization (RAG)

Each plan includes the top 3 "similar travelers" retrieved from a survey corpus. Without the dataset, you get 5 representative personas. To use real data:

1. Drop `travel_survey.csv` from the Kaggle Indian Travel Survey at `data/raw/travel_survey.csv`.
2. Build the index once:
   ```bash
   python personalization.py build
   ```
3. Run as normal — embeddings live in `data/cache/rag/`.

## Per-session rate limit

Each chat is capped at **80 LLM calls** (configurable in `storage.py`). The sidebar shows usage. "Clear chat & start over" resets the counter and the saved JSON.

## Assignment coverage

| Requirement | Where |
|---|---|
| Travel Brief Intake | `llm.extract_updates` runs every turn |
| Agentic Search | `searcher` (live + mock) + `llm.generate_*` for unknown cities |
| Itinerary Assembly | `itinerary.build` — day-by-day, multi-city, transit-aware |
| Conflict Resolution | `critic.validate` — chronology, budget, tight gaps |
| Change Management | `agent._handle_change` — cancel / delay / dates / new trip |
| Traveller Dashboard | `app.py` (Streamlit) **and** `server.py` + `web/` (Safar web UI) |

## Project layout map

```
.
├── app.py              # Streamlit entry
├── server.py           # stdlib web server for the Safar UI (no extra deps)
├── sample_trip.py      # offline sample itinerary for the web UI
├── web/                # Safar frontend — index.html / styles.css / app.js
├── agent.py            # orchestrator
├── schemas.py          # types
├── llm.py              # Gemini wrapper
├── searcher.py         # Sky-Scrapper
├── itinerary.py        # day builder
├── critic.py           # validator
├── personalization.py  # RAG
├── storage.py          # session + rate limit
├── requirements.txt
├── README.md
├── .env                # local secrets (gitignored)
├── .gitignore
└── data/
    ├── cache/          # LLM + API caches (gitignored)
    ├── sessions/       # per-user chat JSONs (gitignored)
    └── raw/            # optional Kaggle CSVs (gitignored)
```

## Running the Test Suite

Safar includes a comprehensive failure-focused test suite that validates the planner's behavior under edge cases and service failures.

The tests use Python's built-in `unittest` framework, so no additional testing dependencies are required.

### Install dependencies

```bash
pip install -r requirements.txt
```

### Run the tests

From the project root:

```bash
python tests/test_agent_failures.py
```

Or with the unittest runner:

```bash
python -m unittest tests.test_agent_failures
```

### What is covered?

The suite mocks external services (`llm`, `storage`, `searcher`, etc.) and verifies that the agent fails gracefully in difficult scenarios.

| Test                                    | Purpose                                                                                  |
| --------------------------------------- | ---------------------------------------------------------------------------------------- |
| Rate Limit Exceeded                     | Verifies the agent returns a call-limit warning when `storage.check_rate_limit()` fails. |
| Missing Flights for Delay Intent        | Ensures flight-delay requests are handled safely when the itinerary contains no flights. |
| No Alternative Flights for Cancellation | Simulates cancelled flights when `searcher.find_flights()` returns no alternatives.      |
| Invalid Date Extraction                 | Confirms malformed date values from the LLM do not crash date-change flows.              |
| Empty Destination Suggestions           | Checks behavior when `llm.suggest_destinations()` returns no recommendations.            |
| Garbage Data Fault Tolerance            | Sends malformed structured data into `_apply_updates()` to verify defensive handling.    |
| Over-Budget Safeguards                  | Forces itinerary costs beyond the user's budget and validates warning prompts.           |

### Notes

* External APIs are mocked and are **not called** during testing.
* The suite can be executed without a Gemini API key.
* Tests focus on resilience, validation, and recovery behavior rather than itinerary quality.
