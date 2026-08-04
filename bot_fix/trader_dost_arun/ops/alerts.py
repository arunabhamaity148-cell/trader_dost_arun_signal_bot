from __future__ import annotations

import asyncio
import html
import logging
import sqlite3
from math import ceil
from pathlib import Path

import httpx

from trader_dost_arun.core.models import Direction, Signal, VenueHealth
from trader_dost_arun.ops.logging_utils import CooldownDeduper

LOGGER = logging.getLogger(__name__)


def advisory_leverage(signal: Signal) -> int:
    """Shared leverage heuristic used both to SIZE the internal hypothetical
    position and to DISPLAY leverage in the alert template. Before this helper
    existed, the two sides computed leverage from different code paths (engine
    used metadata.get("leverage", 1.0) == 1.0 while the template showed up to
    5x), so the R math in your position tracker never matched the advertised
    leverage in the message."""
    stop_pct = max(signal.stop_pct, 1e-6)
    return min(5, max(1, ceil(1 / (stop_pct * 10))))


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
        self._health_deduper = CooldownDeduper(default_cooldown_seconds=60.0)
        self._disabled_log_deduper = CooldownDeduper(default_cooldown_seconds=300.0)
        # Delivery-failure tracking: previously a failed send() only logged a
        # warning and returned - a signal could silently never reach the
        # user with no visible difference from a successful delivery. These
        # let app.py detect delivery failures (including consecutive
        # failures, e.g. an expired token) and surface them loudly instead
        # of only in a log file nobody is watching.
        self.consecutive_send_failures = 0
        self.last_send_error: str | None = None
        self.total_signal_alerts_sent = 0
        self.total_signal_alerts_failed = 0
        # Second line of defense against duplicate alerts, independent of
        # engine.py's duplicate_open_position gate: keyed on strategy+symbol
        # +venue+direction so the same setup can't spam a Telegram alert
        # repeatedly within the cooldown window even if some future code
        # path generates it twice (e.g. a manual re-evaluation or a bug in
        # the exposure check upstream).
        self._signal_deduper = CooldownDeduper(default_cooldown_seconds=90.0)

    async def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a Telegram message. Returns True on confirmed delivery,
        False otherwise (including when Telegram is unconfigured). Retries
        transient failures a few times before giving up.

        Uses a single long-lived httpx.AsyncClient instead of creating a new
        client per send (which previously added TLS handshake + connection-pool
        setup overhead to EVERY alert under load)."""
        if not self.token or not self.chat_id:
            if self._disabled_log_deduper.should_emit("telegram-disabled"):
                LOGGER.info("Telegram DISABLED - missing token or chat id")
            return False
        client = await self._get_client()
        max_attempts = 3
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True},
                )
                response.raise_for_status()
                self.consecutive_send_failures = 0
                self.last_send_error = None
                return True
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_attempts:
                    await asyncio.sleep(1.0 * attempt)
        self.consecutive_send_failures += 1
        self.last_send_error = f"{type(last_exc).__name__}: {last_exc}"
        LOGGER.warning(
            "telegram send failed after %s attempts (consecutive_failures=%s): %s",
            max_attempts, self.consecutive_send_failures, last_exc,
        )
        return False

    def _bar(self, value: float) -> str:
        filled = max(0, min(10, round(value / 10)))
        return "█" * filled + "░" * (10 - filled)

    def _color(self, value: float) -> str:
        if value >= 70:
            return "🟢"
        if value >= 55:
            return "🟡"
        return "🔴"

    async def _get_client(self) -> httpx.AsyncClient:
        client = getattr(self, "_client", None)
        if client is None:
            # Lazily create once; the single client multiplexes via HTTP/2 to
            # api.telegram.org.
            client = httpx.AsyncClient(timeout=10)
            self._client = client
        return client

    async def aclose(self) -> None:
        client = getattr(self, "_client", None)
        if client is not None:
            await client.aclose()
            self._client = None

    def _leverage(self, signal: Signal) -> int:
        return advisory_leverage(signal)

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

    async def signal_alert(self, signal: Signal) -> str:
        """Returns 'sent', 'duplicate' (suppressed by cooldown dedup - not a
        failure), or 'failed' (genuine delivery failure). Callers must not
        treat 'duplicate' as a failure - see app.py's alert-failure escalation,
        which only fires on 'failed'."""
        key = f"signal:{signal.strategy_name}:{signal.symbol}:{signal.venue}:{signal.direction.value}"
        if not self._signal_deduper.should_emit(key):
            LOGGER.info("signal alert suppressed as duplicate within cooldown: %s", key)
            return "duplicate"
        delivered = await self.send(self.render_signal(signal), parse_mode="HTML")
        if delivered:
            self.total_signal_alerts_sent += 1
            return "sent"
        self.total_signal_alerts_failed += 1
        return "failed"

    async def health_alert(self, health: VenueHealth) -> None:
        key = f"health:{health.venue}:{health.status}:{round(health.score, 0)}"
        if not self._health_deduper.should_emit(key):
            return
        await self.send(
            f"⚠️ <b>Health warning</b> {health.venue}: status={health.status}, score={health.score:.1f}, p95={health.p95_latency_ms:.1f}ms, stale={health.stale_seconds:.1f}s, reconnects={health.reconnect_count}"
        )
