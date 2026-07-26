from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from app import TradingApplication
from trader_dost_arun.core.config import load_settings

ROOT = Path(__file__).resolve().parent
OUTPUT_JSON = ROOT / "runtime_verification.json"
OUTPUT_MD = ROOT / "RUNTIME_VERIFICATION.md"
LOG_DIR = ROOT / "logs"


async def fetch_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def main() -> int:
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("TELEGRAM_CHAT_ID", None)
    if LOG_DIR.exists():
        for path in LOG_DIR.iterdir():
            if path.is_file():
                path.unlink()
    settings = load_settings(ROOT)
    settings.config["watchlist"] = {
        "binance": ["BTCUSDT"],
        "bybit": ["BTCUSDT"],
        "okx": ["BTC-USDT-SWAP"],
        "hyperliquid": ["BTC-PERP"],
        "deribit": ["BTC-PERPETUAL"],
    }
    settings.config["system"]["min_snapshots_before_signals"] = 5
    settings.config["system"]["signal_evaluation_interval_seconds"] = 1.0
    settings.config["ops"]["health_port"] = 18081
    app = TradingApplication(ROOT, settings=settings)
    health_samples: list[dict[str, Any]] = []
    metrics_samples: list[dict[str, Any]] = []
    duration_seconds = 90
    await app.start()
    try:
        for second in range(0, duration_seconds, 10):
            await asyncio.sleep(10)
            health_text = ""
            metrics_text = ""
            try:
                health_text = await fetch_text("http://127.0.0.1:18081/health")
            except Exception as exc:  # noqa: BLE001
                health_text = f"ERROR: {exc}"
            try:
                metrics_text = await fetch_text("http://127.0.0.1:18081/metrics")
            except Exception as exc:  # noqa: BLE001
                metrics_text = f"ERROR: {exc}"
            health_samples.append({"t": second + 10, "payload": health_text})
            metrics_samples.append({
                "t": second + 10,
                "metrics_ok": "signals_total" in metrics_text and "signal_latency_seconds" in metrics_text,
                "payload_preview": metrics_text[:500],
            })
    finally:
        runtime_snapshot = app.runtime_snapshot()
        await app.stop()
        current = asyncio.current_task()
        pending_after_stop = [task.get_name() for task in asyncio.all_tasks() if task is not current and not task.done()]
        log_text = ""
        log_path = LOG_DIR / "signal_bot.log"
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8")
        report = {
            "runtime": runtime_snapshot,
            "health_samples": health_samples,
            "metrics_samples": metrics_samples,
            "pending_after_stop": pending_after_stop,
            "shutdown_errors_present": {
                "task_destroyed": "Task was destroyed but it is pending!" in log_text,
                "event_loop_closed": "Event loop is closed" in log_text,
                "task_exception_never_retrieved": "Task exception was never retrieved" in log_text,
            },
            "log_tail": log_text.splitlines()[-80:],
        }
        OUTPUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
        md = [
            "# Runtime Verification",
            "",
            f"- Duration seconds: {runtime_snapshot['runtime_duration_seconds']:.1f}",
            f"- Enabled venues: {', '.join(runtime_snapshot['enabled_venues'])}",
            f"- Enabled symbols: {', '.join(runtime_snapshot['enabled_symbols'])}",
            f"- Socket count: {runtime_snapshot['socket_count']}",
            f"- Peak task count: {runtime_snapshot['peak_task_count']}",
            f"- Reconnect count by venue: {runtime_snapshot['reconnect_count_by_venue']}",
            f"- Reconnect reasons: {runtime_snapshot['reconnect_reason_distribution']}",
            f"- Stale snapshot blocks: {runtime_snapshot['stale_snapshot_blocks']}",
            f"- Healthy snapshot evaluations: {runtime_snapshot['healthy_snapshot_evaluations']}",
            f"- Signals evaluated: {runtime_snapshot['signals_evaluated']}",
            f"- Signals emitted: {runtime_snapshot['signals_emitted']}",
            f"- Signals blocked by reason: {runtime_snapshot['signals_blocked_by_reason']}",
            f"- Unexpected exceptions: {runtime_snapshot['unexpected_exceptions']}",
            f"- Final health payload: {runtime_snapshot['health']}",
            f"- Pending tasks after stop: {pending_after_stop}",
            f"- Shutdown markers: {report['shutdown_errors_present']}",
            "",
            "## Health samples",
        ]
        md.extend([f"- t={sample['t']}s: `{sample['payload']}`" for sample in health_samples])
        md.append("")
        md.append("## Metrics samples")
        md.extend([f"- t={sample['t']}s metrics_ok={sample['metrics_ok']}" for sample in metrics_samples])
        OUTPUT_MD.write_text("\n".join(md), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
