"""
Session persistence + per-session LLM rate limit.

Each chat session has its own JSON file under data/sessions/.
Rate limit is enforced inline by the agent before any LLM call.
"""
import json
from pathlib import Path
from schemas import ConversationState

SESSIONS_DIR = Path(__file__).parent / "data" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

MAX_LLM_CALLS_PER_SESSION = 80   # generous; resets when user clears chat


def _path(session_id: str) -> Path:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return SESSIONS_DIR / f"{safe}.json"


def load(session_id: str) -> ConversationState:
    p = _path(session_id)
    if p.exists():
        try:
            return ConversationState.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return ConversationState(session_id=session_id)


def save(state: ConversationState) -> None:
    try:
        _path(state.session_id).write_text(state.model_dump_json(indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[storage] save failed: {e}")


def clear(session_id: str) -> None:
    p = _path(session_id)
    if p.exists():
        p.unlink()


def check_rate_limit(state: ConversationState) -> bool:
    """Return True if the session can make another LLM call."""
    return state.llm_calls < MAX_LLM_CALLS_PER_SESSION


def record_llm_call(state: ConversationState) -> None:
    state.llm_calls += 1
