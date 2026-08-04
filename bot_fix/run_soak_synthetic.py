"""60-second synthetic soak driving the REAL app code path.

Wires TradingApplication exactly as production does, but replaces exchange
websockets with a synthetic producer that floods the real BoundedMarketQueue at
a configurable event rate across the full watchlist (5 venues x 10 symbols).
This exercises the real consumer task, SignalEvaluationScheduler, SignalEngine,
PositionStore, HealthScorer, and OpsHttpServer on a public-less host (no
network), so the loop-lag / RSS / queue / task numbers are attributable purely
to the in-process data path under load.

It is NOT a substitute for a live exchange soak - that is listed in
SOAK_TEST_RESULTS.md as still-required-on-target evidence. This is the
graceful-load + graceful-degradation evidence.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from trader_dost_arun.core.models import Direction, MarketSnapshot, OrderBookLevel, Trade

STATUS_PATH = Path("./data/soak_status.json")


async def run(duration_seconds: float = 60.0, events_per_second: int = 400) -> dict:
    import app as appmod  # local app module (the real TradingApplication)
    from trader_dost_arun.core.config import load_settings

    settings = load_settings(Path("."))
    application = appmod.TradingApplication(Path("."), settings=settings)
    # Bind ops to a throwaway localhost port for this process only.
    application.http_server.host = "127.0.0.1"
    application.http_server.port = 0

    # Replace the connector manager with a producer that floods the REAL queue.
    real_queue = application.manager.queue

    venues = settings.config["watchlist"]
    rng = random.Random(1337)

    async def producer() -> None:
        seq = 0
        interval = 1.0 / max(events_per_second, 1)
        while not application._stop.is_set():
            for venue, symbols in venues.items():
                symbol = symbols[seq % len(symbols)]
                base = 100.0 + rng.uniform(-1, 1) + seq * 0.0001
                bid = [OrderBookLevel(base, rng.uniform(0.5, 3.0))]
                ask = [OrderBookLevel(base + 0.01, rng.uniform(0.5, 3.0))]
                snap = MarketSnapshot(
                    venue, symbol, datetime.now(timezone.utc),
                    bid_levels=bid, ask_levels=ask,
                    mark_price=base, index_price=base - 0.05,
                    funding_rate=rng.uniform(-0.001, 0.001),
                    open_interest=1000.0 + rng.uniform(-50, 50),
                    premium=rng.uniform(-2, 2), spread=0.01,
                    option_atm_iv=50.0 + rng.uniform(-5, 5),
                    option_put_call_skew=rng.uniform(-0.1, 0.1),
                    core_event_time=datetime.now(timezone.utc), update_class="core",
                )
                await real_queue.put(snap)
                if seq % 4 == 0:
                    await real_queue.put(
                        Trade(venue, symbol, base, rng.uniform(0.1, 2.0),
                              Direction.LONG if rng.random() < 0.5 else Direction.SHORT,
                              datetime.now(timezone.utc)))
                seq += 1
            await asyncio.sleep(interval * len(venues))

    async def fake_start():
        application.manager._started = True
        prod = asyncio.create_task(producer(), name="synthetic-producer")
        application._background_tasks.append(prod)
        return real_queue

    application.manager.start = fake_start  # type: ignore[method-assign]

    task = asyncio.create_task(application.run_forever(), name="app")
    checkpoints = {}
    started = time.perf_counter()
    try:
        while time.perf_counter() - started < duration_seconds:
            await asyncio.sleep(5.0)
            elapsed = round(time.perf_counter() - started, 1)
            s = application.runtime_snapshot()
            checkpoints[f"{int(elapsed)}s"] = {
                "events_processed": s["events_processed"],
                "events_per_second": round(s["events_processed_per_second"], 1),
                "queue_depth": s["queue_depth"],
                "queue_hwm": s["queue_high_water_mark"],
                "queue_overload": s["queue_overload"],
                "task_count": s["task_count"],
                "peak_task_count": s["peak_task_count"],
                "rss_mb": s["rss_mb"],
                "rss_peak_mb": s["rss_peak_mb"],
                "loop_lag_p95_ms": round(s["event_loop_lag_p95_ms"], 2),
                "loop_lag_max_ms": round(s["event_loop_lag_max_ms"], 2),
                "eval_latency_p95_ms": round(s["evaluation_latency_p95_ms"], 2),
                "stale_blocks": s["stale_snapshot_blocks"],
                "signals_evaluated": s["signals_evaluated"],
                "signals_emitted": s["signals_emitted"],
                "unexpected_exceptions": s["unexpected_exceptions"],
            }
    finally:
        application.request_shutdown("soak-complete")
        await asyncio.wait_for(task, timeout=30)

    final = application.runtime_snapshot()
    result = {
        "duration_seconds": duration_seconds,
        "target_events_per_second": events_per_second,
        "checkpoints": checkpoints,
        "final": {
            "events_processed": final["events_processed"],
            "rss_mb": final["rss_mb"],
            "rss_peak_mb": final["rss_peak_mb"],
            "loop_lag_p95_ms": final["event_loop_lag_p95_ms"],
            "loop_lag_max_ms": final["event_loop_lag_max_ms"],
            "unexpected_exceptions": final["unexpected_exceptions"],
            "queue_overload": final["queue_overload"],
            "task_count": final["task_count"],
            "peak_task_count": final["peak_task_count"],
        },
    }
    STATUS_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.WARNING)
    dur = float(sys.argv[1]) if (sys := __import__("sys")) and len(sys.argv) > 1 else 60.0
    eps = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    out = asyncio.run(run(duration_seconds=dur, events_per_second=eps))
    print(json.dumps(out["final"], indent=2))
