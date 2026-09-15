# Prepared one-opportunity normal headless TRAIN control

Prepared root: `WORK/grok-normal-train-control-r1`.

Future execution command, only after review:

```powershell
python -B E:\_ryanDev\AI\research-loop-modular\WORK\grok-normal-train-control-r1\control.py execute
```

The root is fresh and contains only `control.py`, `request.public.json`, and
`manifest.json`; preparation made zero native dispatches. The manifest pins
the production comparator executable `C:/Users/Administrator/.grok/bin/grok.exe`
to `bf43dc75f5478a106eab1e86d422c963e4dbe9666cf14dab363733d27bf1e672`,
the M4/M5 frozen runtime commit `2113371268b30411712273623371cbcf49e0ccc8`,
and inherited frozen runtime source pins. It binds the copied unmodified
public TRAIN `m4_plan` request to
`cb0c0fa56056540de382b615aacf8386731c6afbefa124fc742a0f7ad6614e28`.

On execution the ordinary `GrokHeadlessTrainModelPort` creates one durable
reservation before the normal transport, allows one model opportunity, a
60-second prompt timeout, and no model retry. Any failure remains terminal in
the new ledger with unknown accounting preserved. The transport's existing
read-only account pre/postflight remains part of its frozen protocol; the
control makes no login, billing, API-key-route, or validation change.

This is a direct normal headless CLI-stream path through
`run_headless_diagnostic`, not the r2 ACP stdio initialize harness. It checks
the headless stream's model and runtime-inventory bindings; it cannot by itself
prove ACP notification behavior, formal calibration, validation performance,
or scientific effectiveness.
