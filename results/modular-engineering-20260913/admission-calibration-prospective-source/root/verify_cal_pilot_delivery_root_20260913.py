from pathlib import Path
from collections import Counter
from xml.etree import ElementTree as ET
import hashlib,json,subprocess

base=Path('E:/_ryanDev/AI/research-loop-modular');tree=base/'cal-pilot';w=base/'work/cal-pilot-checks'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
canonical=lambda v:json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'))
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=tree,text=True).strip()=='4cbfe2c269f631d43ff7b42b74edc5283909dbad'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=tree)
delivery=json.loads((w/'delivery-manifest-r2.json').read_text())
assert sha(w/'delivery-manifest-r2.json')=='a176f8200ff72282fdddbdefe92c537da77f877e72094514ef0192d057ef63e9'
for row in delivery['files']:
    assert sha(row['path'])==row['sha256'] and Path(row['path']).stat().st_size==row['size_bytes']
before=json.loads((w/'source-before-final-r2.json').read_text())
after=json.loads((w/'source-after-final-r2.json').read_text())
assert before['files']==after['files'] and after['changed_files']==[] and len(after['files'])==459
assert all(sha(tree/row['path'])==row['sha256'] for row in after['files'])
verification=json.loads((tree/'docs/calibration-pilot-verification.json').read_text())
for row in verification['tests']:
    suite=ET.parse(row['path']).getroot().find('testsuite')
    assert sha(row['path'])==row['sha256']
    assert all(int(suite.attrib[k])==row[k] for k in ('tests','failures','errors','skipped'))
denom=json.loads((w/'synthetic-denominators-r2.json').read_text());all_calls=Counter()
for row in denom['journals']:
    assert sha(row['path'])==row['sha256']
    previous='0'*64;events=Counter();calls=Counter()
    for n,line in enumerate(Path(row['path']).read_bytes().splitlines()):
        entry=json.loads(line);h=entry.pop('digest')
        assert entry['sequence']==n and entry['previous']==previous
        assert hashlib.sha256(canonical(entry).encode()).hexdigest()==h
        previous=h;events[entry['event']]+=1
        if entry['event']=='port_reserved':calls[entry['data']['role']]+=1
    assert previous==row['last_chain_digest'] and dict(events)==row['events'] and dict(calls)==row['reserved_port_attempts']
    all_calls.update(calls)
assert dict(all_calls)==denom['reserved_port_attempts']
result={'source_commit':after['commit'],'unchanged_python_files':459,'verified_artifacts':len(delivery['files']),
        'verified_reports':len(verification['tests']),'synthetic_journals':len(denom['journals']),
        'synthetic_port_reservations':dict(all_calls),'new_paid_calls':0,'actual_reference_payloads_read':0,
        'validation_payloads_read':0,'scientific_calibration':False}
out=base/'work/cal-pilot-delivery-root-verification-r1.json';assert not out.exists()
out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(result))
