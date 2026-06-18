"""
Web UI server — zero extra dependencies.

A tiny stdlib HTTP server that puts a real frontend in front of the same
agent the Streamlit app uses (agent.respond). Keeps the repo's "no heavy
backend" spirit: no FastAPI, no build step.

    python server.py            # http://127.0.0.1:8000
    python server.py --port 9000

Routes
    GET  /                      web/index.html
    GET  /<asset>               static files from web/
    GET  /api/state?sid=...     current ConversationState (+ runtime flags)
    POST /api/chat              {sid, message}  -> {reply, state}
    POST /api/reset             {sid}           -> fresh state
    POST /api/sample            {sid}           -> a seeded sample trip (no API key needed)
"""
import json
import argparse
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import agent
import storage
import searcher
import llm
from schemas import (
    Brief, CityStop, ConversationState, Flight, Hotel, DayPlan,
    TimelineEvent, Itinerary, SimilarTraveler,
)

WEB_DIR = Path(__file__).parent / "web"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
}


# ----- Runtime flags ----------------------------------------------------------

def _llm_live() -> bool:
    key = llm.GEMINI_KEY
    return bool(key) and not key.startswith("your_")


def _serialize(state: ConversationState) -> dict:
    return {
        "state": state.model_dump(),
        "flags": {
            "llm_live": _llm_live(),
            "search_live": searcher.is_live_mode(),
            "llm_calls_max": storage.MAX_LLM_CALLS_PER_SESSION,
        },
    }


# ----- Sample trip (no API key required) --------------------------------------
# A hand-built Bangalore -> Kerala plan that mirrors agent output exactly, so the
# full itinerary view is explorable offline. Same shapes as itinerary.build().

def _sample_state(sid: str) -> ConversationState:
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

    def ev(time, kind, title, note="", cost=0):
        return TimelineEvent(time=time, kind=kind, title=title, note=note, cost_inr=cost)

    days = [
        DayPlan(day_number=1, date=(start).strftime("%Y-%m-%d"), city="Munnar", cost_inr=21540, events=[
            ev("06:30", "FLIGHT_DEPART", "IndiGo 6E-643 BLR -> COK", "0 stops", 4180),
            ev("07:45", "FLIGHT_ARRIVE", "Arrive at COK"),
            ev("08:30", "TRANSIT_DEPART", "Cab COK -> Munnar", "~4.0h", 3200),
            ev("12:30", "TRANSIT_ARRIVE", "Arrive at Munnar"),
            ev("13:30", "HOTEL_CHECKIN", "Check in at Spice Tree Munnar", "", 6800),
            ev("13:00", "MEAL", "Saravana Bhavan", "South Indian, ~₹250/pp", 750),
            ev("18:00", "ACTIVITY", "Tea Museum & sunset point", "nature, ~2.0h", 600),
            ev("18:00", "MEAL", "Rapsy Restaurant", "Kerala, ~₹350/pp", 1050),
        ]),
        DayPlan(day_number=2, date=(start + timedelta(days=1)).strftime("%Y-%m-%d"), city="Munnar", cost_inr=10180, events=[
            ev("09:00", "ACTIVITY", "Eravikulam National Park", "nature, ~3.5h", 1500),
            ev("09:00", "MEAL", "SN Restaurant", "veg, ~₹200/pp", 600),
            ev("13:00", "ACTIVITY", "Kolukkumalai tea estate trek", "adventure, ~3.0h", 2400),
            ev("13:00", "MEAL", "Eastend Eatery", "multi-cuisine, ~₹400/pp", 1200),
            ev("18:00", "MEAL", "The Tea Sanctuary cafe", "cafe, ~₹300/pp", 900),
        ]),
        DayPlan(day_number=3, date=(start + timedelta(days=2)).strftime("%Y-%m-%d"), city="Alleppey", cost_inr=13050, events=[
            ev("08:00", "TRANSIT_DEPART", "Cab Munnar -> Alleppey", "~4.5h", 3600),
            ev("12:30", "TRANSIT_ARRIVE", "Arrive at Alleppey"),
            ev("13:30", "HOTEL_CHECKIN", "Board Lake Canopy Houseboat", "", 7400),
            ev("13:00", "MEAL", "Thaff Restaurant", "seafood, ~₹450/pp", 1350),
            ev("18:00", "ACTIVITY", "Backwater sunset cruise", "nature, ~2.0h", 0),
            ev("18:00", "MEAL", "Onboard Kerala thali dinner", "Kerala, ~₹300/pp", 900),
        ]),
        DayPlan(day_number=4, date=(start + timedelta(days=3)).strftime("%Y-%m-%d"), city="Alleppey", cost_inr=11290, events=[
            ev("09:00", "ACTIVITY", "Houseboat backwater day-cruise", "nature, ~5.0h", 0),
            ev("09:00", "MEAL", "Onboard breakfast", "Kerala, ~₹200/pp", 600),
            ev("13:00", "MEAL", "Halais Restaurant", "biryani, ~₹350/pp", 1050),
            ev("18:00", "ACTIVITY", "Marari Beach evening walk", "beach, ~2.0h", 0),
            ev("18:00", "MEAL", "Chakara seafood shack", "seafood, ~₹500/pp", 1500),
        ]),
        DayPlan(day_number=5, date=(start + timedelta(days=4)).strftime("%Y-%m-%d"), city="Kochi", cost_inr=9760, events=[
            ev("08:00", "TRANSIT_DEPART", "Cab Alleppey -> Kochi", "~1.5h", 1800),
            ev("09:30", "TRANSIT_ARRIVE", "Arrive at Kochi"),
            ev("10:30", "HOTEL_CHECKIN", "Check in at Forte Kochi", "", 5200),
            ev("13:00", "ACTIVITY", "Fort Kochi & Chinese fishing nets", "heritage, ~2.5h", 300),
            ev("13:00", "MEAL", "Kashi Art Cafe", "cafe, ~₹400/pp", 1200),
            ev("18:00", "ACTIVITY", "Kathakali performance, Greenix", "culture, ~1.5h", 1500),
            ev("18:00", "MEAL", "Oceanos Restaurant", "seafood, ~₹450/pp", 1350),
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


# ----- HTTP handler -----------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "SafarUI/1.0"

    def log_message(self, fmt, *args):  # quieter console
        pass

    # -- helpers --
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def _serve_static(self, path):
        rel = path.lstrip("/") or "index.html"
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR.resolve() not in target.parents and target != WEB_DIR.resolve():
            return self._send(403, {"error": "forbidden"})
        if not target.is_file():
            return self._send(404, {"error": "not found"})
        ctype = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

    # -- routing --
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            sid = (parse_qs(parsed.query).get("sid") or ["default"])[0]
            return self._send(200, _serialize(storage.load(sid)))
        if parsed.path == "/" or not parsed.path.startswith("/api"):
            return self._serve_static(parsed.path)
        self._send(404, {"error": "unknown route"})

    def do_POST(self):
        parsed = urlparse(self.path)
        data = self._read_json()
        sid = (data.get("sid") or "default").strip() or "default"

        if parsed.path == "/api/chat":
            message = (data.get("message") or "").strip()
            if not message:
                return self._send(400, {"error": "empty message"})
            state = storage.load(sid)
            try:
                state, reply = agent.respond(state, message)
                storage.save(state)
            except Exception as e:
                return self._send(500, {"error": f"agent failed: {e}"})
            payload = _serialize(state)
            payload["reply"] = reply.model_dump()
            return self._send(200, payload)

        if parsed.path == "/api/reset":
            storage.clear(sid)
            return self._send(200, _serialize(storage.load(sid)))

        if parsed.path == "/api/sample":
            state = _sample_state(sid)
            storage.save(state)
            return self._send(200, _serialize(state))

        self._send(404, {"error": "unknown route"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    live = "live" if _llm_live() else "no GEMINI key (chat is limited — try a sample trip)"
    print(f"Safar UI  ->  http://{args.host}:{args.port}   [LLM: {live}]")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
