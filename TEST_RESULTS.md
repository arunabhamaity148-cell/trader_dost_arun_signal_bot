# TEST RESULTS

## Baseline before modification
Initial full suite on the supplied ZIP:
- **88 passed in 9.71s**

## Post-repair compile/import validation
Changed modules compiled successfully with `python -m py_compile`, including:
- `app.py`
- `trader_dost_arun/data/ingress.py`
- `trader_dost_arun/data/base.py`
- `trader_dost_arun/data/grouped.py`
- `trader_dost_arun/data/external.py`
- `trader_dost_arun/data/manager.py`
- `trader_dost_arun/ops/latency.py`
- `trader_dost_arun/ops/telegram_bot.py`

## Full pytest after repair
Result:
- **95 passed in 10.46s**
- warnings: **0** on the final run

## New regression coverage added in this session
- bounded market queue coalescing
- liquidation preservation under queue pressure
- RSS telemetry returns non-zero process memory on Linux
- `connection_closed:1006` systemic classification
- external bootstrap failure isolation
- reconnect loop does not duplicate supplemental workers
- runtime snapshot exposes queue-overload counters

## Clean install test
A fresh virtual environment was created and validated.

Command flow executed:
1. create venv
2. `pip install -r requirements.txt`
3. `python -m pytest -q`

Result:
- **PASS**
- **95 passed in 13.35s**

## Validation summary
- baseline existing suite: **PASS**
- post-repair suite: **PASS**
- clean install suite: **PASS**
- tests removed/skipped/weakened to get green: **NO**
