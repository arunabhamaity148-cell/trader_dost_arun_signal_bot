import pytest

from trader_dost_arun.newsguard.whale_tracker import WhaleTracker


@pytest.mark.asyncio
async def test_eth_btc_tron_methods_can_be_mocked(monkeypatch):
    tracker = WhaleTracker()

    async def eth_rows():
        return [{"usd": 6_000_000, "to": "binance_addr_1", "from": "wallet"}]

    async def btc_rows():
        return [{"usd": 0, "to": "none", "from": "none"}]

    async def tron_rows():
        return [{"usd": 0, "to": "none", "from": "none"}]

    monkeypatch.setattr(tracker, "fetch_eth", eth_rows)
    monkeypatch.setattr(tracker, "fetch_btc", btc_rows)
    monkeypatch.setattr(tracker, "fetch_tron", tron_rows)
    alerts = await tracker.alerts()
    assert alerts[0].chain == "ETH"


def test_net_flow_marks_exchange_inflow_as_bearish():
    tracker = WhaleTracker()
    flows = tracker.net_flow_usd_per_exchange([{"usd": 6_000_000, "to": "binance_addr_1", "from": "wallet"}], "ETH")
    assert flows["binance"] > 0


def test_net_flow_marks_exchange_outflow_as_bullish():
    tracker = WhaleTracker()
    flows = tracker.net_flow_usd_per_exchange([{"usd": 6_000_000, "to": "wallet", "from": "binance_addr_1"}], "BTC")
    assert flows["binance"] < 0
