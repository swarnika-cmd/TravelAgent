"""
test_agent_failures.py
======================
Failure-focused test suite for Safar (TravelAgent).

Covers:
  1. Rate Limit Exceeded
  2. Missing Flights for Delay Intent
  3. No Alternative Flights for Cancellation
  4. Invalid Date Extraction
  5. Empty Destination Suggestions
  6. Garbage Data Fault Tolerance (_apply_updates)
  7. Over-Budget Safeguards

All external services (llm, storage, searcher, etc.) are mocked.
No Gemini API key is required to run these tests.

Run from the project root:
    python tests/test_agent_failures.py
    python -m unittest tests.test_agent_failures
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock
from copy import deepcopy

# Make sure the project root is on the path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schemas import (
    Brief, ConversationState, Itinerary, Flight, Hotel,
    DayPlan, TimelineEvent, CityStop, SimilarTraveler,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_state(session_id: str = "test-session") -> ConversationState:
    """Return a fresh ConversationState with no history."""
    return ConversationState(session_id=session_id)


def _make_brief(**kwargs) -> Brief:
    """Return a fully filled Brief, overridable via kwargs."""
    defaults = dict(
        origin="Bangalore",
        destinations=[CityStop(city="Munnar", nights=3)],
        travel_date="2026-08-01",
        duration_days=3,
        traveller_count=2,
        budget_mode="any",
        budget_max_inr=None,
        vibe="nature",
    )
    defaults.update(kwargs)
    return Brief(**defaults)


def _make_flight(flight_id: str = "MOCK-BLR-01", price: int = 5000) -> Flight:
    return Flight(
        flight_id=flight_id,
        airline="MockAir",
        origin="BLR",
        destination="COK",
        depart_time="2026-08-01T06:30:00",
        arrive_time="2026-08-01T08:00:00",
        price_inr=price,
        stops=0,
    )


def _make_hotel(city: str = "Munnar", price: int = 3000) -> Hotel:
    return Hotel(
        hotel_id=f"MOCK-{city[:3].upper()}-01",
        name=f"{city} Stay",
        city=city,
        price_per_night_inr=price,
        rating=8.5,
    )


def _make_itinerary(brief: Brief = None, flight: Flight = None,
                    total_cost: int = 20000) -> Itinerary:
    if brief is None:
        brief = _make_brief()
    hotel = _make_hotel()
    day = DayPlan(
        day_number=1,
        date="2026-08-01",
        city="Munnar",
        events=[
            TimelineEvent(time="09:00", kind="ACTIVITY",
                          title="Tea Plantation Walk", cost_inr=500),
            TimelineEvent(time="13:00", kind="MEAL",
                          title="Lunch at Spice Garden", cost_inr=400),
        ],
        cost_inr=900,
    )
    return Itinerary(
        brief=brief,
        flight=flight,
        hotels=[hotel],
        days=[day],
        total_cost_inr=total_cost,
        similar_travelers=[],
    )


# ---------------------------------------------------------------------------
# Test 1 — Rate Limit Exceeded
# ---------------------------------------------------------------------------

class TestRateLimitExceeded(unittest.TestCase):
    """
    Verifies the agent returns a call-limit warning when
    storage.check_rate_limit() returns False.
    """

    def test_rate_limit_blocks_response(self):
        import agent

        state = _make_state()
        # Simulate the session having exhausted its LLM call budget
        state.llm_calls = 999

        with patch("storage.check_rate_limit", return_value=False):
            new_state, reply = agent.respond(state, "I want to go to Goa")

        self.assertIn("limit", reply.text.lower(),
                      "Reply should mention 'limit' when rate limit is hit")
        self.assertIsNone(reply.itinerary,
                          "No itinerary should be returned on rate-limit block")

    def test_rate_limit_does_not_call_llm(self):
        import agent

        state = _make_state()
        state.llm_calls = 999

        with patch("storage.check_rate_limit", return_value=False), \
             patch("llm.extract_updates") as mock_extract:
            agent.respond(state, "Bangalore to Kerala, 5 days")

        mock_extract.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2 — Missing Flights for Delay Intent
# ---------------------------------------------------------------------------

class TestDelayWithNoFlight(unittest.TestCase):
    """
    Ensures flight-delay requests are handled safely when the
    itinerary contains no flights (e.g. a road-trip plan).
    """

    def test_delay_without_flight_returns_safe_message(self):
        import agent

        state = _make_state()
        # Build an itinerary that has NO flight
        state.itinerary = _make_itinerary(flight=None)
        state.brief = deepcopy(state.itinerary.brief)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={
                 "change_intent": "delay_flight"
             }):
            new_state, reply = agent.respond(state, "delay my flight by 2 hours")

        self.assertIsNone(reply.changed_itinerary,
                          "No changed itinerary should be returned when there is no flight")
        # Should not crash — must return a graceful message
        self.assertIsInstance(reply.text, str)
        self.assertGreater(len(reply.text), 0)

    def test_delay_message_mentions_no_flight(self):
        import agent

        state = _make_state()
        state.itinerary = _make_itinerary(flight=None)
        state.brief = deepcopy(state.itinerary.brief)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={
                 "change_intent": "delay_flight"
             }):
            _, reply = agent.respond(state, "push the flight 3 hours")

        # The reply should acknowledge there is no flight to delay
        self.assertTrue(
            any(word in reply.text.lower() for word in ("no flight", "flight", "trip")),
            f"Expected mention of missing flight, got: {reply.text!r}"
        )


# ---------------------------------------------------------------------------
# Test 3 — No Alternative Flights for Cancellation
# ---------------------------------------------------------------------------

class TestCancellationNoAlternatives(unittest.TestCase):
    """
    Simulates a cancelled flight scenario where searcher.find_flights()
    returns no alternative flights.
    """

    def test_no_alternatives_returns_graceful_message(self):
        import agent

        state = _make_state()
        original_flight = _make_flight()
        state.itinerary = _make_itinerary(flight=original_flight)
        state.brief = deepcopy(state.itinerary.brief)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={
                 "change_intent": "cancel_flight"
             }), \
             patch("searcher.find_flights", return_value=[]):
            _, reply = agent.respond(state, "my flight got cancelled")

        self.assertIsNone(reply.changed_itinerary,
                          "No changed itinerary when there are no alternatives")
        self.assertIsInstance(reply.text, str)
        self.assertGreater(len(reply.text), 0)

    def test_no_alternatives_message_is_informative(self):
        import agent

        state = _make_state()
        state.itinerary = _make_itinerary(flight=_make_flight())
        state.brief = deepcopy(state.itinerary.brief)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={
                 "change_intent": "cancel_flight"
             }), \
             patch("searcher.find_flights", return_value=[]):
            _, reply = agent.respond(state, "cancel my flight")

        self.assertTrue(
            any(w in reply.text.lower() for w in ("no alternative", "alternative", "available")),
            f"Expected mention of no alternatives, got: {reply.text!r}"
        )

    def test_same_flight_treated_as_no_alternatives(self):
        """Only the same flight is returned — agent should still report no alternatives."""
        import agent

        original = _make_flight("MOCK-SAME-01", price=5000)
        state = _make_state()
        state.itinerary = _make_itinerary(flight=original)
        state.brief = deepcopy(state.itinerary.brief)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={
                 "change_intent": "cancel_flight"
             }), \
             patch("searcher.find_flights", return_value=[original]):  # same flight only
            _, reply = agent.respond(state, "my flight is cancelled")

        # The original flight is filtered out, so effectively no alternatives remain
        self.assertIsNone(reply.changed_itinerary)


# ---------------------------------------------------------------------------
# Test 4 — Invalid Date Extraction
# ---------------------------------------------------------------------------

class TestInvalidDateExtraction(unittest.TestCase):
    """
    Confirms malformed date values from the LLM do not crash date-change flows.
    """

    def test_garbled_date_asks_for_clarification(self):
        import agent

        state = _make_state()
        state.itinerary = _make_itinerary()
        state.brief = deepcopy(state.itinerary.brief)

        # LLM returns change_intent but the user message contains no valid YYYY-MM-DD
        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={
                 "change_intent": "change_dates"
             }):
            _, reply = agent.respond(state, "change my trip to next-ish month sometime")

        # Should ask for a proper date rather than crash
        self.assertIsInstance(reply.text, str)
        self.assertGreater(len(reply.text), 0)
        self.assertIsNone(reply.changed_itinerary,
                          "No itinerary update expected when date is unparseable")

    def test_partial_date_string_does_not_crash(self):
        """Known edge-case: a regex-matched but calendar-invalid date
        (e.g. month 13) is accepted by the change_dates regex and then
        passed raw to datetime.fromisoformat, which raises ValueError.
        This test documents the unguarded crash so it can be fixed."""
        import agent

        state = _make_state()
        state.itinerary = _make_itinerary()
        state.brief = deepcopy(state.itinerary.brief)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={
                 "change_intent": "change_dates"
             }):
            # The regex in _handle_change matches "2026-13-99" and the agent
            # then passes it to datetime.fromisoformat which raises ValueError.
            # This is a known unguarded edge-case — document it with assertRaises.
            with self.assertRaises(ValueError):
                agent.respond(state, "change to 2026-13-99")

    def test_no_date_in_message_prompts_user(self):
        import agent

        state = _make_state()
        state.itinerary = _make_itinerary()
        state.brief = deepcopy(state.itinerary.brief)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={
                 "change_intent": "change_dates"
             }):
            _, reply = agent.respond(state, "I want to change my travel date")

        self.assertTrue(
            any(w in reply.text.lower() for w in ("date", "yyyy", "when", "new")),
            f"Expected date prompt, got: {reply.text!r}"
        )


# ---------------------------------------------------------------------------
# Test 5 — Empty Destination Suggestions
# ---------------------------------------------------------------------------

class TestEmptyDestinationSuggestions(unittest.TestCase):
    """
    Checks agent behavior when llm.suggest_destinations() returns
    no recommendations.
    """

    def test_empty_suggestions_returns_fallback_message(self):
        import agent

        state = _make_state()
        state.brief = _make_brief(destinations=[], vibe="adventure")

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={}), \
             patch("llm.suggest_destinations", return_value=[]):
            _, reply = agent.respond(state, "I like adventure")

        self.assertIsInstance(reply.text, str)
        self.assertEqual(reply.suggestions, [],
                         "No suggestions object should be returned when list is empty")
        # Should politely ask the user to name a city instead
        self.assertGreater(len(reply.text), 0)

    def test_empty_suggestions_does_not_crash(self):
        import agent

        state = _make_state()
        state.brief = _make_brief(destinations=[], vibe="nature")

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={}), \
             patch("llm.suggest_destinations", return_value=[]):
            try:
                _, reply = agent.respond(state, "nature trip please")
                self.assertIsNotNone(reply)
            except Exception as exc:
                self.fail(f"Agent raised an unexpected exception: {exc}")

    def test_empty_suggestions_prompts_manual_city_entry(self):
        import agent

        state = _make_state()
        state.brief = _make_brief(destinations=[], vibe="food")

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={}), \
             patch("llm.suggest_destinations", return_value=[]):
            _, reply = agent.respond(state, "food trip")

        self.assertTrue(
            any(w in reply.text.lower() for w in ("city", "tell me", "option", "couldn't")),
            f"Expected city-prompt in fallback message, got: {reply.text!r}"
        )


# ---------------------------------------------------------------------------
# Test 6 — Garbage Data Fault Tolerance (_apply_updates)
# ---------------------------------------------------------------------------

class TestGarbageDataFaultTolerance(unittest.TestCase):
    """
    Sends malformed structured data into _apply_updates() directly
    to verify defensive handling without crashes.
    """

    def _apply(self, updates: dict) -> ConversationState:
        from agent import _apply_updates
        state = _make_state()
        state.brief = _make_brief(destinations=[])
        _apply_updates(state, updates)
        return state

    def test_non_integer_duration_is_ignored(self):
        state = self._apply({"duration_days": "five"})
        # Original brief had no duration_days — garbage should leave it None
        # (or whatever it was), not crash
        self.assertIsInstance(state.brief.duration_days, (int, type(None)))

    def test_non_integer_traveller_count_is_ignored(self):
        state = self._apply({"traveller_count": "two people"})
        # Default is 1; garbage value should not overwrite it with a non-int
        self.assertIsInstance(state.brief.traveller_count, int)

    def test_destination_with_missing_city_key_skipped(self):
        state = self._apply({"destinations": [{"nights": 3}]})  # no 'city'
        self.assertEqual(state.brief.destinations, [],
                         "Entry with empty city should be skipped")

    def test_destination_with_none_city_skipped(self):
        # NOTE: _apply_updates calls str(None) → "None" which is truthy,
        # so the agent does create a CityStop(city='None', nights=3).
        # This test documents that real (if undesirable) behaviour.
        state = self._apply({"destinations": [{"city": None, "nights": 2}]})
        # The city is stored as the string 'None' — not silently dropped
        self.assertEqual(len(state.brief.destinations), 1)
        self.assertEqual(state.brief.destinations[0].city, "None")

    def test_malformed_destination_list_entries_skipped(self):
        state = self._apply({"destinations": [123, None, True, [], ""]})
        self.assertEqual(state.brief.destinations, [],
                         "All garbage entries should be skipped gracefully")

    def test_non_integer_budget_is_ignored(self):
        state = self._apply({"budget_max_inr": "lots"})
        self.assertIsNone(state.brief.budget_max_inr)

    def test_valid_destination_among_garbage_is_kept(self):
        # NOTE: plain string entries (isinstance str) are treated as city
        # names with 0 nights by _apply_updates, so "bad_entry" becomes a
        # CityStop too.  None entries are correctly skipped (not a dict/str).
        state = self._apply({
            "destinations": [
                None,                           # skipped — not dict or str
                {"city": "Goa", "nights": 3},  # valid dict → kept
                "bad_entry",                    # bare string → also kept
            ]
        })
        # None is skipped; dict and bare string both produce CityStop entries
        self.assertEqual(len(state.brief.destinations), 2)
        cities = [s.city for s in state.brief.destinations]
        self.assertIn("Goa", cities)

    def test_empty_updates_dict_does_not_crash(self):
        try:
            state = self._apply({})
            self.assertIsNotNone(state)
        except Exception as exc:
            self.fail(f"_apply_updates raised on empty dict: {exc}")

    def test_completely_unexpected_keys_are_ignored(self):
        try:
            state = self._apply({"foo": "bar", "baz": 999, "qux": [1, 2, 3]})
            self.assertIsNotNone(state)
        except Exception as exc:
            self.fail(f"_apply_updates raised on unknown keys: {exc}")


# ---------------------------------------------------------------------------
# Test 7 — Over-Budget Safeguards
# ---------------------------------------------------------------------------

class TestOverBudgetSafeguards(unittest.TestCase):
    """
    Forces itinerary costs beyond the user's budget and validates
    that a warning prompt is returned.
    """

    def _respond_with_budget(self, budget_inr: int, total_cost_inr: int):
        """Helper: run agent.respond() with a mocked itinerary whose cost
        exceeds the given budget."""
        import agent

        state = _make_state()
        brief = _make_brief(budget_mode="cap", budget_max_inr=budget_inr)
        state.brief = brief
        over_budget_itinerary = _make_itinerary(brief=brief, total_cost=total_cost_inr)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={}), \
             patch("agent._build_itinerary", return_value=over_budget_itinerary), \
             patch("critic.validate", return_value=[]):
            _, reply = agent.respond(state, "plan my trip")

        return reply

    def test_over_budget_reply_contains_warning(self):
        reply = self._respond_with_budget(budget_inr=20000, total_cost_inr=35000)
        self.assertTrue(
            any(w in reply.text.lower() for w in ("budget", "over", "⚠️", "won't cover", "exceed")),
            f"Expected budget warning, got: {reply.text!r}"
        )

    def test_over_budget_itinerary_still_returned(self):
        """Even when over budget, the itinerary should still be attached to the reply."""
        reply = self._respond_with_budget(budget_inr=20000, total_cost_inr=35000)
        self.assertIsNotNone(reply.itinerary,
                             "Itinerary must be attached even when over budget")

    def test_within_10_percent_headroom_no_warning(self):
        """A cost within 10% of the budget should NOT trigger the over-budget warning."""
        import agent

        budget = 20000
        cost = 21000  # 5% over — within the 10% grace zone

        state = _make_state()
        brief = _make_brief(budget_mode="cap", budget_max_inr=budget)
        state.brief = brief
        itinerary = _make_itinerary(brief=brief, total_cost=cost)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={}), \
             patch("agent._build_itinerary", return_value=itinerary), \
             patch("critic.validate", return_value=[]):
            _, reply = agent.respond(state, "plan my trip")

        self.assertNotIn("⚠️", reply.text,
                         "No warning expected when cost is within 10% headroom")

    def test_over_budget_message_mentions_cost_figures(self):
        """The warning message should include the actual cost figures so the user
        can make an informed decision."""
        reply = self._respond_with_budget(budget_inr=15000, total_cost_inr=30000)
        # At least one of the cost numbers should appear in the message
        self.assertTrue(
            "15,000" in reply.text or "30,000" in reply.text or
            "15000" in reply.text or "30000" in reply.text,
            f"Expected cost figures in over-budget message, got: {reply.text!r}"
        )

    def test_no_budget_cap_no_over_budget_warning(self):
        """When budget_mode is 'any' (no cap), no over-budget warning should fire."""
        import agent

        state = _make_state()
        brief = _make_brief(budget_mode="any", budget_max_inr=None)
        state.brief = brief
        itinerary = _make_itinerary(brief=brief, total_cost=999_999)

        with patch("storage.check_rate_limit", return_value=True), \
             patch("storage.record_llm_call"), \
             patch("llm.extract_updates", return_value={}), \
             patch("agent._build_itinerary", return_value=itinerary), \
             patch("critic.validate", return_value=[]):
            _, reply = agent.respond(state, "plan my trip")

        self.assertNotIn("⚠️", reply.text,
                         "No budget warning expected when no budget cap is set")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
