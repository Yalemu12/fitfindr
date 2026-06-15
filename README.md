# FitFindr 🛍️

FitFindr is a thrift-shopping styling agent. Given a natural-language request
like *"vintage graphic tee under $30, size M,"* it searches a mock secondhand
listings dataset for matching pieces, styles the best match against the user's
existing wardrobe, and writes a short, social-ready "fit card" caption for the
look. It runs as a three-panel Gradio web app.

The interesting part of FitFindr is not any single tool — it's the **planning
loop** that decides *whether* to call the next tool at all. The agent only
styles an item if it actually found one, and only captions an outfit if it
actually produced one. This README explains those decisions, not just the
mechanics.

---

## Setup

```bash
pip install -r requirements.txt
```

Add your Groq API key to a `.env` file in this directory (free key at
[console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

## Run it

```bash
python app.py
```

Open the URL printed in your terminal. It is usually
<http://localhost:7860>, but **check the terminal output** — Gradio will pick a
different port if 7860 is taken.

Pick a wardrobe (Example or Empty), type a request, and hit **Find it**. The
three panels fill in left-to-right: the top listing found, an outfit idea built
from your wardrobe, and a shareable fit card.

You can also run the agent headless:

```bash
python agent.py        # runs a happy-path query and a no-results query
python -m pytest -q    # runs the tool/loop test suite
```

---

## Tool Inventory

The agent has three tools. `search_listings` is pure Python (deterministic,
cheap, no LLM). The other two call the Groq LLM (`llama-3.3-70b-versatile`).

### 1. `search_listings(description, size, max_price) -> list[dict]`

| Field | Detail |
|-------|--------|
| **Purpose** | Find listings in `data/listings.json` that match the user's request, after applying optional size/price filters, ranked by keyword relevance. |
| **Inputs** | `description` (`str`) — free-text keywords, e.g. `"vintage graphic tee"`. <br> `size` (`str \| None`) — size filter, case-insensitive **substring** match (`"M"` matches `"S/M"`); `None` skips the filter. <br> `max_price` (`float \| None`) — inclusive price ceiling; `None` skips the filter. |
| **Output** | `list[dict]` of listing dicts sorted by relevance score (highest first). Each dict has `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`. Listings with a keyword score of `0` are dropped. Returns `[]` when nothing matches — **it never raises**. |

How relevance works: the description is tokenized, and each listing scores +1
per token that appears anywhere in its `title` + `description` + `style_tags`.
Listings that pass the price/size filters but match zero tokens are discarded so
the agent never "styles" an irrelevant item.

### 2. `suggest_outfit(new_item, wardrobe) -> str`

| Field | Detail |
|-------|--------|
| **Purpose** | Pair the chosen thrifted item with pieces the user already owns and add a fit tip. |
| **Inputs** | `new_item` (`dict`) — a listing dict from `search_listings` (uses its `title`, `category`, `colors`, `style_tags`). <br> `wardrobe` (`dict`) — shaped `{"items": [...]}` where each item has `id`, `name`, `category`, `colors`, `style_tags`, optional `notes`. May be empty. |
| **Output** | A non-empty `str` with 1–2 outfit ideas. With a populated wardrobe it names real pieces by their `name` (e.g. *"Baggy straight-leg jeans, dark wash"* + *"Chunky white sneakers"*) plus a fit tip. With an empty wardrobe it returns **general** styling advice instead of inventing pieces the user doesn't own. |

### 3. `create_fit_card(outfit, new_item) -> str`

| Field | Detail |
|-------|--------|
| **Purpose** | Write a casual, OOTD-style caption for the find. |
| **Inputs** | `outfit` (`str`) — the suggestion string from `suggest_outfit`. <br> `new_item` (`dict`) — the same listing dict (uses `title`, `price`, `platform`). |
| **Output** | A 2–4 sentence `str` caption mentioning the item's title, price, and platform once each. Uses a higher LLM temperature (0.9) so repeated calls read differently. |

---

## How the Planning Loop Works

The loop lives in `run_agent(query, wardrobe)` in `agent.py`. It is a
**deterministic, linear pipeline**, not an open-ended re-planner: each tool's
output is the *precondition* that decides whether the next tool runs. There are
no loops or backtracking — the design choice here is that every branch point is
a "do I have valid input for the next step?" check, which makes the agent's
behavior predictable and easy to test.

The agent makes three real decisions:

1. **How to read the query (parse step).** Before any tool runs, `_parse_query`
   splits the free-text query into `{description, size, max_price}` using
   regex — no LLM, so it's deterministic and free. It pulls a price from cues
   like `under $30` / `$30`, a size from an explicit `size M` phrase, else a
   standalone size token (`XS/S/M/L/XL`, `W30`), else a bare number treated as a
   shoe size. **Decision / fallback:** if stripping the price and size words
   leaves an empty description, the agent falls back to using the *original full
   query* as the description rather than searching for "". This is why
   `"size M"` alone still searches sensibly instead of matching everything.

2. **Whether to style anything at all (the key branch).** The agent calls
   `search_listings` and then checks the result:
   - **If `search_results == []`** → it sets `session["error"]` to an actionable
     message (naming the exact filters it applied and what to relax), and
     **returns immediately**. It deliberately does **not** call `suggest_outfit`
     or `create_fit_card`, because styling nothing would either crash or
     hallucinate an item. This is the single most important decision in the
     loop.
   - **If there are results** → it selects `search_results[0]` (the
     highest-scoring match) as `selected_item` and continues.

3. **How to style for this specific user.** `suggest_outfit(selected_item,
   wardrobe)` runs. The empty-vs-populated wardrobe decision is made *inside* the
   tool, so the loop always receives a non-empty string and can move on. Then
   `create_fit_card(outfit_suggestion, selected_item)` writes the caption. Both
   LLM tools degrade to a usable fallback string on failure (see Error
   Handling), so a flaky LLM call never aborts the whole run — only an empty
   search does.

Step-by-step:

```
1. session = _new_session(query, wardrobe)
2. session["parsed"]         = _parse_query(query)        # {description, size, max_price}
3. session["search_results"] = search_listings(...)       # pure Python
        └─ if [] → session["error"] = actionable message; RETURN early  ← decision
4. session["selected_item"]  = search_results[0]          # top-ranked match
5. session["outfit_suggestion"] = suggest_outfit(selected_item, wardrobe)   # LLM
6. session["fit_card"]          = create_fit_card(outfit_suggestion, selected_item)  # LLM
7. return session                                         # error is None on full success
```

A diagram of the same flow lives in `planning.md` under **Architecture**.

---

## State Management

There is exactly **one source of truth per interaction**: a `session` dict
created by `_new_session(query, wardrobe)`. Every step reads fields written by
earlier steps and writes its own — no globals, no hidden state, nothing passed
implicitly. This makes the data flow auditable and the loop trivial to test
(you can assert on any field after a run).

| Field | Type | Written by | Read by |
|-------|------|-----------|---------|
| `query` | `str` | session init | parse step |
| `parsed` | `dict` | parse step | `search_listings` |
| `search_results` | `list[dict]` | `search_listings` | selection branch |
| `selected_item` | `dict \| None` | selection (`results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `dict` | session init | `suggest_outfit` |
| `outfit_suggestion` | `str \| None` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `str \| None` | `create_fit_card` | the UI |
| `error` | `str \| None` | the no-results branch only | the UI (checked first) |

Data flows in one direction:

```
search_results → selected_item
selected_item + wardrobe → outfit_suggestion
outfit_suggestion + selected_item → fit_card
```

Setting `error` short-circuits the chain and leaves `outfit_suggestion` and
`fit_card` as `None`. The UI (`handle_query` in `app.py`) therefore checks
`session["error"]` **first**: if it's set, the message goes in panel 1 and the
other two panels stay empty; otherwise the three result fields map straight to
the three panels.

---

## Error Handling (per tool)

Each tool has a defined failure mode and a graceful response. The principle:
**the only failure that stops the run is "nothing to style."** Everything else
degrades to a usable string so the user always gets *something* back.

| Tool | Failure mode | Response |
|------|-------------|----------|
| `search_listings` | No listing matches the filters | Returns `[]` (never raises). The loop sets `session["error"]` with the exact applied filters and concrete fixes, and skips the downstream tools entirely. |
| `suggest_outfit` | Empty wardrobe | Tool returns **general** styling advice instead of naming pieces the user doesn't own — never an empty string. The loop proceeds normally. |
| `suggest_outfit` | LLM call raises / returns blank | Caught; returns `"Couldn't generate a styling suggestion right now — try this piece with neutral basics and your go-to shoes."` The run continues. |
| `create_fit_card` | `outfit` is empty/whitespace | Returns the guard string `"No outfit suggestion was provided, so there's nothing to caption yet."` rather than calling the LLM. |
| `create_fit_card` | LLM call raises / returns blank | Caught; returns a plain fallback caption built from the listing: `"Thrifted: {title} for ${price} on {platform}."` |

### Concrete example from testing

I ran the deliberate no-results query through the agent:

```
query = "designer ballgown size XXS under $5"
```

`_parse_query` produced `{"description": "designer ballgown", "size": "XXS",
"max_price": 5.0}`. `search_listings` applied all three filters, found nothing,
and returned `[]`. The loop took the early-return branch and the UI showed only
panel 1:

> I couldn't find any listings matching 'designer ballgown', size XXS, under $5.
> Try raising your budget above $5, dropping the size filter, or broadening the
> style (e.g. 'graphic tee' instead of 'vintage 2003 tour tee'). I didn't
> generate an outfit or fit card because there was nothing to style.

Panels 2 and 3 stayed empty (`""`), confirming the agent did **not** call
`suggest_outfit` or `create_fit_card` on empty input. This case is also locked
in by `test_search_empty_results` in `tests/test_tools.py`.

---

## Spec Reflection

**What the spec asked for and how this build maps to it.** The spec required a
multi-tool agent with a planning loop, explicit state passing between tools, and
graceful error handling — not just a happy path. FitFindr satisfies this with
three tools chained through one `session` dict, where the chain is gated by a
real decision (search results present or not) rather than blindly calling every
tool in sequence.

**Where I made judgment calls beyond the spec:**

- **Regex parsing instead of an LLM parser.** The spec allowed either. I chose
  deterministic regex for query parsing so the search step is reproducible,
  testable, and free. The trade-off is brittleness on unusual phrasings; I
  mitigated it with the "empty description → use the full query" fallback. A
  documented stretch goal in `planning.md` is to swap in an LLM `parse_query`
  tool.
- **"Top result wins" selection.** The agent always styles `search_results[0]`.
  This keeps the loop single-pass and predictable. A richer version would let
  the user pick from several matches, but that would add UI state the spec
  didn't require.
- **LLM tools never abort the run.** I decided that a styling/caption failure
  should degrade to a fallback string rather than surface an error, because the
  user has already found a real item — losing the caption shouldn't lose the
  result. Only an empty search (genuinely nothing to act on) stops the loop.

**What I'd do with more time:** add the LLM-based `parse_query` tool, support
multi-item selection in the UI, and cache LLM calls so re-running the same query
is instant.

---

## How I Used AI Tools

I used Claude (via Cursor) to generate implementation from the spec and diagram
I wrote in `planning.md`, then verified and corrected the output before trusting
it. Two specific instances:

### Instance 1 — Generating `search_listings`

- **Input I gave it:** the Tool 1 block from `planning.md` (parameter names and
  types, the exact return-dict fields, and the "returns `[]`, never raises"
  contract) plus the `load_listings()` docstring from `utils/data_loader.py`.
- **What it produced:** a pure-Python function that loaded listings, filtered by
  `max_price` and `size`, scored the rest by keyword overlap, and sorted
  descending.
- **What I changed / overrode:** the first draft kept listings with a relevance
  score of `0` (so any item under the price cap came back, even if it matched no
  keywords). That would have let the agent "style" a totally irrelevant item. I
  overrode it to **drop zero-score listings** before sorting. I also tightened
  the size match to a case-insensitive *substring* check so `"M"` correctly
  matches `"S/M"`. I confirmed the fix with the three queries listed in
  `planning.md` and with `test_search_price_filter`.

### Instance 2 — Generating the `run_agent` planning loop

- **Input I gave it:** the **Planning Loop** and **State Management** sections of
  `planning.md`, the **Architecture** ASCII diagram, and the `agent.py` skeleton
  (the `_new_session` helper and the `run_agent` TODO with its numbered steps).
- **What it produced:** a `run_agent` that ran all seven steps and threaded
  state through the `session` dict.
- **What I changed / overrode:** the generated version called `suggest_outfit`
  and `create_fit_card` *unconditionally*, then checked for empty results only
  when formatting the output — which meant it sent an empty/None item into the
  LLM tools on a no-results query. I rewrote it to set `session["error"]` and
  **`return` early** the moment `search_results` is empty, so the downstream
  tools are never reached on bad input. I verified this by running the
  `"designer ballgown size XXS under $5"` query and confirming panels 2 and 3
  came back empty (see the Error Handling example above).

In both cases the AI got the structure right but the *failure-path decisions*
wrong — it optimized for the happy path. Reviewing against my planning doc's
error-handling contract is what caught both.

---

## Project Layout

```
fitfindr/
├── app.py                # Gradio UI + handle_query (maps session → 3 panels)
├── agent.py              # run_agent planning loop, query parsing, session state
├── tools.py              # search_listings, suggest_outfit, create_fit_card
├── planning.md           # the spec/diagram I wrote and fed to the AI tools
├── data/
│   ├── listings.json         # 40 mock secondhand listings
│   └── wardrobe_schema.json  # wardrobe format + example/empty wardrobes
├── utils/
│   └── data_loader.py    # load_listings, get_example_wardrobe, get_empty_wardrobe
├── tests/
│   └── test_tools.py     # tool + loop tests (pure-Python tests need no API key)
└── requirements.txt
```
