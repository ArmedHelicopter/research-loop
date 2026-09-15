# Grok initialize stack r2

Prepared only. One fixed initialize; zero session, prompt, authenticate and billing RPC writes. CDB only attaches to the exact spawned child after 15 seconds without a response. Fixture-verified command uses `-pv`, no `-pd` or `-netsym`, explicit `qd`, `-sins -snul -y` fresh empty private symbol directory, `-noshell`, and `-nosqm`. Brief suspension makes timings noncomparable. Raw stdout/logs remain private. Success requires CDB exit 0, parsed Child-SP/RetAddr frames, and child alive after qd.
