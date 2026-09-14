"""Synthetic headless child process. Does not contact a service."""
import json
from pathlib import Path
import sys

if sys.argv[1]=='inspect':
    print(json.dumps({**{k:[] for k in ('skills','hooks','plugins','mcpServers','projectInstructions')},
        'loginPolicy':{'apiKeyAuthDisabled':True},'workflowGuide':None,'memoryDigest':None}))
else:
    session,answer_path=sys.argv[1:3]
    answer=json.loads(Path(answer_path).read_bytes())
    usage={'input_tokens':8,'cache_read_input_tokens':0,'cache_creation_input_tokens':0,
        'output_tokens':2,'reasoning_tokens':0}
    frames=[{'type':'available_commands','tools':[],'commands':[]}]*3
    frames += [{'type':'text','data':json.dumps(answer)},
        {'type':'usage','usage':usage,'signature':'synthetic'},
        {'type':'end','stopReason':'end_turn','sessionId':session,'requestId':'synthetic-'+session,
            'usage':usage|{'total_tokens':10},'num_turns':1,
            'modelUsage':{'grok-4.6':{'inputTokens':8,'outputTokens':2,'cacheReadInputTokens':0,
                'cacheCreationInputTokens':0,'modelCalls':1}},'structuredOutput':answer}]
    for frame in frames:print(json.dumps(frame),flush=True)
