# CHANGELOG

## Trader Dost Arun Signal Bot v2 Fixed

### Core bug fixes
1. Replaced slotted dataclass `.__dict__` access in `trader_dost_arun/features/structural.py` with `dataclasses.asdict()`.
2. Improved structural order-block detection so recent breakout sequences correctly surface bullish/bearish order blocks.
3. Hardened orderbook normalization in `trader_dost_arun/data/base.py` to accept:
   - 2-element arrays
   - 4-element arrays from OKX/Deribit
   - mixed arrays with non-numeric prefixes/suffixes
   - dict-based levels such as Hyperliquid `{px, sz}`.
4. Updated Hyperliquid parsing to pass raw `levels` through the shared orderbook normalizer.
5. Changed connector exception logging from traceback-style logging to warning-only logging so transient venue issues do not spam stack traces.

### NewsGuard / feed reliability
6. Added `follow_redirects=True` to RSS, Nitter/X, Telegram, and Etherscan source fetches.
7. Wrapped each RSS / Telegram / Etherscan source fetch in local `try/except`, logging warnings and returning/continuing safely instead of raising.
8. Kept overall NewsGuard refresh loop resilient so dead feeds or invalid XML no longer stop refresh processing.

### LLM classifier
9. Rebuilt `trader_dost_arun/newsguard/llm_classifier.py` to use `z-ai-web-dev-sdk chat.completions.create` with `glm-4.6` request payloads and JSON-schema-guided batch output parsing.
10. Preserved keyword fallback behavior and improved cache/order preservation so classified results return in original input order.

### Whale tracker
11. Removed `slots=True` from `WhaleTracker` so monkeypatching works in tests.
12. Added Solana support with `fetch_solana()` using Solana JSON-RPC against the USDC mint `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`.
13. Extended the exchange registry with Solana-specific address placeholders alongside existing exchange entries.
14. Updated whale alert scanning to cover four chains: ETH, BTC, TRON, and SOL.
15. Added per-chain fetch fault tolerance so one failing chain does not break the full whale alert cycle.

### Ops / observability
16. Added a proper `/metrics` endpoint in `trader_dost_arun/ops/health.py`.
17. Returned Prometheus payload bytes using the Prometheus content type constant, while preserving `/health` JSON responses.
18. Added 404 handling for unknown ops paths.

### Backtest reporting
19. Rebuilt backtest HTML generation to include:
   - Plotly equity charts embedded inline
   - metrics tables
   - regime breakdown tables
20. Added a graceful no-data Plotly report so HTML still contains an inline chart even when no trades match the requested window.
21. Replaced deprecated `datetime.utcnow()` usage in the runner with timezone-aware UTC timestamps.

### Tests added
22. Added `tests/test_metrics_endpoint.py` to verify `/metrics` and `/health` responses.
23. Added `tests/test_backtest_html_plotly.py` to verify Plotly HTML generation.
24. Updated `pytest.ini` to remove invalid asyncio config keys and register the `asyncio` marker cleanly.

### Verification performed
25. Ran full `pytest -q` successfully.
26. Ran `python app.py` with empty `.env` for 60 seconds via verification harness.
27. Queried `/metrics` and `/health` during the bot run.
28. Ran `python -m trader_dost_arun.backtest.runner --symbol BTCUSDT --days 7` and verified `plotly-graph-div` in the generated HTML.
29. Rendered the Telegram premium formatter template successfully with a Python one-liner.
