"""Versioned public TRAIN solver port over the native Grok ACP bridge.

This is deliberately independent of ``CodexModelPort``.  Native streams,
reservations and prompts are private; the append-only ledger binds their bytes
and exposes only response records needed by the public benchmark runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from research_loop.modular.contracts import FrozenRecord
from research_loop.modular.grok_acp_transport import MODEL, TRAIN_OPPORTUNITY_CONTRACT, run_native_train
from research_loop.modular.model_port import _validate_schema, _schema_witness
from research_loop.ontology import ContractError, canonical


def _sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()
def _write(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix('.tmp'); temporary.write_text(canonical(value), encoding='utf-8'); os.replace(temporary, path)


class GrokTrainModelPort:
    provider_kind = 'grok-acp-public-train-v1'

    def __init__(self, *, executable: Path | str, work_root: Path, private_home: Path, private_profile: Path,
                 public_cwd: Path, frozen_files: Mapping[str, str], max_calls: int, schemas: Mapping[str, Mapping],
                 slot_output_caps: Mapping[str, int], slot_input_byte_caps: Mapping[str, int],
                 observed_main_token_cap: int, native_invoke: Callable[..., Any] = run_native_train) -> None:
        if (not isinstance(max_calls, int) or max_calls < 1 or not isinstance(observed_main_token_cap, int)
                or observed_main_token_cap < 2 or not isinstance(schemas, Mapping) or not schemas
                or set(schemas) != set(slot_output_caps) or set(schemas) != set(slot_input_byte_caps)):
            raise ContractError('invalid frozen Grok TRAIN port contract')
        for slot, schema in schemas.items():
            if not isinstance(slot, str) or not isinstance(schema, Mapping) or schema.get('type') != 'object':
                raise ContractError('Grok TRAIN schemas must be object slots')
            _validate_schema(schema, _schema_witness(schema))
            if type(slot_output_caps[slot]) is not int or slot_output_caps[slot] < 1 or type(slot_input_byte_caps[slot]) is not int or slot_input_byte_caps[slot] < 1:
                raise ContractError('Grok TRAIN per-slot bounds must be positive integers')
        if any(observed_main_token_cap <= cap for cap in slot_output_caps.values()):
            raise ContractError('observed main token cap must exceed every requested output cap')
        self.executable, self.root = str(Path(executable).resolve()), Path(work_root).resolve()
        self.private_home, self.private_profile, self.public_cwd = map(lambda p: Path(p).resolve(), (private_home, private_profile, public_cwd))
        self.frozen_files = dict(frozen_files); self.max_calls = max_calls; self.schemas = json.loads(canonical(schemas))
        self.slot_output_caps, self.slot_input_byte_caps = dict(slot_output_caps), dict(slot_input_byte_caps)
        self.observed_main_token_cap, self.native_invoke = observed_main_token_cap, native_invoke
        self.model, self.effort = MODEL, 'native_acp'
        self.root.mkdir(parents=True, exist_ok=True); self.calls_root = self.root/'calls'; self.calls_root.mkdir(exist_ok=True)
        self.ledger_path = self.root/'ledger.json'
        config = {'schema':'grok-train-solver-port-v1','provider_kind':self.provider_kind,'model':MODEL,
            'opportunity_contract':TRAIN_OPPORTUNITY_CONTRACT,'included_only':True,'api_key_route_permitted':False,
            'max_calls':max_calls,'schemas':self.schemas,'slot_output_caps':self.slot_output_caps,
            'slot_input_byte_caps':self.slot_input_byte_caps,'observed_main_token_cap':observed_main_token_cap,
            'title_opportunities_per_main':1,'title_usage_and_all_call_totals':'unknown','max_retries':0,
            'executable':self.executable,'executable_sha256':_sha(Path(self.executable).read_bytes()),'frozen_files':self.frozen_files}
        if self.ledger_path.exists():
            self.ledger=json.loads(self.ledger_path.read_text(encoding='utf-8'))
            if self.ledger.get('config') != config or self.ledger.get('usage_incomplete') is not False:
                raise ContractError('existing Grok TRAIN ledger is terminal or has different frozen configuration')
        else:
            self.ledger={'config':config,'calls':[],'tokens':0,'usage_incomplete':False}; _write(self.ledger_path,self.ledger)

    def __call__(self, request: FrozenRecord) -> FrozenRecord:
        if not isinstance(request, FrozenRecord): raise ContractError('Grok TRAIN port accepts frozen requests only')
        body=request.data(); slot=body.get('slot')
        if (set(body) != {'schema','task','lock_digest','objective','slot','instruction','context','module_context','execution_feedback'}
                or body.get('schema') != 'public-model-request-v1' or slot not in self.schemas):
            raise ContractError('unexpected public TRAIN solver request')
        if self.ledger['usage_incomplete'] or len(self.ledger['calls']) >= self.max_calls:
            raise ContractError('Grok TRAIN ledger is closed')
        prompt='Return only JSON conforming to the supplied schema. Tools, browsing, filesystem access, and evaluation material are unavailable.\n'+request.encoded
        raw=prompt.encode('utf-8'); cap=self.slot_input_byte_caps[slot]
        if len(raw)>cap: raise ContractError('public TRAIN prompt exceeds frozen complete input-byte bound')
        number=len(self.ledger['calls'])+1; call_dir=self.calls_root/f'{number:04d}-{slot}'; call_dir.mkdir()
        prompt_path=call_dir/'prompt.private.txt'; schema_path=call_dir/'schema.private.json'
        prompt_path.write_bytes(raw); schema_path.write_bytes(canonical(self.schemas[slot]).encode())
        request_path=call_dir/'request.private.json'; request_path.write_bytes(request.encoded.encode())
        reservation=call_dir/'reservation.private.json'; private=call_dir/'native-private'
        row={'id':number,'slot':slot,'request_sha256':request.content_hash,'prompt_sha256':_sha(raw),
             'schema_sha256':_sha(schema_path.read_bytes()),'status':'reserved','reservation_path':str(reservation),
             'native_private_path':str(private),'main_opportunity':1,'possible_initial_title_opportunity':1}
        self.ledger['calls'].append(row); _write(self.ledger_path,self.ledger)
        try:
            result=self.native_invoke(opportunity_contract=TRAIN_OPPORTUNITY_CONTRACT, executable=self.executable,
                cwd=str(self.public_cwd), private_home=str(self.private_home), private_profile=str(self.private_profile),
                private_dir=str(private), reservation=str(reservation), frozen_files=self.frozen_files, prompt=prompt,
                schema=self.schemas[slot], main_output_cap=self.slot_output_caps[slot],
                observed_main_token_cap=self.observed_main_token_cap, input_byte_cap=cap)
            receipt=result.receipt.data(); response=result.response
            receipt_path=call_dir/'observer-receipt.private.json'; receipt_path.write_bytes(result.receipt.encoded.encode())
            binding=receipt.get('public_train_binding')
            billing=receipt.get('billing_before')
            valid = (receipt.get('schema') == 'grok-native-acp-public-train-receipt-v1'
                and receipt.get('accepted') is True and receipt.get('requested_model') == MODEL
                and receipt.get('opportunity_contract') == TRAIN_OPPORTUNITY_CONTRACT
                and receipt.get('runtime_empty_inventory_count', 0) >= 1
                and isinstance(billing, Mapping) and billing.get('route') == 'grok_com_unified_subscription'
                and billing.get('on_demand_cap') == billing.get('on_demand_used') == billing.get('prepaid_balance') == 0
                and billing.get('auto_topup_rule_present') is False and isinstance(binding, Mapping)
                and binding.get('prompt_sha256') == _sha(raw) and binding.get('schema_sha256') == _sha(schema_path.read_bytes())
                and binding.get('source_manifest_sha256') == _sha(canonical(self.frozen_files).encode())
                and binding.get('input_byte_cap') == cap and binding.get('observed_main_token_cap') == self.observed_main_token_cap)
            row.update(native_receipt_sha256=_sha(receipt_path.read_bytes()), reservation_sha256=_sha(reservation.read_bytes()) if reservation.exists() else None,
                       response_sha256=response.content_hash if response else None, known_main_usage=receipt.get('known_usage'),
                       accepted=receipt.get('accepted') is True)
            usage=receipt.get('known_usage')
            if not valid or not response or not isinstance(usage, Mapping) or type(usage.get('totalTokens')) is not int or binding.get('response_sha256') != response.content_hash:
                raise ContractError('native main dispatch or usage is unknown; ledger closed')
            self.ledger['tokens'] += usage['totalTokens']; _validate_schema(self.schemas[slot], response.data())
            (call_dir/'response.private.json').write_bytes(response.encoded.encode())
            row['status']='succeeded'; _write(self.ledger_path,self.ledger); return response
        except Exception as exc:
            row.update(status='unknown_or_failed', error_type=type(exc).__name__); self.ledger['usage_incomplete']=True
            _write(self.ledger_path,self.ledger); raise ContractError('Grok native request is terminal; do not retry') from exc


def replay_grok_train_ledger(port: GrokTrainModelPort) -> None:
    """Recheck original private input and native receipt/reservation byte bindings."""
    if not isinstance(port, GrokTrainModelPort): raise ContractError('typed Grok TRAIN ledger required')
    ledger=json.loads(port.ledger_path.read_text(encoding='utf-8'))
    if ledger != port.ledger or ledger.get('config') != port.ledger.get('config'):
        raise ContractError('on-disk Grok ledger drifted')
    if _sha(Path(port.executable).read_bytes()) != ledger['config'].get('executable_sha256'):
        raise ContractError('native executable source drifted')
    for path, expected in ledger['config']['frozen_files'].items():
        if _sha(Path(path).read_bytes()) != expected:
            raise ContractError('native frozen source drifted')
    identities=set()
    for row in ledger['calls']:
        call=port.calls_root/f"{row['id']:04d}-{row['slot']}"
        if _sha((call/'prompt.private.txt').read_bytes()) != row['prompt_sha256'] or _sha((call/'schema.private.json').read_bytes()) != row['schema_sha256']:
            raise ContractError('original native request replay failed')
        if row['status']=='succeeded':
            if _sha((call/'observer-receipt.private.json').read_bytes()) != row['native_receipt_sha256'] or _sha(Path(row['reservation_path']).read_bytes()) != row['reservation_sha256']:
                raise ContractError('native receipt or reservation replay failed')
            receipt=json.loads((call/'observer-receipt.private.json').read_text(encoding='utf-8'))
            native=Path(row['native_private_path'])
            native_observer=json.loads((native/'observer-receipt.json').read_text(encoding='utf-8'))
            binding=receipt.get('public_train_binding', {})
            identity=(receipt.get('session_id'), receipt.get('prompt_id'))
            if identity in identities or not all(isinstance(x,str) and x for x in identity):
                raise ContractError('duplicate or missing native session/prompt identity')
            identities.add(identity)
            if (receipt.get('accepted') is not True or receipt.get('requested_model') != MODEL
                    or native_observer != receipt
                    or receipt.get('private_stream_sha256') != _sha((native/'stdout.private.jsonl').read_bytes())
                    or binding.get('response_sha256') != row['response_sha256']
                    or _sha((call/'request.private.json').read_bytes()) != row['request_sha256']
                    or _sha((call/'response.private.json').read_bytes()) != row['response_sha256']):
                raise ContractError('native public TRAIN binding replay failed')
