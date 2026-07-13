# Change request: OpenAI-compat proxy should drop unsupported request parameters

**Service:** OpenAI-compatible model proxy at `http://10.16.0.34:8018/v1`
**Requested by:** Tristan Doering
**Priority:** blocks an internal agent integration; small, low-risk change
**Date:** 2026-07-10

## Problem

The proxy forwards unknown OpenAI-compat request fields verbatim to the Anthropic
upstream, which rejects them with `invalid_request_error`. Standard OpenAI-compatible
clients and agent frameworks (here: Nous Research hermes-agent, but this affects any
client using reasoning-related OpenAI params) routinely send fields like
`reasoning_effort`, `think`, `reasoning`, or `thinking` that the Anthropic Messages
API does not accept. Every such request fails with HTTP 502/400 even though the
request is otherwise valid.

## Reproduction (verified 2026-07-10)

Baseline works (HTTP 200):

```bash
curl -s http://10.16.0.34:8018/v1/chat/completions \
  -H 'Authorization: Bearer any' -H 'Content-Type: application/json' \
  -d '{"model":"claude-opus-4-8","messages":[{"role":"user","content":"hi"}],"max_tokens":8}'
```

Adding a reasoning param fails:

```bash
# identical request plus "reasoning_effort":"none"  ->
# {"error":{"code":"upstream_error","message":"upstream error: status=400,
#   body={...\"message\":\"reasoning_effort: Extra inputs are not permitted\"...
#   \"request_id\":\"req_011CctP98mm5hThFkCT...\"}"}}

# identical request plus "think":false  ->
# {"error":{...\"message\":\"think: Extra inputs are not permitted\"...
#   \"request_id\":\"req_011CctP9A5PQyJeCaYezWS4A\"}}
```

## Requested change

Silently drop request-body fields that the upstream provider does not support,
instead of forwarding them. Two acceptable implementations, in order of preference:

1. **If the proxy is LiteLLM:** set `litellm_settings: drop_params: true` in the
   proxy config (documented LiteLLM feature for exactly this problem). One line.
2. **If it is custom code:** strip at minimum the keys
   `reasoning_effort`, `think`, `reasoning`, `thinking`, `thinking_config`
   from the JSON body before translating to the Anthropic request — or better,
   whitelist the fields the translator actually maps and drop the rest.

Optionally (nice to have): translate `reasoning_effort` into Anthropic's native
`thinking` budget parameter rather than dropping it, so clients can control
extended thinking. Not required for this request.

## Acceptance criteria

- The two failing curl commands above return HTTP 200 with a normal completion.
- The baseline request and `stream: true` behavior are unchanged.
- No client-visible errors mentioning "Extra inputs are not permitted" for the
  listed keys.
