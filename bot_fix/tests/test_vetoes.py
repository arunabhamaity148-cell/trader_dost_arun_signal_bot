from datetime import datetime, timezone

from trader_dost_arun.core.models import FeatureSet, StructuralState
from trader_dost_arun.core.state import MarketStateStore
from trader_dost_arun.data.external import ExternalContext
from trader_dost_arun.signals.vetoes import VetoEngine


CONFIG = {
    "vetoes": {
        "volatility_anomaly": {"rv_5m_max": 0.2},
        "exchange_instability": {"max_mark_index_gap_bps": 40, "max_feed_lag_seconds": 2},
        "correlation_spike": {"dispersion_limit": 100},
        "cross_venue_dispersion": {"price_dispersion_limit": 200, "premium_dispersion_limit": 50},
        "funding_proximity": {"pre_minutes": 5, "post_minutes": 3},
        "liquidation_tape": {"liquidation_notional_limit": 1000},
    }
}


def test_veto_engine_blocks_unstable_mark_dislocation():
    engine = VetoEngine(CONFIG)
    features = FeatureSet("binance", "BTCUSDT", datetime.now(timezone.utc), {"spread": 1, "same_side_depth": 100, "atr": 10, "delta_oi": 1, "funding_zscore": 0, "realized_vol_5m": 0.05, "mark_price": 110, "index_price": 100, "price_dispersion": 0, "premium_dispersion": 0, "liquidation_notional": 0})
    checks, failed = engine.evaluate("order_flow_imbalance_continuation", "binance", "BTCUSDT", features, StructuralState(), MarketStateStore(), ExternalContext(), {})
    assert checks["exchange_instability"] is False
    assert failed == "exchange_instability"
