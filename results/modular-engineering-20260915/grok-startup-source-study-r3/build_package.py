from pathlib import Path
import hashlib,json,shutil
BASE=Path(r'E:\_ryanDev\AI\research-loop-modular'); WORK=BASE/'work'; OUT=WORK/'grok-startup-source-study-r3'
NOTES=['grok-profile-lifecycle-readonly-r1.md','grok-post-auth-initialize-readonly-r1.md','grok-post-auth-model-state-source-r2.md']
SOURCE=WORK/'grok-headless-initialize-location-r2'/'acp_agent.rs'
COMMIT='bc7f02eddd3d84085849dc19ed216f11c23b0571'
def h(p):
 x=hashlib.sha256();x.update(p.read_bytes());return x.hexdigest()
def main():
 if (OUT/'manifest.json').exists():raise RuntimeError('refuse overwrite package')
 copied=[]
 for name in NOTES:
  s=WORK/name;d=OUT/name;shutil.copyfile(s,d)
  if s.read_bytes()!=d.read_bytes():raise RuntimeError('copy mismatch '+name)
  copied.append({'path':name,'sha256':h(d),'bytes':d.stat().st_size})
 d=OUT/'acp_agent.rs';shutil.copyfile(SOURCE,d)
 if SOURCE.read_bytes()!=d.read_bytes():raise RuntimeError('source copy mismatch')
 sources={'commit':COMMIT,'binary_source_correspondence_established':False,'files':[{'path':'acp_agent.rs','sha256':h(d),'bytes':d.stat().st_size,'url':f'https://raw.githubusercontent.com/xai-org/grok-build/{COMMIT}/crates/codegen/xai-grok-shell/src/agent/mvp_agent/acp_agent.rs'}], 'url_only':[{'path':'chat_modes.rs','url':f'https://raw.githubusercontent.com/xai-org/grok-build/{COMMIT}/crates/codegen/xai-grok-shell/src/agent/chat_modes.rs','observed_lines':'17-24: process_chat_mode_enabled returns false','local_copy_included':False},{'path':'mvp_agent directory listing','url':f'https://api.github.com/repos/xai-org/grok-build/contents/crates/codegen/xai-grok-shell/src/agent/mvp_agent?ref={COMMIT}','status':'HTTP 403 rate-limit; no listing/file retained'}]}
 (OUT/'source-provenance.json').write_text(json.dumps(sources,indent=2,sort_keys=True)+'\n',encoding='utf8')
 readme='''# Grok startup source study r3\n\nThis package is metadata-only and preserves three bounded read-only studies. It contains no auth payload, raw unified log, token, model output, validation data, or credential file.\n\nThe recorded expired/changed-on-disk credential hypothesis is contradicted: recorded profiles were byte-identical and safe retained flags say current, unexpired, and unchanged on disk. The pinned public release chat branch is hard-off. The remaining synchronous `model_state(None)` implementation was not inspected because the authoritative pinned GitHub directory listing returned HTTP 403 and the root GitHub tree response was restricted.\n\nNo cause or repair is demonstrated. Public source/binary correspondence is unestablished. This package made no model call, paid API call, login/Daybreak action, or retry; none is a prerequisite inferred by this evidence.\n'''
 (OUT/'README.md').write_text(readme,encoding='utf8',newline='\n')
 manifest={'schema':'grok-startup-source-study-r3','notes':copied,'source_provenance_sha256':h(OUT/'source-provenance.json'),'readme_sha256':h(OUT/'README.md'),'credential_or_raw_log_payloads_included':False,'self_excluding':True}
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf8')
 print(json.dumps({'manifest_sha256':h(OUT/'manifest.json'),'files':len(copied)+4,'source_sha256':h(d)}))
if __name__=='__main__':main()
