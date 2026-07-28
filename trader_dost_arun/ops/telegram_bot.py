from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from trader_dost_arun.core.persistence import PositionStore

LOGGER = logging.getLogger(__name__)


class TelegramAdminBot:
    def __init__(self, token: str, admin_chat_id: str, state_path: str | Path = "./data/bot_state.json", position_store: PositionStore | None = None) -> None:
        self.token = token
        self.admin_chat_id = str(admin_chat_id) if admin_chat_id else ""
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.position_store = position_store or PositionStore()
        self.state = self._load_state()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"muted_until": 0, "paused_strategies": []}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def handle_command(self, text: str) -> str:
        parts = text.strip().split()
        command = parts[0].lower() if parts else ""
        if command == "/mute" and len(parts) >= 2:
            minutes = int(parts[1])
            self.state["muted_until"] = minutes
            self._save_state()
            return f"Muted for {minutes} minutes"
        if command == "/pause" and len(parts) >= 2:
            strategy = parts[1]
            self.state.setdefault("paused_strategies", [])
            if strategy not in self.state["paused_strategies"]:
                self.state["paused_strategies"].append(strategy)
            self._save_state()
            return f"Paused {strategy}"
        if command == "/resume" and len(parts) >= 2:
            strategy = parts[1]
            self.state["paused_strategies"] = [s for s in self.state.get("paused_strategies", []) if s != strategy]
            self._save_state()
            return f"Resumed {strategy}"
        if command == "/status":
            open_positions = self.position_store.load_open_positions()
            return f"Open positions: {len(open_positions)} | regime: live | daily PnL: n/a"
        if command == "/stats":
            history = self.position_store.get_history(limit=500)
            returns = [float(row.get("realized_r") or 0.0) for row in history if row.get("realized_r") is not None]
            wins = sum(1 for r in returns if r > 0)
            pf = sum(r for r in returns if r > 0) / max(abs(sum(r for r in returns if r < 0)), 1e-9) if returns else 0.0
            return f"7d/30d win rate: {wins}/{len(returns)} | profit factor: {pf:.2f} | total R: {sum(returns):.2f}"
        return "Unknown command"

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
                        if chat_id != self.admin_chat_id:
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
