"""
Validate an itinerary for obvious conflicts.
Returns a list of human-readable issue strings (empty = clean).
"""
from typing import List
from schemas import Itinerary


def validate(it: Itinerary) -> List[str]:
    issues = []
    if not it:
        return ["No itinerary"]

    # Budget check (allow 10% headroom)
    if it.brief.budget_max_inr and it.total_cost_inr > int(it.brief.budget_max_inr * 1.1):
        over = it.total_cost_inr - it.brief.budget_max_inr
        issues.append(
            f"Estimated cost ₹{it.total_cost_inr:,} exceeds budget ₹{it.brief.budget_max_inr:,} "
            f"by ₹{over:,} ({int(over / it.brief.budget_max_inr * 100)}% over)."
        )

    # Same-day chronology
    for dp in it.days:
        times = [e.time for e in dp.events]
        if times != sorted(times):
            issues.append(f"Day {dp.day_number}: events not in time order")

    # Tight back-to-back activities (less than 90 min apart)
    for dp in it.days:
        acts = [e for e in dp.events if e.kind == "ACTIVITY"]
        for a, b in zip(acts, acts[1:]):
            t1 = int(a.time[:2]) * 60 + int(a.time[3:5])
            t2 = int(b.time[:2]) * 60 + int(b.time[3:5])
            if t2 - t1 < 90:
                issues.append(f"Day {dp.day_number}: tight gap between {a.title} and {b.title}")

    return issues
