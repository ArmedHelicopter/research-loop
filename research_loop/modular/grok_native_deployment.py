"""Explicit isolated 1.0.30 deployment; legacy 1.0.13 remains the default.

The SHA is a local identity pin of the official download, not a reproducible
build attestation. No arbitrary executable, hash or command contract is admitted.
"""
from dataclasses import dataclass
import hashlib
from pathlib import Path

from research_loop.modular.contracts import FrozenRecord
from research_loop.ontology import ContractError

GROK_130_SHA256 = 'ca24ea63272ba7881261f4a52498d1f5bd884b01da25845990422a10dd315266'


@dataclass(frozen=True)
class FrozenNativeDeployment:
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord:
            raise ContractError('exact native deployment record required')
        body = self.record.data()
        executable = body.get('executable')
        if (not isinstance(executable, str) or not Path(executable).is_absolute()
                or str(Path(executable).resolve()) != executable
                or body != self._body(executable)):
            raise ContractError('native deployment is outside the closed 1.0.30 contract')

    @staticmethod
    def _body(executable):
        return {'schema': 'isolated-grok-native-deployment-v1', 'cli_version': '1.0.30',
                'build': '04b7ffed98c6', 'executable': executable,
                'executable_sha256': GROK_130_SHA256,
                'argv': ['{executable}', '--cwd', '{cwd}', 'agent', 'stdio'],
                'environment': {'GROK_DISABLE_AUTOUPDATER': '1'},
                'binary_source_equivalence_verified': False}

    @classmethod
    def create(cls, executable):
        return cls(FrozenRecord.from_dict(cls._body(str(Path(executable).resolve()))))

    @property
    def digest(self):
        return self.record.content_hash

    @property
    def executable(self):
        return self.record.data()['executable']

    def verify_executable(self, executable):
        self.__post_init__()
        path = Path(executable).resolve()
        if str(path) != self.executable or hashlib.sha256(path.read_bytes()).hexdigest() != GROK_130_SHA256:
            raise ContractError('isolated native executable differs')

    def command(self, cwd):
        return [self.executable, '--cwd', str(Path(cwd).resolve()), 'agent', 'stdio']

    def source_pins(self):
        from research_loop.modular import grok_acp_transport
        return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (Path(__file__), Path(grok_acp_transport.__file__))}


def checked_deployment(value):
    if type(value) is not FrozenNativeDeployment:
        raise ContractError('exact closed native deployment required')
    value.__post_init__()
    return value


def diagnostic_receipt_schema(deployment):
    if deployment is None:
        return 'grok-native-acp-diagnostic-receipt-v1'
    checked_deployment(deployment)
    return 'grok-native-acp-diagnostic-receipt-v2'
