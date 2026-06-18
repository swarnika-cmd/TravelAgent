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
    POST /api/sample            {sid}           -> a seeded sample trip (needs sample_trip.py)
    POST /api/brief             {sid, updates}  -> apply structured brief fields (no LLM)
    POST /api/plan              {sid}           -> build the itinerary from the current brief
    POST /api/action            {sid, intent}   -> a disruption: cancel / delay / change date / new trip
"""
import json
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import agent
import critic
import storage
import searcher
import llm
from schemas import ConversationState

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
            try:
                from sample_trip import sample_state
            except ImportError:
                return self._send(501, {"error": "sample trip unavailable (sample_trip.py not present)"})
            state = sample_state(sid)
            storage.save(state)
            return self._send(200, _serialize(state))

        # Structured brief from the quick-plan dropdowns — deterministic, no LLM.
        if parsed.path == "/api/brief":
            updates = data.get("updates") or {}
            if not isinstance(updates, dict):
                return self._send(400, {"error": "updates must be an object"})
            state = storage.load(sid)
            try:
                agent._apply_updates(state, updates)
                storage.save(state)
            except Exception as e:
                return self._send(500, {"error": f"could not apply brief: {e}"})
            payload = _serialize(state)
            b = state.brief
            payload["ready"] = bool(b.is_complete and b.destination)
            return self._send(200, payload)

        # Build the itinerary from whatever the brief currently holds.
        if parsed.path == "/api/plan":
            state = storage.load(sid)
            b = state.brief
            if not (b.is_complete and b.destination):
                return self._send(400, {"error": "Set origin, travel date, duration and a destination city first."})
            try:
                it = agent._build_itinerary(b)
                state.itinerary = it
                issues = critic.validate(it)
                msg = agent._summarize_plan(state, it, issues)
                state.history.append({"role": "assistant", "content": msg})
                storage.save(state)
            except Exception as e:
                return self._send(500, {"error": f"planning failed: {e}"})
            return self._send(200, _serialize(state))

        # Disruptions / change-management, routed straight to the real handler.
        if parsed.path == "/api/action":
            intent = (data.get("intent") or "").strip()
            if intent not in ("cancel_flight", "delay_flight", "change_dates", "new_trip"):
                return self._send(400, {"error": f"unknown action '{intent}'"})
            state = storage.load(sid)
            if intent == "delay_flight":
                hours = int(data.get("hours") or 3)
                user_msg, label = f"delay my flight {hours} hours", f"Delay flight by {hours}h"
            elif intent == "change_dates":
                date = (data.get("date") or "").strip()
                if not date:
                    return self._send(400, {"error": "a new date is required"})
                user_msg, label = f"change the date to {date}", f"Change travel date to {date}"
            elif intent == "cancel_flight":
                user_msg, label = "my flight got cancelled", "Flight cancelled"
            else:
                user_msg, label = "plan a new trip", "Start a new trip"
            state.history.append({"role": "user", "content": label})
            try:
                reply = agent._handle_change(state, intent, user_msg)
                storage.save(state)
            except Exception as e:
                return self._send(500, {"error": f"action failed: {e}"})
            payload = _serialize(state)
            payload["reply"] = reply.model_dump()
            return self._send(200, payload)

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
