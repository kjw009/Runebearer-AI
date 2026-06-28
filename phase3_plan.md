# Phase 3 Learning Plan — Agent Graph

Phase 2 gave you a working knowledge base: wiki pages scraped, chunked, embedded, and stored in pgvector with a retriever that can find relevant chunks for any query. Phase 3 is where those retrieval results become useful — a multi-agent system that classifies what a player is actually asking for, routes to the right specialist, fetches relevant knowledge, and synthesises a final answer.

The goal is not just to end up with a working graph. The goal is to understand *how LangGraph coordinates state between agents*, so you can reason about any multi-agent system, not just this one.

Each step has: a concept to understand first, a task to implement, and a verification step. Don't skip ahead — each step produces something the next step needs.

---

## The map

```
Step 1 → Understand BuildState and LangGraph fundamentals
Step 2 → Prompt templates (supervisor + RAG agent)
Step 3 → Prompt templates (all 6 specialist agents)
Step 4 → SupervisorAgent       (intent classification + final synthesis)
Step 5 → RAGAgent              (query rewrite → retrieve → rerank → format context)
Step 6 → One specialist agent  (build_creation as the pattern)
Step 7 → Remaining 5 specialist agents
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

## Step 2 — Prompt templates (supervisor + RAG agent)

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

Create the following files. Each file should contain only string constants (no classes, no functions):

```
app/prompts/supervisor.py    — SUPERVISOR_SYSTEM, SUPERVISOR_HUMAN
app/prompts/rag_agent.py     — RAG_SYSTEM
```

Use the prompt content from `implementation_plan.md` section 5 as your starting point, but feel free to adjust the wording — you'll be testing it later and tuning it if needed.

Things to figure out:
- Python f-strings don't work for templates you fill in later. Use `str.format(**kwargs)` at call time, or keep them as plain strings with `{placeholder}` syntax and call `.format()` in the agent.
- The supervisor JSON schema has a `final_response` field that is `null` when there are more intents to process and a full string when the supervisor is synthesising. Make sure the schema example in the prompt reflects both cases.

### Verify

In a Python REPL, import your prompt constants and call `.format()` on them with fake values. Confirm the output looks like a real prompt with all placeholders filled.

---

## Step 3 — Prompt templates (specialist agents)

### Understand first

All 6 specialists share the same structural pattern:
1. Here is the current build state.
2. Here is the retrieved context from the knowledge base.
3. Here is what you specialise in.
4. Produce your response + a `state_updates` JSON block.

The `state_updates` block is how specialists communicate build changes back through the graph. The agent node parses this block and includes the updates in its returned state dict.

Read the specialist prompts in `implementation_plan.md` section 5. Notice that:
- `build_creation` returns `player_class`, `stats`, `weapons`, `talismans`, `spirit_ash`, `playstyle`
- `stat_prioritisation` uses the `STAT_SOFT_CAPS` table you can see in the plan
- `boss_optimisation` does not return `state_updates` — it's advisory, not build-modifying

This matters because: specialist agents that modify the build return parsed state updates; those that don't return `None` or an empty dict for those fields.

### Implement

Create:
```
app/prompts/build_creation.py
app/prompts/stat_prioritisation.py
app/prompts/item_loot.py
app/prompts/boss_optimisation.py
app/prompts/combat_execution.py
app/prompts/status_effect.py
```

Each should have a `*_SYSTEM` constant. Use the content in `implementation_plan.md` section 5, then personalise the output format instructions for what each agent actually returns.

### Verify

For each prompt, ask yourself: if an LLM followed these instructions exactly, would I get back something I can parse? If the answer is "maybe", the instruction is too vague — tighten it.

---

## Step 4 — SupervisorAgent (`app/agents/supervisor.py`)

### Understand first

The supervisor runs *twice* per intent:
1. **First call:** classify the query, populate `intent` and `intent_queue`, set `next_agent` to the first specialist.
2. **Subsequent calls (after each specialist returns):** pop the next intent from `intent_queue`, set `next_agent` to that specialist. If the queue is empty, synthesise a final answer from `agent_responses` and set `next_agent` to `"END"`.

How does the supervisor know which call it's on? By checking `state["intent_queue"]`:
- If `intent_queue` is empty and `agent_responses` is empty → first call, classify.
- If `intent_queue` is empty but `agent_responses` is not empty → all intents done, synthesise.
- If `intent_queue` is not empty → more work to do, pop next intent.

**Calling the LLM:** you'll use the `anthropic` SDK directly (not LangChain). The pattern:

```python
from anthropic import AsyncAnthropic

client = AsyncAnthropic()
response = await client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    system=SUPERVISOR_SYSTEM.format(...),
    messages=[{"role": "user", "content": SUPERVISOR_HUMAN.format(...)}],
)
text = response.content[0].text
```

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
# app/agents/supervisor.py

async def supervisor_node(state: BuildState) -> dict:
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
1. Builds a minimal `BuildState` dict with `player_query = "help me build a bleed arcane character"`
2. Calls `await supervisor_node(state)`
3. Prints the returned dict

Does it contain `intent`, `intent_queue`, and `next_agent`? Are the intents sensible? (`build_creation`, `stat_prioritisation` would both be reasonable here.)

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
- `build_creation` → `["weapon", "stat", "item"]`
- `boss_optimisation` → `["boss", "mechanic"]`
- `status_effect` → `["mechanic", "boss"]`
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
    "build_creation": ["weapon", "stat", "item"],
    "stat_prioritisation": ["stat"],
    "item_loot": ["item", "weapon"],
    "boss_optimisation": ["boss", "mechanic"],
    "combat_execution": ["mechanic", "weapon"],
    "status_effect": ["mechanic", "boss"],
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
2. Builds a minimal state with `player_query = "how do I apply bleed fast"` and `calling_agent = "status_effect"`
3. Calls `await rag_node(state)`
4. Prints `state["rag_context"]`

Does the context contain relevant information about hemorrhage/bleed buildup? Are there source citations at the end of each chunk?

---

## Step 6 — One specialist agent (`app/agents/build_creation.py`)

### Understand first

All 6 specialist agents follow the same pattern. Master it once with `build_creation`, then repeat for the other five.

A specialist runs in two phases per intent:
1. **Phase 1 (no rag_context yet):** the specialist returns immediately with `calling_agent = "build_creation"`. The edge condition sees `rag_context` is empty and routes to the RAG node. The specialist does nothing here — it just signals RAG.
2. **Phase 2 (rag_context populated):** the RAG node has run and `state["rag_context"]` is filled. The specialist now does the real work: build a prompt with the context, call the LLM, parse the response, extract `state_updates`, and return the updated state fields.

How does the specialist know which phase it's in? Check `state.get("rag_context")`:

```python
async def build_creation_node(state: BuildState) -> dict:
    if not state.get("rag_context"):
        # Phase 1: just set calling_agent so the edge knows who to return to
        return {"calling_agent": "build_creation"}
    
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
# app/agents/build_creation.py

async def build_creation_node(state: BuildState) -> dict:
    if not state.get("rag_context"):
        return {"calling_agent": "build_creation"}
    
    # Build the prompt using BUILD_CREATION_SYSTEM
    # Call Claude (claude-sonnet-4-6 — this is the quality output)
    # Parse the response for reasoning + state_updates
    # Store the text response in agent_responses["build_creation"]
    # Parse state_updates and return updated build fields
    # Clear rag_context and rag_results
    ...
```

Things to figure out:
- The prompt needs `{build_state_json}` and `{rag_context}`. Write a helper `_build_state_json(state: BuildState) -> str` that serialises the relevant fields.
- `state_updates` may contain `stats` as a nested dict — convert it to a `BuildStats` instance before returning it.
- What happens if the LLM returns no `<state_updates>` tag? (Bad parse, hallucinated format.) Return the existing build fields unchanged rather than crashing.

### Verify

With a state that has `rag_context` already populated (you can hardcode a fake context string for now), call `await build_creation_node(state)`. Does it return sensible build fields? Does `agent_responses["build_creation"]` contain the LLM's reasoning text?

---

## Step 7 — Remaining 5 specialist agents

### Implement

Create:
```
app/agents/stat_prioritisation.py
app/agents/item_loot.py
app/agents/boss_optimisation.py
app/agents/combat_execution.py
app/agents/status_effect.py
```

Same pattern as Step 6. The differences are:
- Which prompt constant they use
- Which fields they include in `state_updates` (boss/combat/status don't modify build fields — they store their output only in `agent_responses`)
- Which `calling_agent` string they set

`stat_prioritisation` additionally needs to inject the `STAT_SOFT_CAPS` table into the prompt. Define that dict in `app/prompts/stat_prioritisation.py` and format it as a readable table string.

### Verify

Run each agent in isolation with a hardcoded `rag_context`. Check that each stores its output in `agent_responses` under the right key and doesn't accidentally modify fields it shouldn't.

---

## Step 8 — Edge conditions (`app/graph/edges.py`)

### Understand first

LangGraph uses *conditional edges* — after a node runs, a function inspects the state and returns a string that tells the graph which node to call next. This is how routing works.

You need two routing functions:

**`route_from_supervisor(state)`** — called after the supervisor runs. Returns the name of the next specialist, or `"__end__"` to terminate the graph. It reads `state["next_agent"]`.

**`route_from_specialist(state)`** — called after any specialist runs. Returns either `"rag"` or `"supervisor"`. Logic:
- If `rag_context` is empty → the specialist is in Phase 1, route to RAG
- If `rag_context` is populated → the specialist is in Phase 2 (RAG already ran), route back to supervisor

This is the mechanism that makes the two-phase specialist pattern work. The edge function, not the specialist itself, decides where to go next.

### Implement

```python
# app/graph/edges.py

SPECIALIST_AGENTS = {
    "build_creation", "stat_prioritisation", "item_loot",
    "boss_optimisation", "combat_execution", "status_effect",
}

def route_from_supervisor(state: BuildState) -> str:
    # Read state["next_agent"]
    # Return the agent name if it's a valid specialist
    # Return "__end__" otherwise (END is also acceptable — check LangGraph docs)
    ...

def route_from_specialist(state: BuildState) -> str:
    # Return "rag" or "supervisor" based on whether rag_context is populated
    ...
```

Things to figure out:
- What string does LangGraph expect to signal graph termination? It's `END` imported from `langgraph.graph`, which equals the string `"__end__"`. Either works in the routing dict.
- What happens if `state["next_agent"]` contains a value that isn't in `SPECIALIST_AGENTS` and isn't `"END"`? Your function should handle that gracefully.

### Verify

Write plain unit tests (no LangGraph, no async) that call these functions with hardcoded state dicts and assert the correct return value. Four cases to cover:
1. Supervisor says `next_agent = "build_creation"` → returns `"build_creation"`
2. Supervisor says `next_agent = "END"` → returns `"__end__"`
3. Specialist has no `rag_context` → returns `"rag"`
4. Specialist has `rag_context` populated → returns `"supervisor"`

---

## Step 9 — Graph assembly (`app/graph/builder.py`)

### Understand first

`StateGraph` is LangGraph's graph class. You:
1. Instantiate it with your state type: `graph = StateGraph(BuildState)`
2. Add nodes: `graph.add_node("name", function)`
3. Set the entry point: `graph.set_entry_point("supervisor")`
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
- How do you handle all 6 specialists having the same edge logic without repeating yourself? A loop over the specialist name list works.

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
        #    rag_results=[], intent_queue=[], and any existing build fields
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
async def test_single_intent_routing(db_pool):
    # Query that maps to exactly one agent: "what is the poise soft cap"
    # Assert: agents_used == ["stat_prioritisation"]
    # Assert: final_response is not empty
    # Assert: final_response mentions "poise" or stat-related terms

async def test_multi_intent_routing(db_pool):
    # Query that maps to two agents: "what build should I use against Malenia"
    # Assert: "build_creation" and "boss_optimisation" both in agents_used
    # Assert: agents called in sequence (check agent_responses keys)

async def test_rag_context_cleared_between_intents(db_pool):
    # Run a two-intent query
    # Assert: the final state has rag_context = None
    # (Proves each specialist got fresh context, not stale from the previous one)
```

**`tests/unit/test_edges.py`:**
```python
def test_route_from_supervisor_to_specialist(): ...
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
- The supervisor runs multiple times per query. How does it know whether to classify or synthesise?
- The RAG node runs retrieval on 3 query variants. Why merge and deduplicate instead of just using the best variant?
- Why does the RAG node produce a formatted string (`rag_context`) rather than returning the raw list of `RagChunk` objects to the specialist?

**After Steps 6–9:**
- A specialist runs twice per intent. What happens on each run and why is this split into two passes?
- `route_from_specialist` is a single function used for all 6 specialists. How does LangGraph know which specialist to return to after RAG runs?
- Why does the RAG node route back to the calling specialist using `lambda s: s["calling_agent"]` instead of hardcoded edges?

**After Steps 10–11:**
- What does `compiled.ainvoke(state)` return? When does it stop?
- Why is `GraphRunner` a separate class rather than just a function?

---

## Order matters

```
BuildState (Step 1, already exists)
  ↓
Prompts (Steps 2–3) → needed by all agents
  ↓
Supervisor (Step 4) → needs prompts
RAG Agent (Step 5)  → needs retriever, reranker, rewriter
  ↓
Specialists (Steps 6–7) → need prompts + RAG agent
  ↓
Edge functions (Step 8) → need to know specialist names
  ↓
Graph assembly (Step 9) → needs all nodes + edges
  ↓
GraphRunner (Step 10) → needs compiled graph
  ↓
Integration test (Step 11) → needs data in DB from Phase 2 pipeline
```

If you try to run the integration test before running the ingestion pipeline, the RAG node will search an empty database and return no context — the specialists will hallucinate or return empty responses.
