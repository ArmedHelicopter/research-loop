"""Messages-specific signed closure over private raw HTTP evaluator originals."""
from pathlib import Path

from evaluation.modular.messages_evaluator import KIND, MessagesEvaluatorModelPort
from research_loop.modular.anthropic_train_provider import read, record, require, sha
from research_loop.modular.panel_receipts import FrozenPanel, verify_signed
from research_loop.ontology import ContractError

SCHEMA='messages-independent-evaluator-closure-v1'


def finalize(*, service, panel, journal_path, nonce, receipt_digests):
    from evaluation.modular.headless_evaluator_closure import _successful_journal, _panel_scope
    port=getattr(service,'messages_evaluator_port',None)
    require(type(port) is MessagesEvaluatorModelPort and type(nonce) is str and nonce, 'typed Messages evaluator required')
    descriptor={'kind':KIND,'configuration_digest':port._config_record.content_hash}
    require(service.evaluator_provider==descriptor and service.config.record.data()['evaluator_id']==port.evaluator_id
        and service.config.record.data()['version']==port.evaluator_version
        and service.config.record.data()['rubric_digest']==port.rubric_digest,'Messages scorer subject differs')
    port.replay();ledger_before=port.ledger_path.read_bytes();journal_before=Path(journal_path).read_bytes()
    journal=_successful_journal(journal_path);rows=port.ledger['calls'];expected=list(receipt_digests)
    require(not port.ledger['usage_incomplete'] and len(rows)==len(journal)==len(expected),'Messages incomplete scoring denominator')
    cells={c.key:c for c in panel.cells};calls=[]
    receipt_schema='linked-adapted-scored-cell-v1' if type(panel) is FrozenPanel else 'combination-adapted-scored-cell-v1'
    for row,(key,receipt),digest in zip(rows,journal,expected,strict=True):
        signed=verify_signed(receipt,{service._authority.authority_id:service._authority.key},schema=receipt_schema)
        directory=port.calls_root/f'{row["id"]:04d}';request=read(directory/'request.private.json');output=record(read(directory/'response.private.json'))
        evidence=signed.get('evaluator_evidence',{});cell=cells.get(key)
        require(row['status']=='succeeded' and receipt.content_hash==digest and cell is not None
            and signed['panel_digest']==panel.digest and signed['cell_key']==list(key)
            and signed['scorer_digest']==service.config.digest and signed['scorer_config_digest']==service.config.digest
            and signed['benchmark']==cell.identity.benchmark==request['benchmark']==row['benchmark']
            and evidence.get('evaluator_id')==port.evaluator_id and evidence.get('evaluator_version')==port.evaluator_version
            and evidence.get('rubric_digest')==port.rubric_digest and evidence.get('output_digest')==output.content_hash==row['response_digest']
            and all(evidence.get(k)==request[k] for k in ('prompt_digest','schema_digest','reference_digest')),
            'Messages score does not bind original evaluator call')
        calls.append({'id':row['id'],'cell_key':list(key),'benchmark':row['benchmark'],'receipt_digest':digest,
            'request_digest':row['request_digest'],'output_digest':row['response_digest'],
            'originals_digest':record(row['files']).content_hash,'usage':row['usage']})
    scope=_panel_scope(panel,[key for key,_ in journal]);scope['schema']='messages-evaluator-closure-scope-v1'
    body={'schema':SCHEMA,'nonce':nonce,'eligible':True,'panel_digest':panel.digest,'scorer_config_digest':service.config.digest,
        'evaluator_provider':descriptor,'receipt_digests':expected,'calls':calls,'scope':scope,
        'ledger_sha256':sha(ledger_before),'worker_journal_sha256':sha(journal_before),
        'known_reported_tokens':port.ledger['tokens'],'usage_scope':'anthropic_messages_reported',
        'settled_additional_charge_usd':None,'source_files':port.frozen_files}
    port.replay();require(port.ledger_path.read_bytes()==ledger_before and Path(journal_path).read_bytes()==journal_before,
        'Messages originals changed during closure replay')
    return service._authority.issue(body)


def verify_closure(value, *, authority_keys, panel, config, provider, nonce, receipt_digests):
    b=verify_signed(value,authority_keys,schema=SCHEMA);expected=list(receipt_digests)
    fields={'schema','authority','nonce','eligible','panel_digest','scorer_config_digest','evaluator_provider',
        'receipt_digests','calls','scope','ledger_sha256','worker_journal_sha256','known_reported_tokens',
        'usage_scope','settled_additional_charge_usd','source_files'}
    require(set(b)==fields and provider.get('kind')==KIND and b['evaluator_provider']==provider
        and b['nonce']==nonce and b['eligible'] is True and b['panel_digest']==panel.digest
        and b['scorer_config_digest']==config.digest and b['receipt_digests']==expected
        and type(b['calls']) is list and len(b['calls'])==len(expected)
        and b['usage_scope']=='anthropic_messages_reported' and b['settled_additional_charge_usd'] is None,
        'Messages closure subject differs')
    scope=b['scope'];cells={c.key:c for c in panel.cells};scored=[];total=0
    for n,(call,digest) in enumerate(zip(b['calls'],expected,strict=True),1):
        require(set(call)=={'id','cell_key','benchmark','receipt_digest','request_digest','output_digest','originals_digest','usage'}
            and call['id']==n and call['receipt_digest']==digest,'Messages closure order differs')
        key=tuple(call['cell_key']);usage=call['usage']
        require(key in cells and key not in scored and call['benchmark']==cells[key].identity.benchmark,'Messages closure cell differs')
        require(type(usage) is dict and set(usage)=={'input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens','total_tokens','cache_usage_complete'}
            and usage['cache_usage_complete'] is True and all(type(usage[k]) is int and usage[k]>=0 for k in usage if k!='cache_usage_complete')
            and usage['total_tokens']==sum(usage[k] for k in ('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')),
            'Messages closure token arithmetic differs')
        for name in ('request_digest','output_digest','originals_digest'):
            require(type(call[name]) is str and len(call[name])==64 and all(v in '0123456789abcdef' for v in call[name]),'Messages original digest invalid')
        scored.append(key);total+=usage['total_tokens']
    require(scope=={'schema':'messages-evaluator-closure-scope-v1','expected_panel_cell_keys':[list(k) for k in sorted(cells)],
        'scored_cell_keys':[list(k) for k in scored],'unscored_cell_count':len(cells)-len(scored)}
        and b['known_reported_tokens']==total,'Messages full scope or token sum differs')
    for name in ('ledger_sha256','worker_journal_sha256'):
        require(type(b[name]) is str and len(b[name])==64 and all(v in '0123456789abcdef' for v in b[name]),'Messages closure original hash invalid')
    require(type(b['source_files']) is dict and b['source_files'],'Messages source pins absent')
    return record(b)
