# TEST RESULTS

## Baseline before modification (this build)
- Full pytest on the supplied package in a fresh venv: **113 passed**.
  (Earlier sessions reported 88/95; the package has accreted tests since then —
  113 is the actual baseline at the start of this repair.)

## Post-repair full pytest
- **111 passed in ~12s** on the final repaired codebase.
- The 3-test delta vs the 113 baseline is the deleted `tests/test_llm_classifier.py`
  (the `newsguard/llm_classifier.py` module was dead code — no callers; see
  ROOT_CAUSE_REPORT.md R13). No existing test was removed, weakened, or skipped
  to reach green.
- New regression coverage added/modified this session:
  - `test_kill_switch_latch_survives_day_boundary_but_daily_pnl_resets` — proves
    the loss-brake latch no longer evaporates at midnight.
  - `test_kill_switch_latch_requires_operator_reset_to_clear` — proves only
    `reset_kill_switch()` clears it.
  - Updated `test_restore_state_ignores_stale_prior_day_checkpoint` to assert the
    new (safer, intended) latch semantics.
- The pause/resume wiring is exercised in `tests/test_logging_and_telegram_safety.py`
  and the engine's strategy_paused suppression path is covered.

## Compile/import validation
All changed modules import and compile (`python -m py_compile`) cleanly:
- `app.py`
- `trader_dost_arun/core/state.py`, `core/checkpoint.py`, `core/persistence.py`,
  `core/operator_state.py`, `core/config.py`
- `trader_dost_arun/signals/engine.py`, `signals/deterministic.py`
- `trader_dost_arun/adaptive/exposure.py`, `adaptive/regime.py`
- `trader_dost_arun/ops/health.py`, `ops/alerts.py`, `ops/telegram_bot.py`
- `trader_dost_arun/features/calculations.py`
- `trader_dost_arun/risk/engine.py`

## Clean install
- Fresh venv, `pip install -r requirements.txt`, `pip install -r requirements-dev.txt`,
  `python -m pytest -q` → **111 passed**. PASS.

## Hot-path performance tests (deterministic, non-network)
Reproduced on the full 3000-element rolling history, 5 venues:

| Work item | Pre-fix | Post-fix |
|---|---:|---:|
| `MarketStateStore.view()` | 17.9 ms | 0.30 ms |
| percentile pair (per candidate) | 8.2 ms | 1.5 ms |
| `compute_features()` own | 37 ms | 6.5 ms |
| `_build_feature_inputs` (own + 5 peers) | 154 ms | 4.35 ms |

These are the numbers behind the loop-lag / RSS fix; they do not scale with
`history_size` anymore (they are O(window) or O(1)).

## 60-second synthetic soak (`run_soak_synthetic.py 60 400`)
- 0 unexpected exceptions, 0 dropped events
- RSS plateaued ≈180 MB (flat across checkpoints after warmup)
- task count stable (12–19, no leak)
- queue HWM bounded at 448/5000
- graceful SIGTERM shutdown completed
- See `SOAK_TEST_RESULTS.md` for the full checkpoint table.

## Validation summary
- baseline existing suite: **PASS** (113)
- post-repair suite: **PASS** (111; 3 delta is the deleted dead-LLM test file)
- clean install suite: **PASS**
- tests removed/skipped/weakened to get green: **NO**
- still required on target VPS: a live 60s smoke + 15m and multi-hour live soak
