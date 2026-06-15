"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── query parsing ─────────────────────────────────────────────────────────────

# Standalone size tokens, matched case-insensitively with word boundaries.
_SIZE_WORD_RE = re.compile(r"\b(XS|S|M|L|XL|XXL|W\d+)\b", re.IGNORECASE)
_SIZE_PHRASE_RE = re.compile(r"\bsize\s+(\S+)", re.IGNORECASE)
_SHOE_SIZE_RE = re.compile(r"\b(\d{1,2})\b")
_PRICE_RE = re.compile(r"(?:under|below|<|\$)\s*\$?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_PLAIN_NUMBER_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)")
_CONNECTOR_RE = re.compile(r"\b(under|below|in|size|for|priced)\b", re.IGNORECASE)


def _parse_query(query: str) -> dict:
    """
    Extract a description, size, and max_price from a free-text query.

    Returns a dict shaped {"description", "size", "max_price"}. The parse is
    deterministic pure-Python (no LLM): price/size substrings are stripped out
    and the remaining cleaned text becomes the description. If stripping leaves
    an empty description, the full original query is used instead.
    """
    working = query
    max_price: float | None = None
    size: str | None = None

    # max_price: prefer a price cue ("under $30", "$30"), else a bare "$30".
    price_match = _PRICE_RE.search(working) or _PLAIN_NUMBER_RE.search(working)
    if price_match:
        max_price = float(price_match.group(1))
        working = working[: price_match.start()] + " " + working[price_match.end():]

    # size: explicit "size X" phrase first, else a standalone size token.
    size_phrase = _SIZE_PHRASE_RE.search(working)
    if size_phrase:
        size = size_phrase.group(1).strip().upper()
        working = working[: size_phrase.start()] + " " + working[size_phrase.end():]
    else:
        size_word = _SIZE_WORD_RE.search(working)
        if size_word:
            size = size_word.group(1).upper()
            working = (
                working[: size_word.start()] + " " + working[size_word.end():]
            )
        else:
            shoe = _SHOE_SIZE_RE.search(working)
            if shoe:
                size = shoe.group(1)
                working = working[: shoe.start()] + " " + working[shoe.end():]

    # description: remove leftover connector words, collapse whitespace.
    working = _CONNECTOR_RE.sub(" ", working)
    description = re.sub(r"\s+", " ", working).strip(" ,.-").strip()
    if not description:
        description = query.strip()

    return {"description": description, "size": size, "max_price": max_price}


def _no_results_message(parsed: dict) -> str:
    """Build an actionable no-results error string naming the applied filters."""
    description = parsed.get("description", "")
    size = parsed.get("size")
    max_price = parsed.get("max_price")

    filters = f"'{description}'"
    if size:
        filters += f", size {size}"
    if max_price is not None:
        filters += f", under ${max_price:g}"

    msg = f"I couldn't find any listings matching {filters}. Try "
    suggestions = []
    if max_price is not None:
        suggestions.append(f"raising your budget above ${max_price:g}")
    if size:
        suggestions.append("dropping the size filter")
    suggestions.append(
        "broadening the style (e.g. 'graphic tee' instead of 'vintage 2003 tour tee')"
    )
    msg += ", ".join(suggestions[:-1])
    if len(suggestions) > 1:
        msg += ", or " + suggestions[-1]
    else:
        msg += suggestions[-1]
    msg += (
        ". I didn't generate an outfit or fit card because there was nothing to style."
    )
    return msg


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: Initialize the session.
    session = _new_session(query, wardrobe)

    # Step 2: Parse the query into description / size / max_price.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: Search listings with the parsed parameters.
    session["search_results"] = search_listings(
        parsed["description"], parsed["size"], parsed["max_price"]
    )

    # Branch: no results → set error and return early. Downstream tools are
    # NOT called when there is nothing to style.
    if not session["search_results"]:
        session["error"] = _no_results_message(parsed)
        return session

    # Step 4: Select the top-ranked match.
    session["selected_item"] = session["search_results"][0]

    # Step 5: Style the selected item against the wardrobe.
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 6: Caption the look using the outfit suggestion and the same item.
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: Return the completed session.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
