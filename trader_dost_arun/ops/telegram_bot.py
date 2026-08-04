from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from trader_dost_arun.core.operator_state import OperatorState
from trader_dost_arun.core.persistence import PositionStore

LOGGER = logging.getLogger(__name__)


class TelegramAdminBot:
    def __init__(self, token: str, admin_chat_id: str, state_path: str | Path = "./data/bot_state.json", position_store: PositionStore | None = None, operator_state: OperatorState | None = None, allowed_chat_ids: list[str] | None = None, engine_stats_provider=None) -> None:
        self.token = token
        self.admin_chat_id = str(admin_chat_id) if admin_chat_id else ""
        # Shared operator-toggles object is the SINGLE source of truth for pause/
        # resume/mute so the signal engine and this bot never disagree (the bug
        # where /pause wrote to a private dict the engine never read).
        self.operator_state = operator_state or OperatorState(state_path)
        self.position_store = position_store or PositionStore()
        self._engine_stats_provider = engine_stats_provider  # returns a dict for /status
        self._allowed_chat_ids = {str(c) for c in (allowed_chat_ids or ([self.admin_chat_id] if self.admin_chat_id else []))}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    # Backwards-compatible property used by older tests / code paths that poke
    # at bot.state directly. Now backed by the shared OperatorState.
    @property
    def state(self) -> dict[str, Any]:
        return {
            "muted_until": self.operator_state.mute_minutes(),
            "paused_strategies": self.operator_state.paused_strategies(),
        }

    def handle_command(self, text: str) -> str:
        parts = text.strip().split()
        command = parts[0].lower() if parts else ""
        if command == "/mute" and len(parts) >= 2:
            try:
                minutes = int(parts[1])
            except ValueError:
                return "Usage: /mute <minutes>"
            self.operator_state.set_mute(minutes)
            return f"Muted for {minutes} minutes"
        if command == "/pause" and len(parts) >= 2:
            strategy = parts[1]
            self.operator_state.pause(strategy)
            return f"Paused {strategy}"
        if command == "/resume" and len(parts) >= 2:
            strategy = parts[1]
            self.operator_state.resume(strategy)
            return f"Resumed {strategy}"
        if command == "/paused":
            paused = self.operator_state.paused_strategies()
            return "Paused strategies: " + (", ".join(paused) if paused else "none")
        if command == "/status":
            open_positions = self.position_store.load_open_positions()
            stats = {}
            if callable(self._engine_stats_provider):
                try:
                    stats = self._engine_stats_provider() or {}
                except Exception:  # noqa: BLE001
                    stats = {}
            return (
                f"Open positions: {len(open_positions)} | "
                f"paused: {len(self.operator_state.paused_strategies())} | "
                f"kill_switch: {stats.get('kill_switch_active', 'n/a')} | "
                f"daily R: {stats.get('daily_realized_r', 'n/a')}"
            )
        if command == "/stats":
            history = self.position_store.get_history(limit=500)
            returns = [float(row.get("realized_r") or 0.0) for row in history if row.get("realized_r") is not None]
            wins = sum(1 for r in returns if r > 0)
            pf = sum(r for r in returns if r > 0) / max(abs(sum(r for r in returns if r < 0)), 1e-9) if returns else 0.0
            return f"7d/30d win rate: {wins}/{len(returns)} | profit factor: {pf:.2f} | total R: {sum(returns):.2f}"
        return "Unknown command"

    def _is_authorized(self, chat_id: str) -> bool:
        # If an allow-list is configured, only those chats may issue commands.
        # If no admin id is configured at all, the bot stays inert (never
        # answers anyone) rather than falling back to open access.
        return bool(self._allowed_chat_ids) and chat_id in self._allowed_chat_ids

    async def start(self) -> None:
        if not self.token or not self.admin_chat_id:
            return
        if self._task is None:
            LOGGER.info("Telegram ENABLED - admin bot polling active")
            self._stop.clear()
            self._task = asyncio.create_task(self._poll_loop(), name="telegram-admin-poll")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _poll_loop(self) -> None:
        offset = 0
        async with httpx.AsyncClient(timeout=15) as client:
            while not self._stop.is_set():
                try:
                    response = await client.get(f"https://api.telegram.org/bot{self.token}/getUpdates", params={"offset": offset, "timeout": 10})
                    response.raise_for_status()
                    payload = response.json()
                    for item in payload.get("result", []):
                        offset = item.get("update_id", offset) + 1
                        message = item.get("message", {})
                        chat_id = str(message.get("chat", {}).get("id", ""))
                        if not self._is_authorized(chat_id):
                            continue
                        reply = self.handle_command(message.get("text", ""))
                        await client.post(f"https://api.telegram.org/bot{self.token}/sendMessage", json={"chat_id": self.admin_chat_id, "text": reply})
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("telegram admin poll failed: %s", exc)
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        continue
