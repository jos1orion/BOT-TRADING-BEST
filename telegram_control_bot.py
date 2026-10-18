"""
Bot Telegram de contrôle — pilote le bot crypto BingX ET le bot sniping
Solana depuis Telegram, comme Trojan/BonkBot.

⚠️ SÉCURITÉ CRITIQUE :
Seul le chat_id configuré dans broker_credentials.py (TELEGRAM_CONFIG)
peut envoyer des commandes. Toute autre personne qui trouverait ton bot
Telegram (même en connaissant juste son @username) serait REFUSÉE — sans
ça, n'importe qui pourrait déclencher des achats/ventes réels sur ton
compte. Cette vérification est faite à CHAQUE commande, jamais une fois
pour toutes.

Architecture :
- CryptoLiveBot (BingX) tourne dans un thread d'arrière-plan, "tické"
  toutes les `scan_interval` secondes.
- Le scanner Solana tourne comme tâche asyncio en parallèle (déjà
  asynchrone nativement).
- Les commandes Telegram lisent/modifient l'état de ces deux bots.

⚠️ Ce module n'a pas pu être testé contre l'API Telegram réelle (pas de
réseau ici). La logique d'autorisation et le parsing des commandes ont
été validés avec des objets Update/Context simulés (voir tests).

Installation : pip install python-telegram-bot solders base58
"""

import asyncio
import logging
import os
import threading
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from core.crypto_config import CryptoConfig
from core.brokers.bingx_connector import BingXConnector, BingXOrder
from live_crypto_bot import CryptoLiveBot, TICKER_TO_BINGX

from core.solana.config import SolanaConfig
from core.solana.token_scanner import SolanaTokenScanner
from core.solana.filters import TokenSafetyChecker
from core.solana.simulator import SnipeSimulator

logging.basicConfig(level=logging.INFO,
                     format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("telegram_control_bot")


class FakeManualSignal:
    """Signal fabriqué pour un ordre manuel (/buy), sans stratégie."""
    def __init__(self, entry, stop_loss_pct, take_profit_pct):
        self.direction = "LONG"
        self.entry = entry
        self.stop_loss = entry * (1 - stop_loss_pct / 100)
        self.tp1 = entry * (1 + take_profit_pct / 100)


class SolanaManager:
    """Encapsule le cycle de vie du scanner Solana (start/pause/resume/status)."""

    def __init__(self, config: SolanaConfig):
        self.config = config
        self.scanner = SolanaTokenScanner(config)
        self.checker = TokenSafetyChecker(config)
        self.simulator = SnipeSimulator()
        self.paused = asyncio.Event()  # set = en pause
        self.candidates_seen = 0
        self.candidates_accepted = 0
        self._task = None

    async def _run(self):
        async for event in self.scanner.stream_new_pools():
            if self.paused.is_set():
                continue
            mint_placeholder = "MINT_A_EXTRAIRE_DE_LA_TRANSACTION"
            report = self.checker.check(mint_placeholder)
            self.simulator.log_candidate(mint_placeholder, event.signature, report)
            self.candidates_seen += 1
            if report.passed:
                self.candidates_accepted += 1

    def start(self):
        self._task = asyncio.create_task(self._run())

    def status(self) -> str:
        state = "⏸️ EN PAUSE" if self.paused.is_set() else "▶️ ACTIF"
        return (f"*Solana Sniper* — {state}\n"
                f"Candidats vus: {self.candidates_seen}\n"
                f"Acceptés par les filtres: {self.candidates_accepted}")


def _is_authorized(update: Update) -> bool:
    """Vérifie que la commande vient bien du chat_id autorisé."""
    try:
        from broker_credentials import TELEGRAM_CONFIG
        allowed_chat_id = str(TELEGRAM_CONFIG.get("chat_id", ""))
    except Exception:
        allowed_chat_id = ""

    if not allowed_chat_id:
        logger.error("Aucun chat_id configuré dans broker_credentials.py — "
                     "toutes les commandes sont refusées par sécurité.")
        return False

    return str(update.effective_chat.id) == allowed_chat_id


def authorized_only(handler):
    """Décorateur : bloque toute commande venant d'un chat_id non autorisé.
    Fonctionne sur des méthodes d'instance : (self, update, context)."""
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not _is_authorized(update):
            logger.warning("Commande refusée — chat_id non autorisé: %s",
                            update.effective_chat.id)
            # Réponse volontairement vague, pour ne pas confirmer l'existence du bot
            await update.message.reply_text("Non autorisé.")
            return
        return await handler(self, update, context)
    return wrapper


class TelegramControlBot:
    def __init__(self, crypto_bot: CryptoLiveBot, solana_manager: SolanaManager,
                 bot_token: str, scan_interval: int = 300):
        self.crypto_bot = crypto_bot
        self.solana_manager = solana_manager
        self.scan_interval = scan_interval
        self.app = Application.builder().token(bot_token).build()
        self._register_handlers()

    def _register_handlers(self):
        h = self.app.add_handler
        h(CommandHandler("start", self.cmd_help))
        h(CommandHandler("help", self.cmd_help))
        h(CommandHandler("status", self.cmd_status))
        h(CommandHandler("positions", self.cmd_positions))
        h(CommandHandler("balance", self.cmd_balance))
        h(CommandHandler("pnl", self.cmd_pnl))
        h(CommandHandler("pause_crypto", self.cmd_pause_crypto))
        h(CommandHandler("resume_crypto", self.cmd_resume_crypto))
        h(CommandHandler("pause_solana", self.cmd_pause_solana))
        h(CommandHandler("resume_solana", self.cmd_resume_solana))
        h(CommandHandler("solana_report", self.cmd_solana_report))
        h(CommandHandler("buy", self.cmd_buy))
        h(CommandHandler("sell", self.cmd_sell))

    # ── Commandes ────────────────────────────────────────────────
    @authorized_only
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "*Commandes disponibles*\n\n"
            "/status — état des deux bots\n"
            "/positions — positions BingX ouvertes\n"
            "/balance — cash + valeur du portefeuille\n"
            "/pnl — statistiques du journal de trading\n"
            "/pause\\_crypto, /resume\\_crypto — bot BingX\n"
            "/pause\\_solana, /resume\\_solana — sniper Solana\n"
            "/solana\\_report — résumé des candidats sniping\n"
            "/buy TICKER — achat manuel (ex: `/buy BTC-USD`)\n"
            "/sell TICKER — vente manuelle d'une position ouverte",
            parse_mode="Markdown",
        )

    @authorized_only
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        with self.crypto_bot.lock:
            n_pos = len(self.crypto_bot.open_positions)
            cash = self.crypto_bot.cash
        crypto_state = "⏸️ EN PAUSE" if self.crypto_bot.manual_pause.is_set() else "▶️ ACTIF"
        dd_status = self.crypto_bot.drawdown_guard.status()
        msg = (
            f"*Bot Crypto (BingX)* — {crypto_state}\n"
            f"Mode: `{self.crypto_bot.connector.mode}`\n"
            f"Positions ouvertes: {n_pos}\n"
            f"Cash: `{cash:,.2f}`\n"
            f"Drawdown guard: {dd_status}\n\n"
            f"{self.solana_manager.status()}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    @authorized_only
    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        with self.crypto_bot.lock:
            positions = dict(self.crypto_bot.open_positions)
        if not positions:
            await update.message.reply_text("Aucune position ouverte.")
            return
        lines = ["*Positions ouvertes*"]
        for ticker, pos in positions.items():
            lines.append(f"`{ticker}` x{pos.quantity} @ {pos.entry_price:.4f} "
                         f"(SL={pos.stop_loss:.4f} TP1={pos.tp1:.4f}) [{pos.strategy}]")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    @authorized_only
    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        with self.crypto_bot.lock:
            cash = self.crypto_bot.cash
            equity = cash + sum(p.quantity * p.entry_price
                                 for p in self.crypto_bot.open_positions.values())
        await update.message.reply_text(
            f"Cash: `{cash:,.2f}`\nValeur totale estimée: `{equity:,.2f}`",
            parse_mode="Markdown",
        )

    @authorized_only
    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = self.crypto_bot.journal.compute_stats()
        await update.message.reply_text(f"```\n{stats}\n```", parse_mode="Markdown")

    @authorized_only
    async def cmd_pause_crypto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.crypto_bot.manual_pause.set()
        await update.message.reply_text("⏸️ Bot crypto (BingX) mis en pause. "
                                        "Les positions ouvertes continuent d'être suivies.")

    @authorized_only
    async def cmd_resume_crypto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.crypto_bot.manual_pause.clear()
        await update.message.reply_text("▶️ Bot crypto (BingX) relancé.")

    @authorized_only
    async def cmd_pause_solana(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.solana_manager.paused.set()
        await update.message.reply_text("⏸️ Sniper Solana mis en pause.")

    @authorized_only
    async def cmd_resume_solana(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.solana_manager.paused.clear()
        await update.message.reply_text("▶️ Sniper Solana relancé.")

    @authorized_only
    async def cmd_solana_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(self.solana_manager.simulator.summary().__repr__())

    @authorized_only
    async def cmd_buy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: `/buy BTC-USD`", parse_mode="Markdown")
            return
        ticker = context.args[0].upper()
        bingx_symbol = TICKER_TO_BINGX.get(ticker)
        if not bingx_symbol:
            await update.message.reply_text(
                f"Ticker inconnu: {ticker}. Options: {', '.join(TICKER_TO_BINGX)}")
            return

        with self.crypto_bot.lock:
            if ticker in self.crypto_bot.open_positions:
                await update.message.reply_text(f"Position déjà ouverte sur {ticker}.")
                return

        ticker_data = self.crypto_bot.connector.get_ticker_24h(bingx_symbol)
        if "error" in ticker_data:
            await update.message.reply_text(f"Erreur BingX: {ticker_data['error']}")
            return
        try:
            current_price = float(ticker_data.get("lastPrice") or ticker_data.get("data", {}).get("lastPrice"))
        except (TypeError, ValueError, KeyError):
            await update.message.reply_text(
                "⚠️ Impossible de lire le prix dans la réponse BingX — "
                "vérifier le format exact de get_ticker_24h() (non testé en réel).")
            return

        sig = FakeManualSignal(current_price,
                                self.crypto_bot.config.manual_stop_loss_pct,
                                self.crypto_bot.config.manual_take_profit_pct)
        self.crypto_bot._open_position(ticker, bingx_symbol, "manuel_telegram", sig, current_price)
        await update.message.reply_text(
            f"✅ Achat manuel {ticker} @ {current_price:.4f} "
            f"(SL={sig.stop_loss:.4f} TP1={sig.tp1:.4f})")

    @authorized_only
    async def cmd_sell(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: `/sell BTC-USD`", parse_mode="Markdown")
            return
        ticker = context.args[0].upper()
        with self.crypto_bot.lock:
            pos = self.crypto_bot.open_positions.get(ticker)
        if pos is None:
            await update.message.reply_text(f"Aucune position ouverte sur {ticker}.")
            return

        bingx_symbol = TICKER_TO_BINGX[ticker]
        ticker_data = self.crypto_bot.connector.get_ticker_24h(bingx_symbol)
        try:
            current_price = float(ticker_data.get("lastPrice") or ticker_data.get("data", {}).get("lastPrice"))
        except (TypeError, ValueError, KeyError):
            await update.message.reply_text("⚠️ Impossible de lire le prix BingX.")
            return

        self.crypto_bot._close_position(ticker, pos, current_price, "MANUEL_TELEGRAM")
        await update.message.reply_text(f"✅ Vente manuelle {ticker} @ {current_price:.4f}")

    # ── Boucle crypto en tâche de fond ───────────────────────────
    async def _crypto_loop(self):
        loop = asyncio.get_event_loop()
        while True:
            try:
                await loop.run_in_executor(None, self.crypto_bot.run_once)
            except Exception:
                logger.exception("Erreur dans le cycle crypto")
            await asyncio.sleep(self.scan_interval)

    async def _post_init(self, app):
        self.solana_manager.start()
        asyncio.create_task(self._crypto_loop())
        logger.info("Bot Telegram démarré — boucles crypto et Solana lancées en tâche de fond.")

    def run(self):
        self.app.post_init = self._post_init
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


def main():
    try:
        from broker_credentials import TELEGRAM_CONFIG
    except ImportError:
        print("Configure d'abord broker_credentials.py avec TELEGRAM_CONFIG "
              "(bot_token, chat_id).")
        return

    bot_token = TELEGRAM_CONFIG.get("bot_token")
    if not bot_token:
        print("bot_token manquant dans TELEGRAM_CONFIG.")
        return

    crypto_config = CryptoConfig()
    crypto_config.risk_per_trade = 0.025
    connector = BingXConnector(
        api_key=os.getenv("BINGX_API_KEY", ""),
        api_secret=os.getenv("BINGX_API_SECRET", ""),
        mode=os.getenv("BINGX_MODE", "paper"),
    )
    crypto_bot = CryptoLiveBot(crypto_config, connector, scan_interval_seconds=300)

    solana_config = SolanaConfig()
    solana_manager = SolanaManager(solana_config)

    control_bot = TelegramControlBot(crypto_bot, solana_manager, bot_token,
                                      scan_interval=300)
    control_bot.run()


if __name__ == "__main__":
    main()
