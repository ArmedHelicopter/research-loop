# Root native deployment integration checks

Sourcefe77ef1 closed30/30,635 source files unchanged,27.046s. Sourcefcd175c
closed39/39,635 unchanged,21.172s, covering the later response-before-inventory
repair. Both use synthetic ACP peers below the native spawn seam and label
checks; neither check made a real model request. The separate native-readiness
archive records actual attempts, including the dispatched request with unknown
usage. Do not infer real readiness from these synthetic checks.
