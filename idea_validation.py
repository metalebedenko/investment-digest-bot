"""Bounded structural checks before untrusted model output reaches a report.

These checks do not establish the accuracy of claims, sources or scores.
"""

import math


MAX_IDEAS = 10
MAX_RESPONSE_IDEAS = 100
MAX_TEXT_LENGTH = 6000
TEXT_FIELDS = (
    "name", "category", "summary", "revenue_model", "target_client",
    "innovation", "investment_format", "investment_range", "why_interesting",
    "risks", "verdict", "localization_label",
)
ASSESSMENT_FIELDS = {
    "scores": {"novelty", "market_potential", "ease_of_launch", "scalability",
               "hypothesis_speed", "investment_appeal", "risk"},
    "localization": {"russia_potential", "replication_ease",
                     "operational_feasibility", "complexity_threshold"},
}


def validate_count(count: int, *, allow_auto: bool = False) -> int:
    minimum = 0 if allow_auto else 1
    if type(count) is not int or not minimum <= count <= MAX_IDEAS:
        raise ValueError(f"Idea count must be an integer from {minimum} to {MAX_IDEAS}")
    return count


def validate_ideas(ideas: list, *, limit=None) -> list[dict]:
    """Return selected plain records, or fail before a partial PDF can be sent."""
    if not isinstance(ideas, list) or not ideas or len(ideas) > MAX_RESPONSE_IDEAS:
        raise ValueError("Expected a bounded nonempty list of ideas")
    if limit is None:
        if len(ideas) > MAX_IDEAS:
            raise ValueError("A report must contain no more than ten ideas")
        limit = MAX_IDEAS
    validate_count(limit)
    selected = []
    for idea in ideas[:limit]:
        if not isinstance(idea, dict):
            raise ValueError("Each idea must be an object")
        clean = {}
        for key in TEXT_FIELDS:
            if key not in idea:
                if key in {"name", "summary"}:
                    raise ValueError("Idea is missing a required text field")
                continue
            value = idea[key]
            if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
                raise ValueError("Invalid idea text field")
            if key in {"name", "summary"} and not value.strip():
                raise ValueError("Required idea text must not be empty")
            clean[key] = value
        for key in ("scores", "localization"):
            values = idea.get(key, {})
            if not isinstance(values, dict) or len(values) > 20:
                raise ValueError("Invalid numeric assessment object")
            for label, value in values.items():
                if not isinstance(label, str) or label not in ASSESSMENT_FIELDS[key]:
                    raise ValueError("Invalid numeric assessment label")
                if (type(value) not in (int, float) or not 0 <= value <= 10
                        or not math.isfinite(value)):
                    raise ValueError("Assessment values must be finite numbers from zero to ten")
            clean[key] = dict(values)
        sources = idea.get("sources", [])
        if (not isinstance(sources, list) or len(sources) > 10
                or any(not isinstance(value, str) or len(value) > 2048 for value in sources)):
            raise ValueError("Sources must be a bounded list of text links")
        clean["sources"] = list(sources)
        selected.append(clean)
    return selected
