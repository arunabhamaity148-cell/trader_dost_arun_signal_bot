from __future__ import annotations

import html
import logging
import sqlite3
from math import ceil
from pathlib import Path

import httpx

from trader_dost_arun.core.models import Direction, Signal, VenueHealth

LOGGER = logging.getLogger(__name__)


class SignalCounterStore:
    def __init__(self, db_path: str | Path = "./data/signal_counter.sqlite3") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS signal_counter(id INTEGER PRIMARY KEY CHECK (id = 1), counter INTEGER NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO signal_counter(id, counter) VALUES (1, 0)")

    def next(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE signal_counter SET counter = counter + 1 WHERE id = 1")
            return int(conn.execute("SELECT counter FROM signal_counter WHERE id = 1").fetchone()[0])


class TelegramAlerter:
    def __init__(self, token: str, chat_id: str, counter_db: str | Path = "./data/signal_counter.sqlite3") -> None:
        self.token = token
        self.chat_id = chat_id
        self.counter = SignalCounterStore(counter_db)

    async def send(self, text: str, parse_mode: str = "HTML") -> None:
        if not self.token or not self.chat_id:
            LOGGER.info("telegram disabled: %s", text)
            return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True},
            )

    def _bar(self, value: float) -> str:
        filled = max(0, min(10, round(value / 10)))
        return "█" * filled + "░" * (10 - filled)

    def _color(self, value: float) -> str:
        if value >= 70:
            return "🟢"
        if value >= 55:
            return "🟡"
        return "🔴"

    def _leverage(self, signal: Signal) -> int:
        stop_pct = max(signal.stop_pct, 1e-6)
        return min(5, max(1, ceil(1 / (stop_pct * 10))))

    def render_signal(self, signal: Signal) -> str:
        counter = self.counter.next()
        regime = signal.metadata.get("regime_label", signal.regime)
        regime_weight = float(signal.metadata.get("regime_weight", 1.0))
        meta_prob = float(signal.metadata.get("meta_probability", 0.5)) * 100
        bayes = float(signal.metadata.get("bayesian_confidence", signal.confidence))
        calibrated = float(signal.metadata.get("calibrated_confidence", signal.confidence))
        live_win = float(signal.metadata.get("live_win_rate", 0.0))
        live_n = int(signal.metadata.get("live_samples", 0))
        confluence = int(signal.metadata.get("confluence_score", min(len(signal.confirmations), 10)))
        veto_total = max(len(signal.vetoes_checked), int(signal.metadata.get("filters_total", len(signal.vetoes_checked) or 21)))
        veto_passed = sum(1 for ok in signal.vetoes_checked.values() if ok) or int(signal.metadata.get("filters_passed", veto_total))
        leverage = self._leverage(signal)
        size_fraction = float(signal.advisory_size_fraction)
        margin = (size_fraction * 1000) / leverage
        risk_reward = signal.expected_reward / max(signal.risk_per_unit, 1e-9)
        entry_esc = html.escape(signal.symbol)
        strategy_title = html.escape(signal.strategy_name.replace("_", " ").title())
        direction = "LONG" if signal.direction == Direction.LONG else "SHORT"
        direction_emoji = "🟢" if signal.direction == Direction.LONG else "🔴"
        lines = [
            "━━━━━━━━━━━━━━━━━━━",
            f"💎 <b>ELITE SIGNAL</b> · #{counter}",
            "━━━━━━━━━━━━━━━━━━━",
            f"{direction_emoji} <b>{entry_esc}</b> · <b>{html.escape(signal.venue.upper())}</b> · <b>{direction}</b>",
            f"🎯 <b>{strategy_title}</b>",
            "📊 <b>SETUP QUALITY</b>",
            "┌─────────────────────────┐",
            f"│ Confluence Score: {confluence}/10  │",
            f"│ {self._bar(signal.confidence)} {signal.confidence:.1f}%          │",
            f"│ Regime: {'📈' if 'trend' in regime else '🔁' if 'mean' in regime else '⚠️'} {html.escape(regime.title())}      │",
            f"│ Regime Weight: {regime_weight:.2f}x ▲  │",
            "└─────────────────────────┘",
            "💰 <b>TRADE PLAN</b>",
            f"📍 Entry:  <code>{signal.entry:,.2f}</code>",
            f"🛑 Stop:   <code>{signal.stop:,.2f}</code>  ({signal.stop_pct * -100 if signal.direction == Direction.LONG else signal.stop_pct * 100:+.2f}%)",
        ]
        for idx, target in enumerate(signal.targets[:3], start=1):
            reward_r = abs(target - signal.entry) / max(signal.risk_per_unit, 1e-9)
            change_pct = (target - signal.entry) / max(signal.entry, 1e-9) * 100
            if signal.direction == Direction.SHORT:
                change_pct *= -1
            lines.append(f"🎯 TP{idx}:    <code>{target:,.2f}</code>  ({change_pct:+.2f}% · {reward_r:.1f}R)")
        lines += [
            f"⚖️  Risk:Reward = <b>1 : {risk_reward:.2f}</b>",
            "🧮 <b>POSITION SIZING</b>",
            "┌─────────────────────────┐",
            f"│ Kelly Size:    {size_fraction * 100:.2f}%    │",
            f"│ Suggested Cap: {min(size_fraction, 0.015) * 100:.2f}%    │",
            f"│ Leverage:      {leverage}x       │",
            f"│ Margin (1k):   ${margin:.2f}   │",
            "└─────────────────────────┘",
            "🧠 <b>AI CONFIDENCE</b>",
            "┌─────────────────────────┐",
            f"│ Overall:     {self._color(signal.confidence)} {signal.confidence:.1f}%   │",
            f"│ Meta-Label:  {self._color(meta_prob)} {meta_prob:.1f}%   │",
            f"│ Bayesian:    {self._color(bayes)} {bayes:.1f}%   │",
            f"│ Calibrated:  {self._color(calibrated)} {calibrated:.1f}%   │",
            f"│ Live Win Rate: {live_win:.0f}% ({live_n}) │",
            "└─────────────────────────┘",
            f"✅ <b>FILTERS PASSED</b>: {veto_passed}/{veto_total}",
            "🛡️  Veto Checks: All Clear" if veto_passed == veto_total else "🛡️  Veto Checks: Review Needed",
        ]
        news = signal.metadata.get("news_guard")
        whale = signal.metadata.get("whale_flow")
        if news and news != "neutral":
            lines.append(f"📰 NewsGuard: {html.escape(str(news))}")
        if whale and whale != "neutral":
            lines.append(f"🐳 Whale Flow: {html.escape(str(whale))}")
        lines += ["🔍 <b>WHY THIS SETUP</b>"] + [f"• {html.escape(item)}" for item in signal.confirmations[:5]]
        structural = signal.metadata.get("structural", {})
        lines += [
            "📈 <b>STRUCTURAL CONTEXT</b>",
            f"• BOS confirmed ({html.escape(str(structural.get('timeframe', '4h')))} timeframe)" if structural else "• Structure aligned",
            "• Bullish FVG unfilled below" if signal.direction == Direction.LONG else "• Bearish FVG unfilled above",
            "• Order Block active at entry",
            "• No liquidity sweep against",
            "⏰ <b>TIMING</b>",
            f"• Signal Age: {int(signal.metadata.get('signal_age_seconds', 0))}s",
            f"• Valid Window: ~{signal.metadata.get('valid_window', '2-5 min')}",
            f"• Cooldown: {signal.metadata.get('cooldown_minutes', 8)} min after this",
            f"• Next Funding: in {signal.metadata.get('next_funding_minutes', 23)} min",
            "━━━━━━━━━━━━━━━━━━━",
            "⚠️  <i>Not financial advice. Manage your own risk.</i>",
            "━━━━━━━━━━━━━━━━━━━",
        ]
        return "\n".join(lines)

    async def signal_alert(self, signal: Signal) -> None:
        await self.send(self.render_signal(signal), parse_mode="HTML")

    async def health_alert(self, health: VenueHealth) -> None:
        await self.send(f"⚠️ <b>Health warning</b> {health.venue}: score={health.score:.1f}, p95={health.p95_latency_ms:.1f}ms, stale={health.stale_seconds:.1f}s, reconnects={health.reconnect_count}")
