"""Synthetic streaming-json peer; it never reaches a provider."""
import json
import sys

session = sys.argv[1]
answer = {"ok": True}
rows = [
    {"type": "available_commands", "tools": [], "commands": []},
    {"type": "available_commands", "tools": [], "commands": []},
    {"type": "available_commands", "tools": [], "commands": []},
    {"type": "text", "data": json.dumps(answer)},
    {"type": "usage", "usage": {"input_tokens": 8, "cache_read_input_tokens": 0,
     "cache_creation_input_tokens": 0, "output_tokens": 2, "reasoning_tokens": 0}, "signature": "synthetic"},
    {"type": "end", "stopReason": "end_turn", "sessionId": session, "requestId": "synthetic-request",
     "usage": {"input_tokens": 8, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
     "output_tokens": 2, "reasoning_tokens": 0, "total_tokens": 10}, "num_turns": 1,
     "modelUsage": {"grok-4.6": {"inputTokens": 8, "outputTokens": 2, "cacheReadInputTokens": 0,
     "cacheCreationInputTokens": 0, "modelCalls": 1}}, "structuredOutput": answer},
]
for row in rows:
    print(json.dumps(row), flush=True)
