# Phase 3 Learning Plan — Agent Graph

Phase 2 gave you a working knowledge base: wiki pages scraped, chunked, embedded, and stored in pgvector with a retriever that can find relevant chunks for any query. Phase 3 is where those retrieval results become useful — a multi-agent system that classifies what a player is actually asking for, routes to the right specialist, fetches relevant knowledge, and synthesises a final answer.

The goal is not just to end up with a working graph. The goal is to understand *how LangGraph coordinates state between agents*, so you can reason about any multi-agent system, not just this one.

Each step has: a concept to understand first, a task to implement, and a verification step. Don't skip ahead — each step produces something the next step needs.

---

## Naming update (read this first)

This plan was written with generic role names (`supervisor`, `build_creation`,
`stat_prioritisation`, `item_loot`, `boss_optimisation`, `combat_execution`,
`status_effect`). The actual prompt layer (Steps 2–3) was implemented with
persona-driven names instead, and an onboarding agent was added that wasn't in the
original plan at all. Every step below still describes the right *concept* — wherever
you read one of the old names, substitute using this table:

| Old generic name (this plan) | Actual persona / file | Routing key (`next_agent` / `calling_agent`) |
|---|---|---|
| `supervisor` | Guidance of Grace — `app/prompts/guidance_of_grace.py` | `guidance_of_grace` |
| *(not in original plan)* | Maiden Melina (onboarding) — `app/prompts/maiden_melina.py` | `melina_onboarding` |
| `build_creation` | Master Hewg — `app/prompts/master_hewg.py` | `master_hewg_build` |
| `stat_prioritisation` | Queen Rennala — `app/prompts/queen_rennala.py` | `rennala_stats` |
| `item_loot` | Merchant Kalé — `app/prompts/merchant_kale.py` | `kale_loot_routes` |
| `combat_execution` | Iron Fist Alexander — `app/prompts/iron_fist_alexander.py` | `alexander_combat` |
| `boss_optimisation` **and** `status_effect` (merged into one agent) | Sir Gideon Ofnir — `app/prompts/sir_gideon_ofnir.py` | `gideon_all_knowing` |

Two structural differences from the original plan to keep in mind for Steps 4–11:
1. **Only 5 specialists, not 6.** `boss_optimisation` and `status_effect` were merged
   into a single Gideon agent rather than kept separate — one fewer node, one fewer
   `ENTITY_TYPE_MAP` entry, one fewer edge to wire.
2. **Melina (onboarding) is not a specialist.** She never touches RAG — she runs, then
   returns straight to the supervisor. Steps 8–9's "every specialist round-trips through
   RAG" logic does not apply to her; she needs her own unconditional edge back to
   `guidance_of_grace`, wired separately from `route_from_specialist`.

---

## The map

```
Step 1 → Understand BuildState and LangGraph fundamentals
Step 2 → Prompt templates (supervisor + RAG agent)                    [DONE — see naming update above]
Step 3 → Prompt templates (5 specialists + onboarding)                [DONE — see naming update above]
Step 4 → SupervisorAgent       (intent classification + final synthesis) — guidance_of_grace_node
Step 4b → OnboardingAgent      (profile interview, gates access)         — melina_onboarding_node
Step 5 → RAGAgent              (query rewrite → retrieve → rerank → format context)
Step 6 → One specialist agent  (master_hewg_build as the pattern)
Step 7 → Remaining 4 specialist agents
Step 8 → Edge conditions       (route_from_supervisor, route_from_specialist)
Step 9 → Graph assembly        (builder.py — wire all nodes and edges)
Step 10 → GraphRunner          (async invocation wrapper)
Step 11 → Integration test     (one full query end-to-end)
```

---

## Step 1 — Understand BuildState and LangGraph fundamentals

### Understand first

Before writing a single line of agent code, read `app/graph/state.py` in full and understand what it is.

`BuildState` is a `TypedDict`. It's not a class you instantiate — it's a schema that describes the shape of the dict that flows through every node in the graph. Every node receives the full state and returns a *partial* dict. LangGraph merges that partial return into the shared state before calling the next node.

Answer these questions before moving on:

- What is the difference between a `TypedDict` and a regular Python `dict`?
- Why does `messages` use `Annotated[list[BaseMessage], add_messages]` instead of just `list[BaseMessage]`? What would break if you used a plain list?
- The `intent_queue` field is a `list[str]`. The supervisor pushes intents onto it and pops one per turn. What problem does this solve that a single `next_agent: str` field could not?
- The `rag_context` field is `Optional[str]`. When is it `None`? When is it populated? What does it contain?
- `calling_agent` is a `str`. What does it hold and why do we need it? (Hint: look at the routing diagram in `implementation_plan.md`.)

**Key LangGraph insight:** a node function has this shape:
```python
async def my_node(state: BuildState) -> dict:
    # read anything from state
    # do work
    return {"field_to_update": new_value}  # only return what changed
```

LangGraph calls `my_node(state)`, takes the returned dict, and merges it into the current state. You never pass state between nodes yourself — the graph does that. This is fundamentally different from calling functions directly.

**The `add_messages` reducer:** for the `messages` field, LangGraph uses `add_messages` as a reducer instead of plain replacement. Without it, every node that returns `{"messages": [...]}` would overwrite the entire conversation history. With `add_messages`, LangGraph *appends* to the existing list instead. Every other field just replaces.

### No implementation in this step

Just read, understand, and answer the questions above. You'll refer back to BuildState constantly in steps 4–9.

### Verify

Without looking at any code, draw the state dict on paper after the supervisor runs for the first time on the query `"help me build a bleed character"`. What fields are populated? What fields are still `None` or empty?

---

## Step 2 — Prompt templates (supervisor + RAG agent) [DONE]

### Understand first

Prompt templates are just strings with `{placeholder}` slots. They live in `app/prompts/` as constants so that:
1. Agent code stays clean — no multi-line strings mixed with logic.
2. Prompts can be read, edited, and tested independently of the agent code.
3. You can swap prompts without touching agent logic.

Each agent needs at minimum a system prompt. Some need a human/user prompt template too.

**Structured JSON output from LLMs:** the supervisor needs to return structured data (intent list, next_agent, optional final response) rather than free text. The standard approach for Claude: tell it in the system prompt to respond with JSON only, give it a schema example, and then use `json.loads()` on the response. For robustness, strip markdown fences if Claude wraps the JSON in ` ```json ``` `.

Look at `implementation_plan.md` section 5 for the full prompt content — your job is not to write the prompt content from scratch, it's to understand *why* each section exists.

Answer these before implementing:
- The supervisor prompt includes a `{build_state_summary}` placeholder. What would you put in this summary? Why not pass the full `BuildState` JSON?
- The RAG agent prompt says "Do not hallucinate facts not present in the chunks." Why is this instruction necessary here even though specialist agents also have this instruction?
- Why does the supervisor prompt say "Respond with valid JSON only"? What breaks if it doesn't?

### Implement

Already created (persona names, not the generic names originally planned):

```
app/prompts/guidance_of_grace.py    — GUIDANCE_OF_GRACE (single constant, no separate _HUMAN template)
app/prompts/maiden_melina.py        — MAIDEN_MELINA (onboarding — not in the original plan)
app/prompts/rag_agent.py            — RAG_CONTEXT_TEMPLATE (unchanged — no LLM call, so no persona)
```

See `implementation_plan.md` section 5 for the current mapping of every routing key to its file and constant name.

Things to figure out:
- Python f-strings don't work for templates you fill in later. Use `str.format(**kwargs)` at call time, or keep them as plain strings with `{placeholder}` syntax and call `.format()` in the agent.
- The supervisor JSON schema has a `final_response` field that is `null` when there are more intents to process and a full string when the supervisor is synthesising. Make sure the schema example in the prompt reflects both cases.

### Verify

In a Python REPL, import your prompt constants and call `.format()` on them with fake values. Confirm the output looks like a real prompt with all placeholders filled.

---

## Step 3 — Prompt templates (specialist agents) [DONE]

### Understand first

All 5 specialists share the same structural pattern:
1. Here is the current build state.
2. Here is the retrieved context from the knowledge base.
3. Here is what you specialise in.
4. Produce your response + a `state_updates` JSON block (where applicable).

The `state_updates` block is how specialists communicate build changes back through the graph. The agent node parses this block and includes the updates in its returned state dict.

Read the actual specialist prompts (persona names — see the naming update table above). Notice that:
- Master Hewg (`MASTER_HEWG`) returns `player_class`, `weapons`, `talismans`, `playstyle`
- Queen Rennala (`QUEEN_RENNALA`) uses the soft-cap reference embedded directly in her system prompt and returns updated `stats`
- Merchant Kalé, Iron Fist Alexander, and Sir Gideon Ofnir do not return `state_updates` — they're advisory, not build-modifying

This matters because: specialist agents that modify the build return parsed state updates; those that don't return `None` or an empty dict for those fields.

### Implement

Already created (persona names, not the generic names originally planned):
```
app/prompts/master_hewg.py
app/prompts/queen_rennala.py
app/prompts/merchant_kale.py
app/prompts/sir_gideon_ofnir.py    (covers boss_optimisation + status_effect)
app/prompts/iron_fist_alexander.py
```

Each has a persona-named constant (`MASTER_HEWG`, `QUEEN_RENNALA`, etc.) instead of a `*_SYSTEM` suffix. Functionally equivalent — just check the constant name in each file before importing it in Step 6–7.

### Verify

For each prompt, ask yourself: if an LLM followed these instructions exactly, would I get back something I can parse? If the answer is "maybe", the instruction is too vague — tighten it.

---

## Step 4 — SupervisorAgent, "Guidance of Grace" (`app/agents/guidance_of_grace.py`)

### Understand first

The supervisor runs *twice* per intent, plus it now has a third responsibility: gating
on onboarding.

0. **Onboarding gate (checked before anything else):** if `state["onboarding_completed"]`
   is `false`, skip classification entirely and set `next_agent = "melina_onboarding"`.
1. **First call (onboarding already done):** classify the query, populate `intent` and `intent_queue`, set `next_agent` to the first specialist.
2. **Subsequent calls (after each specialist returns):** pop the next intent from `intent_queue`, set `next_agent` to that specialist. If the queue is empty, synthesise a final answer from `agent_responses` and set `next_agent` to `"END"`.

How does the supervisor know which call it's on? By checking `state["intent_queue"]`:
- If `onboarding_completed` is `false` → gate to `melina_onboarding`, skip everything else.
- If `intent_queue` is empty and `agent_responses` is empty → first call, classify.
- If `intent_queue` is empty but `agent_responses` is not empty → all intents done, synthesise.
- If `intent_queue` is not empty → more work to do, pop next intent.

**Calling the LLM:** you'll use the `anthropic` SDK directly (not LangChain). The pattern:

```python
from anthropic import AsyncAnthropic
from app.prompts.guidance_of_grace import GUIDANCE_OF_GRACE

client = AsyncAnthropic()
response = await client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    system=GUIDANCE_OF_GRACE.format(build_state_summary=_build_summary(state)),
    messages=[{"role": "user", "content": f"Player Input: {state['player_query']}"}],
)
text = response.content[0].text
```

Note the actual `GUIDANCE_OF_GRACE` prompt is a single constant (no separate `_HUMAN`
template like the original plan sketched) — build the human turn inline as shown above.

Use `claude-haiku-4-5-20251001` for the supervisor — it's fast and cheap for JSON classification. Use `claude-sonnet-4-6` for synthesis (the final answer needs to be high quality).

**Parsing JSON from Claude:** Claude sometimes wraps JSON in markdown code fences. A robust parse:
```python
import json, re

def extract_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    return json.loads(text)
```

### Implement

```python
# app/agents/guidance_of_grace.py

async def guidance_of_grace_node(state: BuildState) -> dict:
    if not state.get("onboarding_completed"):
        return {"next_agent": "melina_onboarding"}
    # Decide which branch we're in (first call / pop next / synthesise)
    # Build the appropriate prompt
    # Call the LLM
    # Parse the JSON response
    # Return the state fields that changed:
    #   - first call: intent, intent_queue, next_agent
    #   - pop next: intent_queue (with first item removed), next_agent
    #   - synthesise: final_response, next_agent = "END"
    ...
```

Things to figure out:
- How do you build the `{build_state_summary}` to inject into the prompt? Write a small helper `_build_summary(state: BuildState) -> str` that formats the relevant fields into a short readable string.
- The `intent_queue` needs to be a copy, not a mutation of the list in state. Why? (Hint: TypedDicts are not immutable — accidentally mutating a list in state between nodes can cause subtle bugs.)
- What should you do if `json.loads()` raises? Log the error and return a safe fallback (e.g., `next_agent = "END"`, `final_response = "I could not process that request."`).

### Verify

Write a small script (not a test file) that:
1. Builds a minimal `BuildState` dict with `onboarding_completed = True` and `player_query = "help me build a bleed arcane character"`
2. Calls `await guidance_of_grace_node(state)`
3. Prints the returned dict

Does it contain `intent`, `intent_queue`, and `next_agent`? Are the intents sensible? (`master_hewg_build`, `rennala_stats` would both be reasonable here.) Then flip `onboarding_completed` to `False` and confirm it short-circuits straight to `next_agent = "melina_onboarding"` without calling the LLM at all.

---

## Step 4b — OnboardingAgent, "Maiden Melina" (`app/agents/maiden_melina.py`)

Not in the original plan — added alongside the persona rename. Same two-phase shape as
a specialist (see Step 6), but simpler: Melina never calls RAG.

```python
# app/agents/maiden_melina.py

async def melina_onboarding_node(state: BuildState) -> dict:
    # Build a prompt from MAIDEN_MELINA.format(build_state_json=...)
    # Call the LLM (claude-sonnet-4-6 — this is a conversational interview, not JSON classification)
    # Check for a <state_updates> block (see Step 6's extract_state_updates helper)
    # If present: merge those fields into state, including onboarding_completed
    # If absent: onboarding is still in progress, just return the conversational text
    # Always return next_agent unset — the unconditional edge back to
    # guidance_of_grace handles routing, not this node
    ...
```

Things to figure out:
- Where does Melina's conversational reply go? It should land in `agent_responses` (or
  directly in `final_response` if you want it surfaced immediately) — since she has no
  RAG round-trip, whatever she says this turn *is* the whole response for this turn.
- What happens if the player answers a question incompletely? The prompt already tells
  her not to emit `<state_updates>` until she has enough info — your node just needs to
  handle "no state_updates block" gracefully (return conversational text, leave
  `onboarding_completed` as `False`).

### Verify

Build a state with `onboarding_completed = False` and a `player_query` like "hi, first time playing". Call `await melina_onboarding_node(state)`. Confirm it returns a conversational response and does *not* set `onboarding_completed = True` on the first turn.

---

## Step 5 — RAGAgent (`app/agents/rag_agent.py`)

### Understand first

The RAG agent is different from the specialist agents. It doesn't generate a final answer — it generates a *context block* that the specialist will use. Its job is:

1. Rewrite the query using `QueryRewriter` (from `app/rag/query_rewriter.py`)
2. For each rewritten variant, call `Retriever.retrieve()` — collect all results
3. Deduplicate results by source URL + chunk_index
4. Pass results through `Reranker.rerank()` to get the top 5
5. Format those 5 chunks into a readable context string
6. Store that string in `state["rag_context"]`

Why run retrieval on all 3 query variants and merge? A single embedding may miss relevant chunks due to vocabulary mismatch. Three variants cast a wider net — the union of their top-20 results is more comprehensive than any single search alone.

**Entity type filtering:** the retriever's `entity_types` argument restricts which rows are searched. Each specialist should only retrieve from its relevant entity types:
- `master_hewg_build` → `["weapon", "stat", "item"]`
- `gideon_all_knowing` → `["boss", "mechanic"]` (covers both boss_optimisation and status_effect now that they're one agent)
- etc.

The RAG node receives `state["calling_agent"]` and uses that to decide which entity types to pass.

**Formatting context:** the output `rag_context` is a plain string that gets injected into the specialist's prompt. Format it as:

```
[1] {page_title} — {section}
{content}
Source: {source_url}

[2] ...
```

The `[N]` tags are what specialists reference when they write `[source_1]` in their response.

### Implement

```python
# app/agents/rag_agent.py

ENTITY_TYPE_MAP = {
    "master_hewg_build": ["weapon", "stat", "item"],
    "rennala_stats": ["stat"],
    "kale_loot_routes": ["item", "weapon"],
    "alexander_combat": ["mechanic", "weapon"],
    "gideon_all_knowing": ["boss", "mechanic"],   # boss_optimisation + status_effect merged
}

async def rag_node(state: BuildState) -> dict:
    # 1. Get the entity types for the calling agent
    # 2. Rewrite the query (state["player_query"] or a more specific sub-query)
    # 3. Retrieve for each variant, merge + deduplicate results
    # 4. Rerank
    # 5. Format rag_context string
    # 6. Return {"rag_context": ..., "rag_results": ...}
    ...
```

Things to figure out:
- `QueryRewriter` and `Retriever` and `Reranker` need to be instantiated. Should you create them inside the node function on every call, or create them once at module level? (Module-level is fine for stateless objects — the cross-encoder model load is expensive and only happens once.)
- `Retriever.__init__` takes a `pool: asyncpg.Pool`. Where does the pool come from inside a node function? You'll need to thread it through state or use a module-level singleton. For now, pass the pool via a closure when you wire the graph in Step 9 — more on that then.
- How do you deduplicate results from 3 retrieval calls? Use a dict keyed by `(source_url, chunk_index)` — if the same chunk appears in multiple retrieval results, keep the one with the higher similarity score.

### Verify

Write a small script that:
1. Creates a pool
2. Builds a minimal state with `player_query = "how do I apply bleed fast"` and `calling_agent = "gideon_all_knowing"`
3. Calls `await rag_node(state)`
4. Prints `state["rag_context"]`

Does the context contain relevant information about hemorrhage/bleed buildup? Are there source citations at the end of each chunk?

---

## Step 6 — One specialist agent (`app/agents/master_hewg.py`)

### Understand first

All 5 specialist agents follow the same pattern. Master it once with Master Hewg (`master_hewg_build`), then repeat for the other four (Rennala, Kalé, Alexander, Gideon).

A specialist runs in two phases per intent:
1. **Phase 1 (no rag_context yet):** the specialist returns immediately with `calling_agent = "master_hewg_build"`. The edge condition sees `rag_context` is empty and routes to the RAG node. The specialist does nothing here — it just signals RAG.
2. **Phase 2 (rag_context populated):** the RAG node has run and `state["rag_context"]` is filled. The specialist now does the real work: build a prompt with the context, call the LLM, parse the response, extract `state_updates`, and return the updated state fields.

How does the specialist know which phase it's in? Check `state.get("rag_context")`:

```python
async def master_hewg_build_node(state: BuildState) -> dict:
    if not state.get("rag_context"):
        # Phase 1: just set calling_agent so the edge knows who to return to
        return {"calling_agent": "master_hewg_build"}
    
    # Phase 2: do the real work
    ...
```

**Parsing `state_updates`:** the specialist prompt tells the LLM to include a `<state_updates>` XML tag with a JSON block inside. Parse it like:

```python
import re, json

def extract_state_updates(text: str) -> dict:
    match = re.search(r"<state_updates>(.*?)</state_updates>", text, re.DOTALL)
    if not match:
        return {}
    return json.loads(match.group(1).strip())
```

Then use those updates to populate the fields you return.

**Clearing rag_context:** after the specialist uses the context, clear it. Otherwise the *next* specialist will skip RAG (because `rag_context` is still populated) and use stale context from the previous specialist. Return `{"rag_context": None, "rag_results": []}` along with your other updates.

### Implement

```python
# app/agents/master_hewg.py

async def master_hewg_build_node(state: BuildState) -> dict:
    if not state.get("rag_context"):
        return {"calling_agent": "master_hewg_build"}
    
    # Build the prompt using MASTER_HEWG
    # Call Claude (claude-sonnet-4-6 — this is the quality output)
    # Parse the response for reasoning + state_updates
    # Store the text response in agent_responses["master_hewg_build"]
    # Parse state_updates and return updated build fields
    # Clear rag_context and rag_results
    ...
```

Things to figure out:
- The prompt needs `{build_state_json}` and `{rag_context}`. Write a helper `_build_state_json(state: BuildState) -> str` that serialises the relevant fields.
- `state_updates` may contain `stats` as a nested dict — convert it to a `BuildStats` instance before returning it.
- What happens if the LLM returns no `<state_updates>` tag? (Bad parse, hallucinated format.) Return the existing build fields unchanged rather than crashing.

### Verify

With a state that has `rag_context` already populated (you can hardcode a fake context string for now), call `await master_hewg_build_node(state)`. Does it return sensible build fields? Does `agent_responses["master_hewg_build"]` contain the LLM's reasoning text?

---

## Step 7 — Remaining 4 specialist agents

### Implement

Create:
```
app/agents/queen_rennala.py
app/agents/merchant_kale.py
app/agents/sir_gideon_ofnir.py     (covers boss_optimisation + status_effect)
app/agents/iron_fist_alexander.py
```

Same pattern as Step 6. The differences are:
- Which prompt constant they use
- Which fields they include in `state_updates` (Kalé, Alexander, and Gideon don't modify build fields — they store their output only in `agent_responses`)
- Which `calling_agent` string they set (`rennala_stats`, `kale_loot_routes`, `gideon_all_knowing`, `alexander_combat`)

Unlike the original plan, the soft-cap reference table for `rennala_stats` isn't a separate importable dict — it's already baked directly into the `QUEEN_RENNALA` prompt string under "GAME MATHEMATICS ENGINES", so there's no `STAT_SOFT_CAPS` constant to import; just format the prompt as-is.

### Verify

Run each agent in isolation with a hardcoded `rag_context`. Check that each stores its output in `agent_responses` under the right key and doesn't accidentally modify fields it shouldn't.

---

## Step 8 — Edge conditions (`app/graph/edges.py`)

### Understand first

LangGraph uses *conditional edges* — after a node runs, a function inspects the state and returns a string that tells the graph which node to call next. This is how routing works.

You need two routing functions, plus one unconditional edge (not a function) for onboarding:

**`route_from_supervisor(state)`** — called after the supervisor runs. Returns the name of the next specialist or `melina_onboarding`, or `"__end__"` to terminate the graph. It reads `state["next_agent"]`.

**`route_from_specialist(state)`** — called after any of the 5 specialists runs. Returns either `"rag"` or `"guidance_of_grace"`. Logic:
- If `rag_context` is empty → the specialist is in Phase 1, route to RAG
- If `rag_context` is populated → the specialist is in Phase 2 (RAG already ran), route back to the supervisor

This is the mechanism that makes the two-phase specialist pattern work. The edge function, not the specialist itself, decides where to go next.

Melina doesn't use this function at all — she gets a plain unconditional `graph.add_edge("melina_onboarding", "guidance_of_grace")` in Step 9, since she never populates `rag_context` and would otherwise incorrectly be routed to RAG by `route_from_specialist`'s logic.

### Implement

```python
# app/graph/edges.py

SPECIALIST_AGENTS = {
    "master_hewg_build", "rennala_stats", "kale_loot_routes",
    "gideon_all_knowing", "alexander_combat",
}
ONBOARDING_AGENT = "melina_onboarding"

def route_from_supervisor(state: BuildState) -> str:
    # Read state["next_agent"]
    # Return the agent name if it's ONBOARDING_AGENT or a valid specialist
    # Return "__end__" otherwise (END is also acceptable — check LangGraph docs)
    ...

def route_from_specialist(state: BuildState) -> str:
    # Return "rag" or "guidance_of_grace" based on whether rag_context is populated
    ...
```

Things to figure out:
- What string does LangGraph expect to signal graph termination? It's `END` imported from `langgraph.graph`, which equals the string `"__end__"`. Either works in the routing dict.
- What happens if `state["next_agent"]` contains a value that isn't in `SPECIALIST_AGENTS`, isn't `ONBOARDING_AGENT`, and isn't `"END"`? Your function should handle that gracefully.

### Verify

Write plain unit tests (no LangGraph, no async) that call these functions with hardcoded state dicts and assert the correct return value. Five cases to cover:
1. Supervisor says `next_agent = "master_hewg_build"` → returns `"master_hewg_build"`
2. Supervisor says `next_agent = "melina_onboarding"` → returns `"melina_onboarding"`
3. Supervisor says `next_agent = "END"` → returns `"__end__"`
4. Specialist has no `rag_context` → returns `"rag"`
5. Specialist has `rag_context` populated → returns `"guidance_of_grace"`

---

## Step 9 — Graph assembly (`app/graph/builder.py`)

### Understand first

`StateGraph` is LangGraph's graph class. You:
1. Instantiate it with your state type: `graph = StateGraph(BuildState)`
2. Add nodes: `graph.add_node("name", function)`
3. Set the entry point: `graph.set_entry_point("guidance_of_grace")`
4. Add edges (unconditional) or conditional edges
5. Compile: `compiled = graph.compile()`

The compiled graph is what you actually run. You call `await compiled.ainvoke(initial_state)` and get back the final state.

**Wiring the RAG node's pool:** `rag_node` needs a `pool` to instantiate the `Retriever`. But node functions must accept only `state` as their argument. The solution: use a closure or a class.

The cleanest approach for learning: create a factory function that takes the pool and returns the node function:

```python
def make_rag_node(pool: asyncpg.Pool):
    retriever = Retriever(pool)
    reranker = Reranker()
    rewriter = QueryRewriter()
    
    async def rag_node(state: BuildState) -> dict:
        # use retriever, reranker, rewriter from closure
        ...
    
    return rag_node
```

Then in `build_graph(pool)`: `graph.add_node("rag", make_rag_node(pool))`

Look at the `implementation_plan.md` section 2 for the full graph wiring — all the `add_conditional_edges` calls are shown there. Your job is to understand what they're doing, not to copy them blindly.

### Implement

```python
# app/graph/builder.py

from langgraph.graph import StateGraph, END

def build_graph(pool: asyncpg.Pool):
    graph = StateGraph(BuildState)
    
    # Add all nodes
    # Set entry point
    # Add conditional edge from supervisor
    # Add conditional edges from each specialist (all use route_from_specialist)
    # Add edge from rag back to the calling_agent
    
    return graph.compile()
```

Things to figure out:
- The RAG node needs to route back to whichever specialist called it. LangGraph's conditional edge takes a function that returns a string. For RAG, that function can be a lambda: `lambda s: s["calling_agent"]`. The routing dict maps each specialist name to itself.
- How do you handle all 5 specialists having the same edge logic without repeating yourself? A loop over the specialist name list works.
- Melina is *not* part of that loop — she gets a single plain `graph.add_edge("melina_onboarding", "guidance_of_grace")` since she never touches RAG. Adding her to the specialist loop by mistake would send her through `route_from_specialist`, which would misinterpret her always-empty `rag_context` as "needs to go to RAG."

### Verify

Instantiate `build_graph(pool)` in a script and call `compiled.get_graph().print_ascii()`. (LangGraph has this built in.) Confirm the graph diagram matches `implementation_plan.md`'s ASCII diagram.

---

## Step 10 — GraphRunner (`app/graph/runner.py`)

### Understand first

The graph runner is a thin wrapper around `compiled.ainvoke()`. Its job is to:
1. Build the initial state dict from the request parameters.
2. Invoke the compiled graph.
3. Extract the fields from the final state that the API needs to return.

This wrapper is why the API layer (Phase 4) doesn't need to know anything about LangGraph — it just calls `await runner.run(...)` and gets back a structured result.

### Implement

```python
# app/graph/runner.py

class GraphRunner:
    def __init__(self, graph, pool: asyncpg.Pool) -> None:
        self._graph = graph
        self._pool = pool

    async def run(
        self,
        session_id: str,
        player_query: str,
        build_state: dict,   # previously persisted build fields
    ) -> dict:
        # 1. Build the initial BuildState dict
        #    Populate: session_id, player_query, messages, agent_responses={},
        #    rag_results=[], intent_queue=[], onboarding_completed and player_profile
        #    (from previously persisted state — defaults to False/empty for a brand-new
        #    session, which is what triggers the melina_onboarding gate on turn one),
        #    and any existing build fields
        # 2. Call await self._graph.ainvoke(initial_state)
        # 3. Extract and return: final_response, agents_used, citations, updated build fields
        ...
```

Things to figure out:
- `agents_used` in the response should be the list of agents that stored a response in `agent_responses`. How do you derive this from the final state?
- Citations come from `final_state["rag_results"]` — but each specialist clears `rag_results` after RAG runs. You'll need to accumulate citations across all RAG calls. One approach: add a `citations: list` field to `BuildState` that each RAG node appends to rather than replaces.

### Verify

Write a script that creates a `GraphRunner`, calls `await runner.run(...)` with a real query, and prints the returned dict. Does `final_response` contain a coherent answer? Does `agents_used` list the agents that actually ran?

---

## Step 11 — Integration test

### Write these tests

**`tests/integration/test_graph.py`:**

```python
async def test_onboarding_gate_blocks_first_query(db_pool):
    # Fresh session, onboarding_completed defaults to False
    # Query: anything, e.g. "what stats should I use"
    # Assert: agents_used == ["melina_onboarding"] (supervisor never classifies real intent)

async def test_single_intent_routing(db_pool):
    # Session with onboarding_completed = True
    # Query that maps to exactly one agent: "what is the poise soft cap"
    # Assert: agents_used == ["rennala_stats"]
    # Assert: final_response is not empty
    # Assert: final_response mentions "poise" or stat-related terms

async def test_multi_intent_routing(db_pool):
    # Session with onboarding_completed = True
    # Query that maps to two agents: "what build should I use against Malenia"
    # Assert: "master_hewg_build" and "gideon_all_knowing" both in agents_used
    # Assert: agents called in sequence (check agent_responses keys)

async def test_rag_context_cleared_between_intents(db_pool):
    # Run a two-intent query (onboarding_completed = True)
    # Assert: the final state has rag_context = None
    # (Proves each specialist got fresh context, not stale from the previous one)
```

**`tests/unit/test_edges.py`:**
```python
def test_route_from_supervisor_to_specialist(): ...
def test_route_from_supervisor_to_onboarding(): ...
def test_route_from_supervisor_to_end(): ...
def test_route_from_specialist_to_rag_when_no_context(): ...
def test_route_from_specialist_to_supervisor_when_context_present(): ...
```

---

## Concept checkpoints

After you finish each group, answer these without looking at code:

**After Steps 1–3:**
- What is the difference between a LangGraph node and a regular Python function?
- Why does `messages` need the `add_messages` reducer but `rag_context` doesn't?
- What would happen if you forgot to return `{"rag_context": None}` from a specialist after it finishes?

**After Steps 4–5:**
- The supervisor runs multiple times per query. How does it know whether to classify, synthesise, or gate to onboarding?
- Why does Melina need her own unconditional edge instead of going through `route_from_specialist` like the other five?
- The RAG node runs retrieval on 3 query variants. Why merge and deduplicate instead of just using the best variant?
- Why does the RAG node produce a formatted string (`rag_context`) rather than returning the raw list of `RagChunk` objects to the specialist?

**After Steps 6–9:**
- A specialist runs twice per intent. What happens on each run and why is this split into two passes?
- `route_from_specialist` is a single function used for all 5 specialists. How does LangGraph know which specialist to return to after RAG runs?
- Why does the RAG node route back to the calling specialist using `lambda s: s["calling_agent"]` instead of hardcoded edges?
- Sir Gideon Ofnir now covers two of the original plan's domains (boss_optimisation and status_effect). What would have to change in `ENTITY_TYPE_MAP` and his prompt if you later wanted to split him back into two separate agents?

**After Steps 10–11:**
- What does `compiled.ainvoke(state)` return? When does it stop?
- Why is `GraphRunner` a separate class rather than just a function?

---

## Order matters

```
BuildState (Step 1, already exists — now includes onboarding_completed, player_profile, current_level)
  ↓
Prompts (Steps 2–3, already exists) → persona files, needed by all agents
  ↓
Supervisor (Step 4) → needs prompts
Onboarding agent (Step 4b) → needs prompts
RAG Agent (Step 5)  → needs retriever, reranker, rewriter
  ↓
Specialists (Steps 6–7) → need prompts + RAG agent
  ↓
Edge functions (Step 8) → need to know specialist names + the onboarding agent name
  ↓
Graph assembly (Step 9) → needs all nodes + edges, including Melina's unconditional edge
  ↓
GraphRunner (Step 10) → needs compiled graph
  ↓
Integration test (Step 11) → needs data in DB from Phase 2 pipeline
```

If you try to run the integration test before running the ingestion pipeline, the RAG node will search an empty database and return no context — the specialists will hallucinate or return empty responses.
