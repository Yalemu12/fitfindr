# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock secondhand-listings dataset (`data/listings.json`, loaded via `load_listings()`) for items that match a free-text description, then applies optional size and price filters and returns the surviving listings ranked by keyword relevance. It is pure Python (no LLM) so it is deterministic and cheap to test.

**Input parameters:**
- `description` (str): Free-text keywords describing the target piece, e.g. `"vintage graphic tee"`. Used for keyword-overlap scoring against each listing's `title`, `description`, and `style_tags`.
- `size` (str | None): Size string to filter by (e.g. `"M"`), or `None` to skip size filtering. Matching is case-insensitive and substring-based so `"M"` matches `"S/M"` and `"M"` matches `"M"`.
- `max_price` (float | None): Inclusive price ceiling (e.g. `30.0`), or `None` to skip price filtering. A listing survives if `listing["price"] <= max_price`.

**What it returns:**
A `list[dict]` of matching listing dicts, sorted by relevance score (highest first). Each dict has exactly these fields: `id` (str, e.g. `"lst_006"`), `title` (str), `description` (str), `category` (str: one of `tops`, `bottoms`, `outerwear`, `shoes`, `accessories`), `style_tags` (list[str]), `size` (str), `condition` (str: `excellent`/`good`/`fair`), `price` (float), `colors` (list[str]), `brand` (str | None), `platform` (str: `depop`/`thredUp`/`poshmark`). Listings whose keyword score is `0` are dropped. Returns an empty list `[]` when nothing matches — it never raises.

**What happens if it fails or returns nothing:**
On an empty result the agent does NOT call any downstream tool. The planning loop sets `session["error"]` to an actionable message that names the filters that were applied and suggests concrete adjustments (raise the budget above `max_price`, drop the `size` filter, or broaden the description), then returns the session early.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the chosen thrifted item plus the user's wardrobe and uses the Groq LLM to write 1–2 concrete outfit suggestions that pair the new item with specific pieces the user already owns, plus a short styling/fit tip.

**Input parameters:**
- `new_item` (dict): A single listing dict returned by `search_listings` (the item the user is considering). The tool uses its `title`, `category`, `colors`, and `style_tags` to anchor the suggestion.
- `wardrobe` (dict): A wardrobe dict shaped `{"items": [ ... ]}` where each item has `id`, `name`, `category`, `colors`, `style_tags`, and optional `notes` (see `data/wardrobe_schema.json`). May be empty (`items == []`) — must be handled gracefully.

**What it returns:**
A non-empty `str` containing 1–2 outfit ideas. When the wardrobe has items, the string names real pieces by their `name` field (e.g. "Baggy straight-leg jeans, dark wash" + "Chunky white sneakers") and includes a fit tip. When the wardrobe is empty, it returns general styling advice for the item (what categories/colors/vibes pair well) instead of inventing items the user does not own.

**What happens if it fails or returns nothing:**
If `wardrobe["items"]` is empty, the tool itself returns the general-advice fallback string (never empty). If the LLM call raises or returns a blank string, the tool returns a short fallback like `"Couldn't generate a styling suggestion right now — try this piece with neutral basics and your go-to shoes."`. The planning loop treats a non-empty string as success and proceeds; it never blocks the run on a styling miss.

---

### Tool 3: create_fit_card

**What it does:**
Generates a short, casual, social-ready caption (an OOTD-style "fit card") for the thrifted find, using the outfit suggestion and the item details. Uses a higher LLM temperature so repeated calls read differently.

**Input parameters:**
- `outfit` (str): The outfit-suggestion string returned by `suggest_outfit()`. Supplies the vibe/pairings the caption should reference.
- `new_item` (dict): The listing dict for the thrifted item. The caption mentions its `title`, `price`, and `platform` naturally (once each).

**What it returns:**
A 2–4 sentence `str` usable directly as an Instagram/TikTok caption. If `outfit` is empty or whitespace-only, it returns a descriptive error string (e.g. `"No outfit suggestion was provided, so there's nothing to caption yet."`) rather than raising.

**What happens if it fails or returns nothing:**
The tool guards against a blank `outfit` and returns the descriptive error string above. If the LLM call fails, it returns a plain fallback caption built from `new_item` fields (`"Thrifted: {title} for ${price} on {platform}."`). The planning loop stores whatever string is returned in `session["fit_card"]` and surfaces it in the fit-card panel; it does not terminate the run on a fit-card failure.

---

### Additional Tools (if any)

None for the core build. (Stretch idea, not yet implemented: `parse_query(query) -> {description, size, max_price}` as a dedicated LLM-backed parser to replace the regex parsing done inline in the planning loop.)

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop is deterministic and linear: each tool's output is the precondition that triggers the next tool. There is no open-ended re-planning. The branches are:

1. **Initialize.** `session = _new_session(query, wardrobe)`.
2. **Parse the query.** Extract `max_price` from a `under $X` / `$X` pattern (regex `\$?\s*(\d+(?:\.\d+)?)`), extract `size` from a `size X` pattern or standalone size tokens (`XS/S/M/L/XL`, `W\d+`, or numeric shoe sizes), and treat the remaining cleaned text as `description`. **Branch:** if stripping price/size leaves an empty `description`, fall back to using the full original `query` as `description`. Store all three in `session["parsed"]`.
3. **Search.** `results = search_listings(parsed["description"], parsed["size"], parsed["max_price"])`; store in `session["search_results"]`.
   - **Branch (error / early return):** if `results == []`, set `session["error"]` to an actionable message naming the applied filters and suggested adjustments, then `return session` immediately. Do NOT call `suggest_outfit` or `create_fit_card`.
   - **Branch (continue):** if `results` is non-empty, proceed.
4. **Select.** `session["selected_item"] = results[0]` (top-ranked match).
5. **Style.** `outfit = suggest_outfit(session["selected_item"], session["wardrobe"])`; store in `session["outfit_suggestion"]`. The empty-wardrobe case is handled inside the tool (general advice), so the loop always receives a non-empty string and continues.
6. **Caption.** `card = create_fit_card(session["outfit_suggestion"], session["selected_item"])`; store in `session["fit_card"]`.
7. **Done.** `return session`. The loop is complete when `create_fit_card` returns, or earlier if the no-results branch fired. `session["error"]` is `None` on a full success and a non-empty string on early termination.

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session(query, wardrobe)` in `agent.py`) is the one source of truth for the whole interaction. Each step reads the fields written by earlier steps and writes its own:

- `query` (str) — original user text; read by the parse step.
- `parsed` (dict) — `{description, size, max_price}`; written by the parse step, read by `search_listings`.
- `search_results` (list[dict]) — written by `search_listings`; read to pick the selection.
- `selected_item` (dict | None) — `search_results[0]`; written after search, read by both `suggest_outfit` and `create_fit_card`.
- `wardrobe` (dict) — passed in at session creation; read by `suggest_outfit`.
- `outfit_suggestion` (str | None) — written by `suggest_outfit`; read by `create_fit_card`.
- `fit_card` (str | None) — written by `create_fit_card`; read by the UI.
- `error` (str | None) — set only when an early-return branch fires; checked first by the UI (`app.py handle_query`).

Data flow: `search_results → selected_item`; `selected_item + wardrobe → outfit_suggestion`; `outfit_suggestion + selected_item → fit_card`. Setting `error` short-circuits the chain and leaves the later fields as `None`.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Stop after search. Set `session["error"]` to: "I couldn't find any listings matching '<description>'<, size X><, under $Y>. Try raising your budget above $Y, dropping the size filter, or broadening the style (e.g. 'graphic tee' instead of 'vintage 2003 tour tee'). I didn't generate an outfit or fit card because there was nothing to style." Downstream tools are not called. |
| suggest_outfit | Wardrobe is empty | The tool returns general styling advice (categories, colors, and vibes that pair with the item) instead of naming pieces the user doesn't own. The agent prefixes the panel with "Your wardrobe is empty, so here are general styling ideas:" and still proceeds to `create_fit_card`. |
| create_fit_card | Outfit input is missing or incomplete | The tool returns a descriptive string ("No outfit suggestion was provided, so there's nothing to caption yet.") rather than raising. The agent stores it in `session["fit_card"]` and shows the listing + outfit panels normally, with that note in the fit-card panel. |

---

## Architecture

```
User query  ("vintage graphic tee under $30, ...")
    │
    ▼
Planning Loop (run_agent) ───────────────────────────────────────────────┐
    │                                                                     │
    │  parse query → session["parsed"] = {description, size, max_price}   │
    │                                                                     │
    ├─► search_listings(description, size, max_price)                     │
    │       │ results = []                                                │
    │       ├──► [ERROR] session["error"]="No listings found… adjust X"   │
    │       │         → return session  ──────────────────────────────┐  │
    │       │                                                          │  │
    │       │ results = [lst_006, lst_002, …]                          │  │
    │       ▼                                                          │  │
    │   Session: search_results = results                              │  │
    │   Session: selected_item   = results[0]                          │  │
    │       │                                                          │  │
    ├─► suggest_outfit(selected_item, wardrobe)                        │  │
    │       │  (empty wardrobe → general advice fallback inside tool)  │  │
    │       ▼                                                          │  │
    │   Session: outfit_suggestion = "Pair it with…"                   │  │
    │       │                                                          │  │
    └─► create_fit_card(outfit_suggestion, selected_item)              │  │
            │  (blank outfit → descriptive error string inside tool)   │  │
            ▼                                                          │  │
        Session: fit_card = "Thrifted gold…"                          │  │
            │                                                          │  │
            ▼                                                          │  │
        Return session ◄──────── error path returns here ─────────────┘  │
            │                                                             │
            ▼                                                             │
   app.py handle_query: if session["error"] → show in panel 1 only;      │
   else map selected_item/outfit_suggestion/fit_card → 3 UI panels ──────┘

Session State (single dict, threaded through every step):
  query · parsed · search_results · selected_item · wardrobe ·
  outfit_suggestion · fit_card · error
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

- **`search_listings` (Claude):** Input = the Tool 1 block above (inputs, return fields, empty-result behavior) plus the `load_listings()` docstring from `utils/data_loader.py`. Expected output = a pure-Python function that loads listings, filters by `max_price` and `size` when provided, scores remaining listings by keyword overlap of `description` against `title`/`description`/`style_tags`, drops score-0 listings, sorts descending, and returns the dicts. Verify before use: confirm it filters by all three parameters, drops zero-score matches, returns `[]` (not an exception) on no match, then test three queries — "vintage graphic tee under $30" (expect `lst_006`/`lst_002`), "90s track jacket in size M" (expect `lst_004`), "designer ballgown size XXS under $5" (expect `[]`).
- **`suggest_outfit` (Claude):** Input = the Tool 2 block plus `data/wardrobe_schema.json` so it knows wardrobe item fields. Expected output = a function with two branches (empty wardrobe → general advice; non-empty → LLM prompt that names real wardrobe `name` values). Verify: confirm the empty-`items` branch never references owned pieces and never returns an empty string; run it once with `get_example_wardrobe()` (should name baggy jeans / chunky sneakers) and once with `get_empty_wardrobe()` (should give general advice).
- **`create_fit_card` (Claude):** Input = the Tool 3 block. Expected output = a function that guards a blank `outfit`, builds a caption prompt from `new_item` fields, and calls the LLM at higher temperature. Verify: confirm the blank-`outfit` guard returns the descriptive string, that `title`/`price`/`platform` each appear once, and that two different items produce two different captions.

**Milestone 4 — Planning loop and state management:**

- **`run_agent` (Claude):** Input = the Planning Loop section, the State Management section, the Architecture diagram above, and the `agent.py` skeleton (`_new_session` + the `run_agent` TODO). Expected output = `run_agent` implementing the 7 steps and exact branches, writing each field into `session` as specified. Verify before trusting: confirm it sets `session["error"]` and returns early when `search_results == []` (and that it does NOT call `suggest_outfit`/`create_fit_card` in that case), sets `selected_item = results[0]`, and threads state through correctly. Then run `python agent.py` and confirm the happy path (graphic tee) fills all three output fields and the no-results path ("designer ballgown size XXS under $5") returns an `error` with the other fields `None`.

---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**What FitFindr needs to do:** FitFindr is a thrift-shopping styling agent: given a natural-language request, it searches a mock secondhand-listings dataset for matching pieces, then styles a chosen item against the user's existing wardrobe and writes a short, social-ready fit card. The user's request triggers `search_listings`; a successful match triggers `suggest_outfit`; a returned suggestion triggers `create_fit_card`. If `search_listings` finds nothing, the agent stops and tells the user what to change (raise the budget, drop the size filter, broaden the style) rather than calling the downstream tools with empty input, and `suggest_outfit` against an empty wardrobe should fall back gracefully instead of inventing items the user doesn't own.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 0 — Parse:**
`run_agent` initializes the session and parses the query into `session["parsed"] = {"description": "vintage graphic tee", "size": None, "max_price": 30.0}` (the budget comes from "under $30"; no explicit size token, so `size` stays `None`).

**Step 1 — search_listings:**
The agent calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. The tool drops anything over $30, scores the rest by keyword overlap, and returns matches sorted by relevance — e.g. `lst_006` "Graphic Tee — 2003 Tour Bootleg Style" ($24) first, then `lst_002` "Y2K Baby Tee — Butterfly Print" ($18). The loop stores the list in `session["search_results"]` and sets `session["selected_item"] = results[0]` (`lst_006`).

**Step 2 — suggest_outfit:**
Using the chosen listing as `new_item` and `get_example_wardrobe()` as `wardrobe`, the agent calls `suggest_outfit(new_item=<lst_006 graphic tee>, wardrobe=<10-item example wardrobe>)`. It returns a string pairing the tee with the user's "Baggy straight-leg jeans, dark wash" (w_001) and "Chunky white sneakers" (w_007), plus a fit tip (e.g. half-tuck the front for shape). Stored in `session["outfit_suggestion"]`.

**Step 3 — create_fit_card:**
The agent calls `create_fit_card(outfit=<suggestion>, new_item=<lst_006>)`, which returns a 2–4 sentence casual caption mentioning the tee's title, its $24 price, and the `depop` platform once each, capturing the vibe. Stored in `session["fit_card"]`.

**Final output to user:**
`app.py` checks `session["error"]` (None here) and fills the three panels: the matched listing (title, price, platform, condition) in panel 1, the styling suggestion in panel 2, and the fit-card caption in panel 3. **Error path:** if `search_listings` had returned `[]` (e.g. the "designer ballgown size XXS under $5" example), the agent stops after Step 1, sets `session["error"]` with what to adjust, leaves `outfit_suggestion`/`fit_card` as `None`, and never calls `suggest_outfit` or `create_fit_card`.
