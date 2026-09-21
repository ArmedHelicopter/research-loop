"""S: ordinary process-local revision cache for the existing native context contract.

Single controller; public ledger mutations only. No semantics or core changes.
The observer preserves existing audit sinks and invalidates on any ledger event.
This must invalidate on unrelated updates too: full ledger versions are public.
"""
from research_loop.modular.contracts import required_text
from research_loop.modular.modules.context import ContextBuilder
from research_loop.modular.modules.evidence import EvidenceLedger,ClaimLedger
from research_loop.ontology import ContractError

class VersionCache:
    def __init__(self):
        self._pair=None
        self._hooks=[]
        self._items={}
        self._epoch=0
        self._poisoned=False
        self.hits=self.misses=self.builds=self.events=self.invalidations=self.clears=0

    def _invalidate(self):
        self._epoch+=1
        self.events+=1
        self.invalidations+=len(self._items)
        self._items.clear()

    def _bind(self,evidence,claims):
        if self._pair and self._pair[0] is evidence and self._pair[1] is claims:
            for log,old_sink,old_failure,sink,failure in self._hooks:
                if log.event_sink is not sink or log.on_failure is not failure:
                    raise ContractError("S observer displaced; refusing a potentially stale cache")
            return
        self.close()
        if type(evidence) is not EvidenceLedger or type(claims) is not ClaimLedger or claims.evidence is not evidence:
            raise ContractError("S requires the exact native bound ledger pair")
        self._pair=(evidence,claims)
        self._poisoned=False
        self._epoch=0
        for ledger in (evidence,claims):
            log=ledger._log
            old_sink,old_failure=log.event_sink,log.on_failure
            def sink(event,forward=old_sink):
                self._invalidate()
                if forward is not None:
                    forward(event)
            def failure(forward=old_failure):
                self._poisoned=True
                self._invalidate()
                if forward is not None:
                    forward()
            self._hooks.append((log,old_sink,old_failure,sink,failure))
            log.event_sink,log.on_failure=sink,failure

    def get_or_build(self,builder,question,evidence,claims,*,mode="candidate",baseline_summary=None):
        if type(builder) is not ContextBuilder:
            raise ContractError("S is frozen to the native builder implementation")
        question=required_text(question,"context question")
        if builder.identity!=evidence.identity or claims.identity!=evidence.identity:
            raise ContractError("context identity mismatch")
        if mode not in ("baseline","candidate"):
            raise ContractError("context mode must be baseline or candidate")
        if baseline_summary is not None and not isinstance(baseline_summary,str):
            raise ContractError("baseline summary must be text")
        self._bind(evidence,claims)
        if self._poisoned:
            raise ContractError("S ledger write failed; discard this session")
        key=(self._epoch,builder.identity,question,builder.budget_bytes,mode,baseline_summary)
        if evidence.identity.domain!="validation" and key in self._items:
            self.hits+=1
            return self._items[key]
        self.misses+=1
        result=builder.build(question,evidence,claims,mode=mode,baseline_summary=baseline_summary)
        self.builds+=1
        if not result.ephemeral:
            self._items[key]=result
        return result

    def clear(self):
        self.clears+=1
        self._items.clear()

    def size(self):
        return len(self._items)

    def close(self):
        for log,old_sink,old_failure,sink,failure in self._hooks:
            if log.event_sink is sink:
                log.event_sink=old_sink
            if log.on_failure is failure:
                log.on_failure=old_failure
        self._hooks=[]
        self._pair=None
        self._items.clear()

    def stats(self):
        return dict(hits=self.hits,misses=self.misses,builds=self.builds,events=self.events,
                    invalidated_entries=self.invalidations,clears=self.clears,retained_entries=self.size())

