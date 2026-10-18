import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import core.brokers.mt5_connector as mt5_connector
from core.brokers.mt5_connector import MT5Connector
from core.drawdown_guard import DrawdownGuard
from core.bot_commands import BotCommands
from live_trading import LiveTradingBot


class DrawdownGuardPersistenceTests(unittest.TestCase):
    def test_persists_equity_references_pause_and_loss_streak(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "drawdown.json"
            now = datetime(2026, 10, 17, 12)
            guard = DrawdownGuard(state_path=state_path)
            self.assertEqual(guard.check(1000, now), (True, "OK"))
            guard.record_trade_result(-10)
            self.assertFalse(guard.check(970, now)[0])

            restored = DrawdownGuard(state_path=state_path)
            allowed, reason = restored.check(1000, now)
            self.assertFalse(allowed)
            self.assertIn("journalier", reason)
            self.assertEqual(restored._day_start_equity, 1000)
            self.assertEqual(restored._consecutive_losses, 1)

    def test_keeps_loss_streak_when_period_rolls_over(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "drawdown.json"
            guard = DrawdownGuard(state_path=state_path)
            guard.check(1000, datetime(2026, 10, 16, 12))
            guard.record_trade_result(-10)

            restored = DrawdownGuard(state_path=state_path)
            restored.check(990, datetime(2026, 10, 17, 12))
            self.assertEqual(restored._day_start_equity, 990)
            self.assertEqual(restored._consecutive_losses, 1)

    def test_rejects_corrupt_persistent_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "drawdown.json"
            state_path.write_text('{"version": 999}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                DrawdownGuard(state_path=state_path)

    def test_failed_state_write_does_not_clear_loss_pause(self):
        guard = DrawdownGuard()
        guard._consecutive_losses = 5
        guard._paused = True
        guard._pause_reason = "5 pertes consécutives"
        with patch.object(guard, "_persist_state", side_effect=RuntimeError("disk error")):
            with self.assertRaises(RuntimeError):
                guard.reset_consecutive_losses()

        self.assertEqual(guard._consecutive_losses, 5)
        self.assertTrue(guard.is_paused)

    def test_retries_transient_windows_replace_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "drawdown.json"
            guard = DrawdownGuard(state_path=state_path)
            real_replace = os.replace
            attempts = []

            def replace_with_one_transient_lock(source, destination):
                attempts.append(1)
                if len(attempts) == 2:
                    raise PermissionError(5, "Access is denied")
                real_replace(source, destination)

            with patch("core.drawdown_guard.os.replace", side_effect=replace_with_one_transient_lock):
                self.assertEqual(guard.check(1000, datetime(2026, 10, 17, 12)), (True, "OK"))

            self.assertEqual(len(attempts), 3)
            self.assertTrue(state_path.exists())
            self.assertEqual(list(Path(temp_dir).glob(".*.tmp")), [])


class PositionSizingTests(unittest.TestCase):
    def setUp(self):
        self.mt5 = SimpleNamespace(
            ORDER_TYPE_BUY=0,
            ORDER_TYPE_SELL=1,
            account_info=lambda: SimpleNamespace(balance=10000, margin_free=10000),
            symbol_info=lambda _symbol: SimpleNamespace(
                trade_tick_value=1,
                trade_tick_size=0.01,
                volume_min=0.01,
                volume_max=100,
                volume_step=0.01,
            ),
            order_calc_margin=lambda *_args: 100,
        )
        self.connector = MT5Connector(simulation=False)
        self.connector.connected = True
        self.connector.account_info = {"balance": 10000, "free_margin": 10000}

    def test_sizing_adds_slippage_and_rounds_down_to_broker_step(self):
        with patch.object(mt5_connector, "mt5", self.mt5), patch.object(
            mt5_connector, "MT5_AVAILABLE", True
        ):
            lots = self.connector.calculate_lots(
                "TEST", entry=100, stop_loss=99, risk_pct=0.01, slippage_pct=0.05
            )
            risk = self.connector.calculate_position_risk(
                "TEST", volume=lots, entry=100, stop_loss=99, slippage_pct=0.05
            )

        self.assertEqual(lots, 0.95)
        self.assertLessEqual(risk, 100)

    def test_refuses_broker_minimum_that_exceeds_requested_risk(self):
        self.connector.account_info = {"balance": 1, "free_margin": 1}
        self.mt5.account_info = lambda: SimpleNamespace(balance=1, margin_free=1)
        self.mt5.symbol_info = lambda _symbol: SimpleNamespace(
            trade_tick_value=1,
            trade_tick_size=0.01,
            volume_min=0.1,
            volume_max=100,
            volume_step=0.1,
        )
        with patch.object(mt5_connector, "mt5", self.mt5), patch.object(
            mt5_connector, "MT5_AVAILABLE", True
        ):
            lots = self.connector.calculate_lots(
                "TEST", entry=100, stop_loss=99, risk_pct=0.01, slippage_pct=0
            )

        self.assertEqual(lots, 0)

    def test_open_position_risk_is_aggregated_and_unknown_risk_fails_closed(self):
        bot = object.__new__(LiveTradingBot)
        bot.config = SimpleNamespace(slippage_pct=0.05)
        bot.mt5 = SimpleNamespace(
            calculate_position_risk=lambda **kwargs: kwargs["volume"] * 10
        )
        positions = [
            SimpleNamespace(ticket=1, symbol="A", volume=1, open_price=10, stop_loss=9),
            SimpleNamespace(ticket=2, symbol="B", volume=1.5, open_price=10, stop_loss=9),
        ]

        self.assertEqual(bot._calculate_open_positions_risk(positions), 25)
        positions[1].stop_loss = 0
        self.assertIsNone(bot._calculate_open_positions_risk(positions))

    def test_resetting_loss_pause_requires_confirmation(self):
        class Guard:
            is_paused = True
            status = "⛔ PAUSE — 5 pertes consécutives"

            def __init__(self):
                self.reset = False

            def reset_consecutive_losses(self):
                self.reset = True

        guard = Guard()
        bot = SimpleNamespace(
            drawdown_guard=guard,
            _cycle_now=False,
            _log=lambda _message: None,
        )
        commands = BotCommands(bot)

        self.assertIn("Confirmez avec /oui", commands.handle("/reset_garde"))
        self.assertFalse(guard.reset)
        self.assertIn("Compteur de pertes réinitialisé", commands.handle("/oui"))
        self.assertTrue(guard.reset)

    def test_telegram_recipients_exclude_bot_account_id(self):
        bot = object.__new__(LiveTradingBot)
        bot.notifier = SimpleNamespace(
            chat_id="human-main",
            chat_ids=["human-main", "123"],
            enabled=True,
        )
        bot.commander = SimpleNamespace(
            bot_token="not-a-real-token",
            chat_id="human-main",
            owner_chat_ids=["human-main", "123"],
            miniapp_chat_ids=["human-main", "123", "human-miniapp"],
            enabled=True,
        )

        with patch(
            "live_trading.get_me",
            return_value=(True, {"id": 123, "username": "example_bot"}, ""),
        ):
            bot._validate_telegram_recipients()

        self.assertEqual(bot.notifier.chat_ids, ["human-main"])
        self.assertEqual(bot.commander.owner_chat_ids, ["human-main"])
        self.assertEqual(bot.commander.miniapp_chat_ids, ["human-main", "human-miniapp"])
        self.assertTrue(bot.notifier.enabled)
        self.assertTrue(bot.commander.enabled)


if __name__ == "__main__":
    unittest.main()
