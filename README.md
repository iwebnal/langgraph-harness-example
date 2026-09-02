# Release Triage Agent

This is an educational LangGraph agent designed to be wrapped later with harness engineering practices.

The agent receives a software release request, looks up service context, assesses risk, and either drafts a release plan or blocks until human approval is present.

## Why this example works well for learning

- It uses LangGraph's core concepts: state, nodes, edges, conditional routing, and compiled graphs.
- It separates graph orchestration from deterministic policy logic.
- It includes a tool boundary via `lookup_service`.
- It creates an audit trail in state.
- It exposes natural harness points: approval, policy checks, evals, sandboxing, and checkpointing.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python run_demo.py
pytest
```

## Expected behavior

Low-risk notification changes auto-produce a plan.

High-risk billing database changes are blocked unless `approval` is set to `approved`.

## Project layout

```text
src/release_triage_agent/
  graph.py      LangGraph workflow
  policy.py     deterministic risk and routing policy
  state.py      shared state schema
  tools.py      service catalog tool
tests/
  test_policy.py
harness/
  HARNESS_ENGINEERING.md
  eval_cases.jsonl
  policy.yaml
```

## How this maps to LangGraph

LangGraph models workflows as graphs with shared state, nodes, and edges. This example uses `StateGraph` to define the state machine and conditional edges to route high-risk changes through approval.

Official references:

- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://langchain-ai.github.io/langgraph/agents/tools/
- https://docs.langchain.com/oss/python/releases/langgraph-v1

## How this maps to harness engineering

Harness engineering should wrap this agent with controls:

- run it in a sandbox;
- restrict available tools;
- require approval for high-risk actions;
- run eval cases in CI;
- persist audit logs;
- use durable checkpoints for long-running workflows;
- verify generated plans before allowing real actions.
