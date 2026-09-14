"""Actual child-process fixture with synthetic references only; no network."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.helpers.material_authoring_fixture import authored_answer

if sys.argv[1] == 'inspect':
    print(json.dumps({**{k: [] for k in ('skills', 'hooks', 'plugins', 'mcpServers', 'projectInstructions')},
        'loginPolicy': {'apiKeyAuthDisabled': True}, 'workflowGuide': None, 'memoryDigest': None}))
else:
    session, prompt_file = sys.argv[1:3]
    prompt = json.loads(Path(prompt_file).read_text(encoding='utf-8'))
    answer = authored_answer(prompt['references']) if 'references' in prompt else {'ok': True}
    usage = {'input_tokens': 8, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0,
        'output_tokens': 2, 'reasoning_tokens': 0}
    rows = [{'type': 'available_commands', 'tools': [], 'commands': []}] * 3
    rows += [{'type': 'text', 'data': json.dumps(answer)},
        {'type': 'usage', 'usage': usage, 'signature': 'synthetic'},
        {'type': 'end', 'stopReason': 'end_turn', 'sessionId': session,
            'requestId': 'synthetic-' + session, 'usage': usage | {'total_tokens': 10},
            'num_turns': 1, 'modelUsage': {'grok-4.6': {'inputTokens': 8, 'outputTokens': 2,
                'cacheReadInputTokens': 0, 'cacheCreationInputTokens': 0, 'modelCalls': 1}},
            'structuredOutput': answer}]
    for row in rows:
        print(json.dumps(row), flush=True)
