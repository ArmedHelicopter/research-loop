"""Test-only executable: real subprocess, synthetic authorities and canned ports."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from evaluation.modular.calibration_pilot_process import load_record, serve_once
from evaluation.modular.calibration_pilot import DiagnosticAuthority
from tests.helpers.calibration_pilot_fixture import FixturePorts

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    descriptor = {'path': args.config, 'sha256': args.sha256}
    config = load_record(descriptor).data()
    manifest = load_record(config['manifest'])
    authorities = {role: DiagnosticAuthority(manifest.data()['authorities'][role], Path(desc['path']).read_bytes())
                   for role, desc in config['key_files'].items()}
    ports = FixturePorts(manifest, authorities)
    return serve_once(descriptor, output_path=args.output, **ports.kwargs())

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('{"status":"failed","receipt_sha256":null}')
        raise SystemExit(1)
