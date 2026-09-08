# Importing the demo workflow into n8n

## Prerequisites

- Ariadne running at `http://localhost:8000` with `UPSTREAM_MCP_URL` set to
  `http://localhost:8001/mcp` (the demo tool server).
- The demo tool server running: `uvicorn demo.tool_server.server:app --port 8001`.
- An Ariadne API key (see `scripts/provision_api_key.py` in the repo root, or
  the value already in your `.env`'s `ARIADNE_API_KEYS`).
- An Anthropic API key.

## Import steps

1. Open n8n (`http://localhost:5678`).
2. Menu -> **Import from File** -> select `demo/n8n/workflow.json`.
3. Open the **Anthropic Chat Model** node. Create/select an Anthropic
   credential with your `ANTHROPIC_API_KEY`.
4. Open the **Ariadne MCP** node (the MCP Client Tool). Create a **Header
   Auth** credential:
   - Name: `Ariadne API Key`
   - Header name: `X-Api-Key`
   - Header value: your Ariadne API key
   Assign it to the node.
5. Confirm the **Ariadne MCP** node's endpoint URL is `http://localhost:8000/mcp`
   (already set in the imported JSON) -- change it if Ariadne runs elsewhere.
6. Save the workflow.
7. Click **Execute workflow** (the Manual Trigger) to run it, or configure a
   webhook/trigger of your choice for `demo/scripts/run_demo.py` to call
   non-interactively (pass its path via `--n8n-webhook`).

## Known caveat: MCP transport compatibility

n8n's MCP Client Tool node speaks the standard MCP **streamable-HTTP**
transport, which includes session-id negotiation and specific response-status
conventions beyond plain JSON-RPC request/response. Ariadne's proxy
(`ariadne/proxy/mcp_proxy.py`) implements the core JSON-RPC methods
(`initialize`, `tools/list`, `tools/call`) the same way its own test scripts
(`scripts/ariadne_agent.py`, `scripts/mock_upstream_server.py`) exercise it,
but has not been verified against every edge case of n8n's streamable-HTTP
client implementation. If the AI Agent node's tool calls fail to connect:

- Try `serverTransport: sse` instead of `httpStreamable` on the Ariadne MCP
  node, and confirm you can reach `GET http://localhost:8000/mcp` (Ariadne
  does not currently implement a session-negotiation SSE endpoint separate
  from `/mcp` -- this may need a small addition to `mcp_proxy.py` depending
  on what n8n's client requires at connect time).
- As a fallback that exercises Ariadne's real pipeline without depending on
  n8n's MCP transport at all, run `python demo/scripts/run_demo.py --direct`,
  which plays the same tool-call sequence straight through Ariadne's `/mcp`
  JSON-RPC endpoint exactly as `scripts/ariadne_agent.py` does. This still
  proves the same result (real drift scoring, real BLOCK, real 0-calls-reached
  upstream) -- it only skips n8n's own AI Agent loop for picking which tools
  to call.
