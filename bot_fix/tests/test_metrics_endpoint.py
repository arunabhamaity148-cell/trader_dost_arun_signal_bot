import asyncio

from trader_dost_arun.ops.health import LATENCY_HIST, SIGNAL_COUNTER, VETO_COUNTER, OpsHttpServer


async def _fetch(url: str) -> str:
    process = await asyncio.create_subprocess_shell(
        f"curl -s {url}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", "ignore"))
    return stdout.decode("utf-8", "ignore")


def test_metrics_endpoint_exposes_prometheus_metrics():
    async def runner() -> None:
        server = OpsHttpServer(port=18080)
        if SIGNAL_COUNTER is not None:
            SIGNAL_COUNTER.inc()
        if VETO_COUNTER is not None:
            VETO_COUNTER.labels(reason="test").inc()
        if LATENCY_HIST is not None:
            LATENCY_HIST.observe(0.123)
        await server.start()
        try:
            await asyncio.sleep(0.05)
            metrics = await _fetch("http://127.0.0.1:18080/metrics")
            health = await _fetch("http://127.0.0.1:18080/health")
            assert "signals_total" in metrics
            assert "signal_veto_total" in metrics
            assert "signal_latency_seconds" in metrics
            assert '"status": "ok"' in health
        finally:
            await server.stop()

    asyncio.run(runner())
