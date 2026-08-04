from trader_dost_arun.signals.engine import SignalEngine


def test_regime_weighting_prefers_continuation_in_trending():
    engine = SignalEngine(
        {
            "risk": {"daily_loss_limit_r": 4, "kill_switch_after_consecutive_losses": 4},
            "adaptive": {
                "kelly_cap": 0.03,
                "kelly_fraction": 0.5,
                "hmm_regimes": 3,
                "hmm_min_samples": 5,
                "meta_label_threshold": 0.5,
                "max_gross_exposure": 1.0,
                "max_same_direction_exposure": 1.0,
            },
            "strategy_priors": {name: 80 for name in [
                "liquidation_cascade_continuation",
                "extreme_funding_crowding_reversion",
                "order_flow_imbalance_continuation",
                "aggressor_exhaustion_absorption_fade",
                "fresh_oi_breakout_continuation",
                "single_venue_premium_snapback",
                "cross_venue_basis_dispersion_convergence",
                "spot_index_lead_follow_through",
                "funding_window_inventory_rebalance",
                "deribit_iv_shock_repricing",
            ]},
            "strategies": {"aggressor_exhaustion_absorption_fade": {"cvd_extreme": 1000}},
            "vetoes": {
                "volatility_anomaly": {"rv_5m_max": 1.0},
                "exchange_instability": {"max_mark_index_gap_bps": 1000, "max_feed_lag_seconds": 999},
                "correlation_spike": {"dispersion_limit": 9999},
                "cross_venue_dispersion": {"price_dispersion_limit": 9999, "premium_dispersion_limit": 9999},
                "funding_proximity": {"pre_minutes": 5, "post_minutes": 3},
                "liquidation_tape": {"liquidation_notional_limit": 999999999},
            },
        }
    )
    up_label, up_conf, up_priority = engine._regime_weight("order_flow_imbalance_continuation", "trending")
    down_label, down_conf, down_priority = engine._regime_weight("single_venue_premium_snapback", "trending")
    assert up_label == "up-weighted"
    assert down_label == "down-weighted"
    assert up_conf > down_conf
    assert up_priority > down_priority
