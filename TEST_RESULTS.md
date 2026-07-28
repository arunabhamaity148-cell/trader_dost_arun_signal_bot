# TEST RESULTS

## Scope
Repository: `trader_dost_arun_signal_bot-main`

## Compile / import validation
**PROVEN PASS**

Validated with Python bytecode compilation for the changed modules, including:
- `app.py`
- `trader_dost_arun/data/manager.py`
- `trader_dost_arun/data/grouped.py`
- `trader_dost_arun/newsguard/guard.py`
- `trader_dost_arun/newsguard/embeddings.py`
- `tests/test_grouped_architecture.py`

## Full pytest
**PROVEN PASS**

Command executed:
```bash
pytest -q
```

Result:
```text
88 passed in 6.49s
```

## Regression coverage added this session
New regression coverage was added for:
- grouped connector manager topology
- duplicate start prevention
- correct grouped symbol routing (Binance / Hyperliquid)
- bounded logging queue behavior
- SentenceTransformer progress suppression
- runtime snapshot topology / bounded queue metrics

## Comparison against stated baseline
- Historical baseline from prior session notes: **81 passed**
- Final post-repair result in this session: **88 passed**

## Clean install / fresh venv
**NOT VERIFIED**

A fresh virtual-environment install was not completed in this workflow. The repaired code is delivered with the existing `requirements.txt`, but clean-room installation evidence is not claimed.

## Final testing classification
- Unit / regression suite: **PASS**
- Clean install: **NOT VERIFIED**
- 60-second full-watchlist live smoke: see `RUNTIME_VERIFICATION.md`
- 15-minute full-watchlist soak: see `SOAK_TEST_RESULTS.md`
