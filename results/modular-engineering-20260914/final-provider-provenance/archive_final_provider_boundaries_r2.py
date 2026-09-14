"""Accept the two explicit imported manifest shapes; preserve the failed builder."""
from pathlib import Path

prior = Path(__file__).with_name('archive_final_provider_boundaries_r1.py')
source = prior.read_text(encoding='utf-8')
source = source.replace("manifest['members']", "(manifest['members'] if 'members' in manifest else manifest['files'])")
source = source.replace("'c4-provider-root-committed-archive-r1.json',", "'archive_final_provider_boundaries_r1.py','final-provider-archive-builder-r1-failure.json','c4-provider-root-committed-archive-r1.json',")
exec(compile(source, str(prior), 'exec'))
