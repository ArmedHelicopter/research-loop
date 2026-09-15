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
class FrozenHeadlessTrainDeployment:
    """The sole opt-in 1.0.30 normal-CLI TRAIN deployment.

    This is deliberately distinct from :class:`FrozenNativeDeployment`: ACP
    stdio and normal streaming JSON have different command and evidence
    contracts.  Omitting this object preserves the legacy 1.0.13 path.
    """
    record: FrozenRecord

    def __post_init__(self):
        if type(self.record) is not FrozenRecord:
            raise ContractError('exact headless TRAIN deployment record required')
        body = self.record.data(); executable = body.get('executable')
        if (not isinstance(executable, str) or not Path(executable).is_absolute()
                or str(Path(executable).resolve()) != executable
                or body != self._body(executable)):
            raise ContractError('headless TRAIN deployment is outside the closed 1.0.30 contract')

    @staticmethod
    def _body(executable):
        return {'schema': 'grok-headless-train-native-deployment-v1',
                'cli_version': '1.0.30', 'build': '04b7ffed98c6',
                'executable': executable, 'executable_sha256': GROK_130_SHA256,
                'model': 'grok-4.6', 'account_client_version': '1.0.30',
                'command_contract': 'grok-headless-streaming-json-v1',
                'inspect_inventory_contract': 'grok-headless-inspect-empty-v1',
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

    @property
    def account_client_version(self):
        return self.record.data()['account_client_version']

    def verify_executable(self, executable):
        self.__post_init__()
        path = Path(executable).resolve()
        if str(path) != self.executable or hashlib.sha256(path.read_bytes()).hexdigest() != GROK_130_SHA256:
            raise ContractError('headless TRAIN executable differs')

    def source_pins(self):
        from research_loop.modular import grok_cli_protocol, grok_headless_transport
        paths = (Path(__file__), Path(grok_headless_transport.__file__),
                 Path(grok_cli_protocol.__file__))
        return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}


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
                or body not in (self._body(executable), self._body(executable, True))):
            raise ContractError('native deployment is outside the closed 1.0.30 contract')

    @staticmethod
    def _body(executable, skill_isolation=False):
        body = {'schema': 'isolated-grok-native-deployment-v1', 'cli_version': '1.0.30',
                'build': '04b7ffed98c6', 'executable': executable,
                'executable_sha256': GROK_130_SHA256,
                'argv': ['{executable}', '--cwd', '{cwd}', 'agent', 'stdio'],
                'environment': {'GROK_DISABLE_AUTOUPDATER': '1'},
                'binary_source_equivalence_verified': False}
        if skill_isolation:
            body.update(schema='isolated-grok-native-deployment-v2',
                        context_policy='grok130-readiness-context-v1', scope='readiness-only')
        return body

    @classmethod
    def create(cls, executable, *, skill_isolation=False):
        if type(skill_isolation) is not bool:
            raise ContractError('skill isolation selector must be bool')
        return cls(FrozenRecord.from_dict(cls._body(str(Path(executable).resolve()), skill_isolation)))

    @property
    def skill_isolation(self):
        return self.record.data()['schema'] == 'isolated-grok-native-deployment-v2'

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
        paths = [Path(__file__), Path(grok_acp_transport.__file__)]
        if self.skill_isolation:
            from research_loop.modular import grok_skill_isolation
            paths.append(Path(grok_skill_isolation.__file__))
        return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}


def checked_deployment(value):
    if type(value) is not FrozenNativeDeployment:
        raise ContractError('exact closed native deployment required')
    value.__post_init__()
    return value


def checked_headless_train_deployment(value):
    if type(value) is not FrozenHeadlessTrainDeployment:
        raise ContractError('exact closed headless TRAIN deployment required')
    value.__post_init__()
    return value


def diagnostic_receipt_schema(deployment):
    if deployment is None:
        return 'grok-native-acp-diagnostic-receipt-v1'
    checked_deployment(deployment)
    if deployment.skill_isolation:
        raise ContractError('isolated readiness deployment is not admitted by diagnostic readers')
    return 'grok-native-acp-diagnostic-receipt-v2'
