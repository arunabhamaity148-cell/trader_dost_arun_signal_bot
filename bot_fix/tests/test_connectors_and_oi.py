import asyncio
from datetime import datetime, timezone

import pytest

from trader_dost_arun.data.binance import BinanceConnector
from trader_dost_arun.data.deribit import DeribitConnector
from trader_dost_arun.data.hyperliquid import HyperliquidConnector
from trader_dost_arun.data.okx import OkxConnector
from trader_dost_arun.ops.latency import LatencyMonitor


def _connector(connector_cls, symbol: str):
    return connector_cls(symbol=symbol, latency_monitor=LatencyMonitor(), config={})


def test_binance_open_interest_parser():
    connector = _connector(BinanceConnector, "BTCUSDT")
    assert connector._parse_open_interest_payload({"openInterest": "12345.6"}) == pytest.approx(12345.6)


def test_okx_open_interest_parser():
    connector = _connector(OkxConnector, "BTC-USDT-SWAP")
    assert connector._parse_open_interest_payload({"data": [{"oi": "98765"}]}) == pytest.approx(98765.0)


def test_hyperliquid_asset_context_parser_reads_open_interest():
    connector = _connector(HyperliquidConnector, "BTC-PERP")
    payload = [
        {"universe": [{"name": "BTC"}]},
        [{"markPx": "100.0", "oraclePx": "99.5", "funding": "0.0001", "openInterest": "5555"}],
    ]
    parsed = connector._parse_asset_context(payload)
    assert parsed["open_interest"] == pytest.approx(5555.0)
    assert parsed["mark_price"] == pytest.approx(100.0)


def test_deribit_option_metrics_are_real_options_data():
    connector = _connector(DeribitConnector, "BTC-PERPETUAL")
    rows = [
        {"instrument_name": "BTC-30AUG26-60000-C", "underlying_price": 60500, "mark_iv": 0.74},
        {"instrument_name": "BTC-30AUG26-60000-P", "underlying_price": 60500, "mark_iv": 0.82},
        {"instrument_name": "BTC-27SEP26-70000-C", "underlying_price": 60500, "mark_iv": 0.69},
    ]
    metrics = connector._compute_option_metrics(rows)
    assert metrics["atm_iv"] == pytest.approx((0.74 + 0.82) / 2)
    assert metrics["put_call_skew"] == pytest.approx(0.08)
