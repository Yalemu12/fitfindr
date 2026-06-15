import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_empty_wardrobe, load_listings


# ── Tool 1: search_listings (pure Python, no API key needed) ──────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []   # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


# ── Tool 3: create_fit_card blank-outfit guard (no API key needed) ────────────

_GUARD_MSG = "No outfit suggestion was provided, so there's nothing to caption yet."


def test_create_fit_card_empty_outfit():
    item = load_listings()[0]
    assert create_fit_card("", item) == _GUARD_MSG


def test_create_fit_card_whitespace_outfit():
    item = load_listings()[0]
    assert create_fit_card("   ", item) == _GUARD_MSG


# ── Tool 2: suggest_outfit empty-wardrobe fallback (requires GROQ_API_KEY) ────

@pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set; skipping LLM-dependent test",
)
def test_suggest_outfit_empty_wardrobe():
    item = load_listings()[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""
