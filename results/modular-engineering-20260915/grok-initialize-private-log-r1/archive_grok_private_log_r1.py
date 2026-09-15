import hashlib,importlib.util,json,shutil,zipfile
from pathlib import Path
BASE=Path('E:/_ryanDev/AI/research-loop-modular')
WORK=BASE/'work'; SOURCE=WORK/'grok130-initialize-private-log-r1'
DEST=BASE/'artifact-evidence-provenance/results/modular-engineering-20260915/grok-initialize-private-log-r1'
PRIVATE=BASE/'retained-private-evidence/grok-initialize-private-log-r1'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_bytes())
def stamp(p): return {'sha256':sha(p),'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
def write(p,b):
    with p.open('xb') as out: out.write((json.dumps(b,indent=2)+'\n').encode())
def main():
    assert not DEST.exists() and not PRIVATE.exists()
    joined=read(WORK/'grok130-initialize-private-log-r1-native-join.json')
    started=read(WORK/'grok130-initialize-private-log-r1-native-start.json')
    assert joined['native_session_id']==started['session_id']==59193
    assert 'session_id' not in joined['result'] and joined['result']['exit_code']==0
    closure=read(SOURCE/'closure.json'); result=closure['result']
    assert result['process_tree_closed'] and result['initialize_writes_completed']==1
    assert result['outbound_method_counts']['session/new']==result['outbound_method_counts']['session/prompt']==0
    assert result['faults']==['timeout'] and result['response'] is None
    assert closure['source_unchanged'] and closure['global_auth_metadata_unchanged']
    frozen=read(SOURCE/'envelope.json')['frozen_files']
    assert all(sha(Path(p))==h for p,h in frozen.items())
    helper=WORK/'prepare_headless_lineage_full4_archive_r1.py'
    spec=importlib.util.spec_from_file_location('retention',helper)
    retention=importlib.util.module_from_spec(spec);spec.loader.exec_module(retention)
    originals=sorted(retention.regular_files(SOURCE))
    before={str(p):stamp(p) for p in originals}
    PRIVATE.mkdir(parents=True)
    archive=PRIVATE/'originals-without-credentials.zip'
    rows=retention.add_zip(archive,((p.relative_to(SOURCE).as_posix(),p.read_bytes(),str(p)) for p in originals))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert z.namelist()==[r['path'] for r in rows]
        for row in rows:
            raw=z.read(row['path'])
            assert hashlib.sha256(raw).hexdigest()==row['sha256']==before[row['origin']]['sha256']
    assert before=={str(p):stamp(p) for p in originals}
    DEST.mkdir(parents=True);(DEST/'.gitattributes').write_bytes(b'* -text\n')
    names=['driver.py','init_engine.py','summarize_private_logs.py','summarize_source_bound_phases.py',
        'summarize_span_boundaries.py','launch-reservation.json','envelope.json','help-receipt.json',
        'agent-help.stdout.txt','agent-help.stderr.txt','closure.json','allowlisted-log-summary.json',
        'source-bound-phase-summary.json','span-boundary-summary.json']
    copies=[SOURCE/name for name in names]+[Path(__file__),helper,
        WORK/'grok130-initialize-private-log-r1-native-start.json',
        WORK/'grok130-initialize-private-log-r1-native-join.json',
        WORK/'grok130-initialize-private-log-r1-driver.log',WORK/'prepare_grok_private_log_r1.py']
    for p in copies:
        shutil.copyfile(p,DEST/p.name);assert (DEST/p.name).read_bytes()==p.read_bytes()
    source_rows=[]
    with zipfile.ZipFile(DEST/'frozen-source-python.zip','x',zipfile.ZIP_DEFLATED) as z:
        for name,h in frozen.items():
            p=Path(name)
            if p.suffix!='.py':continue
            raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==h
            z.writestr(p.name,raw);source_rows.append({'member':p.name,'origin':name,'sha256':h,'bytes':len(raw)})
    write(DEST/'source-members.json',{'files':source_rows,'zip_sha256':sha(DEST/'frozen-source-python.zip')})
    write(DEST/'retention-manifest.json',{'schema':'private-log-retention-v1','private_archive':str(archive),
        'archive_sha256':sha(archive),'members':rows,'excluded':retention.EXCLUSIONS,
        'pruned_reparse_paths':sorted(retention.PRUNED_LINKS),'before':before,'after':before})
    (DEST/'README.md').write_text('''# Grok 初始化私有日志诊断

原生工具 session 59193 已 join，驱动退出 0；实际诊断为 60.25 秒内未获得初始化响应，
因此不是启动通过。只发送一次 initialize，session/new、prompt、authenticate 和 billing
RPC 均为零，原进程树已关闭。实际模型用量及结算仍未知，不把驱动退出码解释成成功。

同一固定 1.0.30 二进制 ca24ea63 通过 agent --help 明确支持 --debug 与 --debug-file。
本次保留 66 行、11,385 字节原生 debug 日志；公开目录只含固定词表/公开源码常量匹配，
不公开原始日志或认证内容。初始化记录在 06:21:26.908620Z 包含 model_state；之后模型
目录获取和认证信息补充有完成记录，但无初始化响应。该词出现缩小了源码检查范围，
并不单独证明准确的阻塞点或死锁。公开源码与该二进制的等价性仍未建立。

旧 grok-next-discriminating-diagnostic-r1.md 声称 README 支持 GROK_LOG_FILE/RUST_LOG，
本轮无法从其引用的固定源码确认该依据。首次纯准备在文档字符串断言处失败，未运行
Grok；保留准备脚本，未使用这两个环境变量。改用实际二进制帮助支持的命令行日志选项。
旧报告原件不改写，本说明纠正其依据。新目录路径和运行时刻仍是上下文差异。

原初始化 helper 字节沿用已验证的单写入引擎；实际源码、配置和二进制摘要前后保持一致。
全局认证文件只作不展示内容的复制，元数据不变；调用前后隔离上下文检查通过。
源码副本、工具开始/终态、配置摘要、白名单日志摘要与私有非凭据原件清单一并保留。
这不是 M4/M5 实验重跑、真实模型效果证据或 VAL 验收，也不引入 Daybreak 前置要求。
''',encoding='utf-8')
    manifest={'schema':'published-files-v1','files':[{'path':p.name,'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(DEST.iterdir())]}
    write(DEST/'published-manifest.json',manifest)
    assert read(DEST/'published-manifest.json')==manifest
    for row in manifest['files']:
        p=DEST/row['path'];assert sha(p)==row['sha256'] and p.stat().st_size==row['bytes']
    assert before=={str(p):stamp(p) for p in originals}
    print(json.dumps({'destination':str(DEST),'private_members':len(rows),
        'public_files':len(manifest['files'])+1,'manifest_sha256':sha(DEST/'published-manifest.json'),
        'originals_bytes_mtimes_unchanged':True}))
if __name__=='__main__':main()
