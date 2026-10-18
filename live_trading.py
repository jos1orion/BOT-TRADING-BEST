"""
Mode trading live — connecte les stratégies du bot à MetaTrader 5.

Lance avec :
  python live_trading.py --broker deriv --demo
  python live_trading.py --broker deriv --demo --check   (teste connexion + symboles, sans ordre)
  python live_trading.py --broker xm --demo
  python live_trading.py --broker axiom --demo
"""

import os
import time
import math
import sys
from collections import deque
import argparse
import logging
from datetime import datetime, time as dtime
from pathlib import Path
from typing import List, Dict, Optional

from core.brokers.mt5_connector import MT5Connector, OrderType, AccountMode
from core.brokers.xm_axiom_config import (
    XM_SERVERS, AXIOM_SERVERS, YFINANCE_TO_XM
)
from core.brokers.deriv_config import (
    DERIV_SYMBOL_ALIASES, is_synthetic
)
from core.config import Config
from core.live_dashboard import write_live_dashboard, write_live_dashboard_state
from core.miniapp_commands import drain as drain_miniapp_commands
from core.telegram_commander import TelegramCommander
from core.bot_commands import BotCommands
from core.data import DataFetcher
from core.indicators import Indicators as I
from core.risk import RiskManager
from core.news_filter import EconomicCalendar
from core.notifier import TelegramNotifier
from core.journal import TradeJournal
from core.drawdown_guard import DrawdownGuard
from core.market_filter import MarketFilter, guess_asset_class
from strategies.strategies import BreakoutStrategy, MeanReversionStrategy, TurtleStrategy
from strategies.englobante import EnglobanteHaussiere
from strategies.liquidity_sweep import LiquiditySweepStrategy
from strategies.patterns import (
    PullbackStrategy, BullFlagStrategy, DoubleBottomStrategy,
    InsideBarStrategy, OpeningRangeBreakoutStrategy
)
from core.telegram_api import get_me, wait_for_user_pairing

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('trading_live.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LiveTradingBot:
    """
    Bot de trading live connecté à MetaTrader 5.
    Combine toutes les stratégies du bot avec l'exécution réelle.
    """

    def __init__(self, broker: str = "xm", demo: bool = True, no_telegram: bool = False):
        # Chargement de la config
        try:
            from broker_credentials import (
                XM_CONFIG, AXIOM_CONFIG, DERIV_CONFIG, MT5_PATH, LIVE_TRADING_CONFIG
            )
            self.broker_config = {
                "xm": XM_CONFIG, "axiom": AXIOM_CONFIG, "deriv": DERIV_CONFIG,
            }[broker.lower()]
            self.mt5_path      = MT5_PATH
            self.live_config   = LIVE_TRADING_CONFIG
        except ImportError:
            raise RuntimeError(
                "Fichier broker_credentials.py manquant ou mal configuré.\n"
                "Remplissez vos identifiants dans broker_credentials.py"
            )

        self.demo   = demo
        self.broker = broker.upper()
        self.no_telegram = no_telegram
        self.small_capital_mode = False   # activé dynamiquement après connexion
        mode_key    = "demo" if demo else "real"
        mode        = AccountMode.DEMO if demo else AccountMode.REAL

        # Connecteur MT5
        self.mt5 = MT5Connector(account_mode=mode, simulation=False)

        # Config bot
        self.config = Config(
            risk_per_trade = self.live_config['risk_per_trade_pct'] / 100,
            max_positions  = self.live_config['max_positions'],
        )
        self.data    = DataFetcher(verbose=False)
        self.risk_mgr = RiskManager(self.config)

        # Stratégies actives
        self.strategies = {
            'breakout':       BreakoutStrategy(self.config),
            'englobante':     EnglobanteHaussiere(self.config, variante='sur_ma'),
            'liquidity_sweep': LiquiditySweepStrategy(self.config),
            'mean_reversion': MeanReversionStrategy(self.config),
            'pullback':       PullbackStrategy(self.config),
            'bull_flag':      BullFlagStrategy(self.config),
            'double_bottom':  DoubleBottomStrategy(self.config),
            'inside_bar':     InsideBarStrategy(self.config),
            'orb':            OpeningRangeBreakoutStrategy(self.config),
        }

        # Symboles demandés (noms "canoniques") ; la correspondance avec les noms
        # réels du broker (ex. DE40 → "Germany 40" chez Deriv) est faite à la connexion.
        self.symboles = list(self.live_config['symboles'])
        self.symbol_map: Dict[str, str] = {s: s for s in self.symboles}

        # ── Modules ajoutés : news, notifications, journal, drawdown, filtre marché ──
        self.news = EconomicCalendar(
            buffer_minutes=self.live_config.get('news_buffer_minutes', 30),
            verbose=True,
        )
        self.notifier = TelegramNotifier.from_credentials()
        self.journal = TradeJournal(csv_path=f"trading_journal_live_{broker.lower()}.csv")
        try:
            from broker_credentials import DRAWDOWN_CONFIG
        except ImportError:
            DRAWDOWN_CONFIG = {"daily_limit_pct": 3.0, "weekly_limit_pct": 6.0, "max_consecutive_losses": 5}
        self.drawdown_guard = DrawdownGuard(
            daily_limit_pct=DRAWDOWN_CONFIG['daily_limit_pct'],
            weekly_limit_pct=DRAWDOWN_CONFIG['weekly_limit_pct'],
            max_consecutive_losses=DRAWDOWN_CONFIG['max_consecutive_losses'],
            state_path=Path(__file__).resolve().parent / (
                f"drawdown_state_{broker.lower()}_{mode_key}_"
                f"{self.broker_config[mode_key]['login']}.json"
            ),
        )
        self.market_filter = MarketFilter(data_fetcher=self.data)
        self._known_position_tickets = set()
        self._session_start = datetime.now()
        self.activity = deque(maxlen=80)     # journal d'activité affiché dans le dashboard
        self._last_cycle = None
        # ── Pilotage Telegram ──
        self.user_paused = False             # /pause : plus de nouveaux trades
        self.disabled_symbols = set()        # /exclure : symboles (noms canoniques) à ne plus trader
        self._stop_requested = False         # /stop
        self._cycle_now = False              # force un cycle rapidement après une commande
        self._mt5_lost_alerted = False
        self.commander = TelegramCommander.from_credentials()
        self._validate_telegram_recipients()
        self.commands = BotCommands(self)

    def _validate_telegram_recipients(self) -> None:
        """Remove the bot's own Telegram ID from every destination list."""
        if not self.commander.bot_token:
            return

        ok, bot_info, error = get_me(self.commander.bot_token)
        if not ok:
            logger.warning("Impossible de valider les destinataires Telegram au démarrage: %s", error)
            return

        bot_id = str(bot_info.get("id", ""))
        if not bot_id:
            logger.warning("Telegram getMe n'a pas retourné d'identifiant de bot")
            return

        invalid_lists = []
        for name, recipients in (
            ("notifier", self.notifier.chat_ids),
            ("propriétaires", self.commander.owner_chat_ids),
            ("Mini App", self.commander.miniapp_chat_ids),
        ):
            if bot_id in recipients:
                invalid_lists.append(name)

        self.notifier.chat_ids = [chat_id for chat_id in self.notifier.chat_ids if chat_id != bot_id]
        self.commander.owner_chat_ids = [
            chat_id for chat_id in self.commander.owner_chat_ids if chat_id != bot_id
        ]
        self.commander.miniapp_chat_ids = [
            chat_id for chat_id in self.commander.miniapp_chat_ids if chat_id != bot_id
        ]

        if self.notifier.chat_id == bot_id:
            self.notifier.chat_id = ""
        if self.commander.chat_id == bot_id:
            self.commander.chat_id = ""

        self.notifier.enabled = bool(
            self.notifier.enabled and self.notifier.chat_id and self.notifier.chat_ids
        )
        self.commander.enabled = bool(
            self.commander.enabled
            and self.commander.chat_id
            and self.commander.chat_id in self.commander.owner_chat_ids
        )

        if invalid_lists:
            logger.error(
                "TELEGRAM_OWNER_IDS ou un destinataire Telegram contient l'identifiant du bot; "
                "destinataire supprimé (%s). Remplacez-le par l'identifiant d'un compte humain.",
                ", ".join(invalid_lists),
            )
        if not self.commander.owner_chat_ids:
            logger.error("Aucun propriétaire Telegram humain valide : commandes et alertes désactivées")

    # ────────────────────────────────────────────────────────────
    # CONNEXION
    # ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        """Se connecte au broker via MT5."""
        mode_key  = "demo" if self.demo else "real"
        creds     = self.broker_config[mode_key]

        print(f"\n  Connexion à {self.broker} ({mode_key.upper()})...")

        if creds['login'] == 0:
            print(f"\n  ❌ Identifiants non configurés dans broker_credentials.py")
            print(f"     Remplissez login/password/server pour {self.broker} {mode_key.upper()}")
            return False

        success = self.mt5.connect(
            login    = creds['login'],
            password = creds['password'],
            server   = creds['server'],
            mt5_path = self.mt5_path,
        )
        if success:
            # Capital de départ figé au moment de la connexion : sert de
            # référence pour le drawdown % et le rendement % du dashboard
            # (le solde courant, lui, bouge à chaque trade).
            account = self.mt5.get_account_summary()
            balance = account.get('balance', self.journal.initial_capital)
            self.journal.initial_capital = balance

            # ── MODE AUTONOME PETIT CAPITAL ──
            # Adapte automatiquement les paramètres de trading au capital détecté
            # pour éviter les rejets de marge et les sur-expositions fatales.
            self._apply_small_capital_mode(balance)

            self._resolve_symbols()
            if not self.symbol_map:
                print("  ❌ Aucun des symboles configurés n'existe chez ce broker.")
                return False
        return success

    def _apply_small_capital_mode(self, balance: float):
        """
        Adapte automatiquement les paramètres de trading en fonction du capital.

        ┌──────────────┬──────────────┬──────────────┬───────────┬──────────┐
        │  Capital     │ max_positions│ risk/trade   │ DD jour   │ DD sem.  │
        ├──────────────┼──────────────┼──────────────┼───────────┼──────────┤
        │  ≤ 50$       │      1       │    1.0%      │   5.0%    │  10.0%   │
        │  ≤ 200$      │      1       │    0.8%      │   4.0%    │   8.0%   │
        │  ≤ 500$      │      2       │    0.5%      │   3.0%    │   6.0%   │
        │  > 500$      │   (inchangé) │  (inchangé)  │ (inchangé)│(inchangé)│
        └──────────────┴──────────────┴──────────────┴───────────┴──────────┘

        Sur les très petits comptes, les pourcentages de drawdown doivent être
        plus larges car une seule perte de 0.80$ peut représenter 3% d'un
        compte de 25$, mais reste sans gravité réelle.
        Le min_loss_amount empêche le drawdown guard de se déclencher
        pour des pertes < 1$ en valeur absolue (le % est trompeur).
        """
        if balance <= 50:
            self.small_capital_mode = True
            self.live_config['max_positions'] = 1
            self.live_config['risk_per_trade_pct'] = 1.0
            self.config.risk_per_trade = 0.01
            self.config.max_positions = 1
            self.drawdown_guard.daily_limit_pct = 5.0
            self.drawdown_guard.weekly_limit_pct = 10.0
            self.drawdown_guard.min_loss_amount = 1.0
        elif balance <= 200:
            self.small_capital_mode = True
            self.live_config['max_positions'] = 1
            self.live_config['risk_per_trade_pct'] = 0.8
            self.config.risk_per_trade = 0.008
            self.config.max_positions = 1
            self.drawdown_guard.daily_limit_pct = 4.0
            self.drawdown_guard.weekly_limit_pct = 8.0
            self.drawdown_guard.min_loss_amount = 0.50
        elif balance <= 500:
            self.small_capital_mode = True
            self.live_config['max_positions'] = 2
            self.live_config['risk_per_trade_pct'] = 0.5
            self.config.risk_per_trade = 0.005
            self.config.max_positions = 2

        if self.small_capital_mode:
            print(f"\n  💰 MODE PETIT CAPITAL ACTIVÉ — Balance: {balance:.2f}$")
            print(f"     Positions max     : {self.live_config['max_positions']}")
            print(f"     Risque/trade      : {self.live_config['risk_per_trade_pct']}%")
            print(f"     Drawdown jour max : {self.drawdown_guard.daily_limit_pct}%")
            print(f"     Drawdown sem. max : {self.drawdown_guard.weekly_limit_pct}%")
            print(f"     Les symboles trop lourds (marge > 70% capital) seront ignorés automatiquement.\n")

    def _resolve_symbols(self):
        """Associe chaque symbole configuré à son nom exact chez le broker."""
        aliases = DERIV_SYMBOL_ALIASES if self.broker == "DERIV" else {}
        resolved: Dict[str, str] = {}
        for canon in self.symboles:
            real = self.mt5.resolve_symbol(canon, aliases.get(canon))
            if real:
                resolved[canon] = real
                label = canon if canon == real else f"{canon} → {real}"
                print(f"  ✔ Symbole {label}")
            else:
                print(f"  ⚠️  Symbole {canon} introuvable chez {self.broker} — ignoré "
                      f"(vérifiez le nom dans MT5 → Ctrl+U)")
        self.symbol_map = resolved
        self.symboles = list(resolved.keys())

    # ────────────────────────────────────────────────────────────
    # VÉRIFICATION HORAIRES
    # ────────────────────────────────────────────────────────────

    def _is_trading_hours(self) -> bool:
        """Vérifie si on est dans les heures de trading définies."""
        hours = self.live_config.get('trading_hours')
        if not hours:                      # None = 24h/24 (ex. indices synthétiques)
            return True
        now   = datetime.now().time()
        start = dtime.fromisoformat(hours['start'])
        stop  = dtime.fromisoformat(hours['stop'])
        return start <= now <= stop

    # ────────────────────────────────────────────────────────────
    # CYCLE DE TRADING
    # ────────────────────────────────────────────────────────────

    def _trading_cycle(self):
        """Un cycle complet : scan + mise à jour positions + exécution."""
        timestamp = datetime.now().strftime("%H:%M:%S")

        self._last_cycle = datetime.now()
        if not self._is_trading_hours():
            print(f"  [{timestamp}] Hors heures de trading — pause")
            self._log("Hors heures de trading — en attente")
            return

        print(f"\n  [{timestamp}] ─── Cycle Live ({self.broker}) ───────────────")

        # ── 0bis. Calendrier économique ──────────────────────
        if self.live_config.get('avoid_news', True):
            self.news.load()

        # ── 1. Vérifier les positions ouvertes (SL/TP) ──────
        open_positions = self.mt5.get_open_positions()
        if open_positions:
            print(f"  📂 {len(open_positions)} position(s) ouverte(s)")
            for pos in open_positions:
                icon = '🟢' if pos.profit >= 0 else '🔴'
                print(f"     {icon} {pos.symbol} {pos.type} "
                      f"| Profit: ${pos.profit:+.2f}")

        # Détecter les positions fermées (SL/TP touché côté broker, clôture manuelle…).
        # On croise : positions vues au cycle précédent + trades encore OPEN dans le journal
        # (couvre les redémarrages du bot et les trades clôturés entre deux cycles).
        tracked = set(self._known_position_tickets) | self._journal_open_tickets()
        current_tickets = {p.ticket for p in open_positions}
        closed_tickets = tracked - current_tickets
        for ticket in closed_tickets:
            deal = self.mt5.get_closed_deal_for_position(ticket)
            if not deal:
                continue        # pas encore dans l'historique : on réessaiera au prochain cycle
            pnl = deal['profit']
            icon = '✅' if pnl >= 0 else '❌'
            print(f"  {icon} Position #{ticket} ({deal['symbol']}) fermée [{deal['reason']}] | PnL réel : {pnl:+.2f}")
            self._log(f"{icon} Position #{ticket} {deal['symbol']} fermée ({deal['reason']}) : {pnl:+.2f}")
            self.notifier.notify_trade_closed(deal['symbol'], pnl, 0.0, deal['reason'])
            trade_id = f"{deal['symbol']}_{ticket}"
            if not self.journal.close_trade(trade_id, deal['time'], deal['price'], pnl, deal['reason']):
                # trade ouvert hors du bot (ex. manuellement) : on garde au moins sa clôture
                self.journal.log_trade(
                    trade_id=trade_id, ticker=deal['symbol'], strategy='(hors bot)', direction='?',
                    entry_date=deal['time'], entry_price=0.0, shares=deal['volume'],
                    exit_date=deal['time'], exit_price=deal['price'], exit_reason=deal['reason'],
                    pnl=pnl, status='CLOSED')
            self.drawdown_guard.record_trade_result(pnl)
            self.journal.export_dashboard_snapshot(
                path=f"dashboard_snapshot_{self.broker.lower()}.json",
                name=f"Bot MT5 — {self.broker}",
                market=", ".join(self.symboles),
                period=f"depuis {self._session_start.strftime('%Y-%m-%d')}",
            )
            self._known_position_tickets.discard(ticket)
        # on garde les positions ouvertes + celles fermées dont le PnL n'est pas encore dans l'historique
        self._known_position_tickets = set(current_tickets) | (self._known_position_tickets & closed_tickets)

        # Vérifier le drawdown après le traitement des clôtures afin de ne pas
        # perdre une perte réalisée pendant que le bot était arrêté.
        account = self.mt5.get_account_summary()
        equity = account.get('equity')
        if not isinstance(equity, (int, float)) or not math.isfinite(equity) or equity <= 0:
            message = "Equity MT5 indisponible ou invalide — nouvelles entrées bloquées"
            logger.error(message)
            self._log(f"⛔ {message}")
            self.notifier.notify_error("Protection du risque", message)
            return

        allowed, dd_reason = self.drawdown_guard.check(equity)
        if not allowed:
            print(f"  ⛔ {dd_reason}")
            self._log(f"⛔ {dd_reason}")
            self.notifier.notify_pause(dd_reason)
            return

        open_risk = self._calculate_open_positions_risk(open_positions)
        if open_risk is None:
            message = "Risque des positions ouvertes impossible à calculer (stop-loss ou données MT5 manquants) — nouvelles entrées bloquées"
            logger.error(message)
            self._log(f"⛔ {message}")
            self.notifier.notify_error("Limite de risque ouvert", message)
            return
        max_open_risk_pct = self.live_config.get('max_total_open_risk_pct', 3.0)
        if (
            not isinstance(max_open_risk_pct, (int, float))
            or not math.isfinite(max_open_risk_pct)
            or max_open_risk_pct < 0
        ):
            message = "Limite de risque total ouvert invalide — nouvelles entrées bloquées"
            logger.error(message)
            self._log(f"⛔ {message}")
            self.notifier.notify_error("Limite de risque ouvert", message)
            return
        max_open_risk = equity * max_open_risk_pct / 100
        if open_risk >= max_open_risk:
            message = (
                f"Risque ouvert {open_risk:.2f} atteint la limite "
                f"{max_open_risk_pct:.2f}% "
                f"({max_open_risk:.2f}) — aucune nouvelle position"
            )
            self._log(f"⛔ {message}")
            print(f"  ⛔ {message}")
            return

        # ── Repos demandé depuis Telegram : on continue de suivre les positions, mais aucun nouveau trade
        if self.user_paused:
            self._log("⏸ Repos (Telegram) — aucun nouveau trade")
            print("  ⏸ Bot en repos (commande Telegram) — pas de nouveau trade")
            return

        # ── 2. Scanner les signaux ───────────────────────────
        signals_found = []
        timeframe = self.live_config.get('timeframe', 'H1')

        for canon in self.symboles:
            if canon in self.disabled_symbols:       # exclu via /exclure
                continue
            symbol = self.symbol_map[canon]          # nom exact chez le broker
            # Marché fermé (week-end Forex, session indices…) → on saute
            if not self.mt5.is_symbol_tradable(symbol):
                continue
            # Données MT5 en priorité, sinon yfinance
            df = self.mt5.get_ohlcv_mt5(symbol, timeframe, count=300)
            if df is None:
                # Fallback yfinance (symbole à convertir)
                yf_symbol = {v: k for k, v in YFINANCE_TO_XM.items()}.get(canon)
                if yf_symbol:
                    df = self.data.get_ohlcv(yf_symbol, period='3mo')

            if df is None or len(df) < 60:
                continue

            # Filtre de marché adapté à la classe d'actif du symbole
            # (Forex/indices EU n'utilisent pas SPY/QQQ comme les actions US)
            asset_class = 'synthetic' if is_synthetic(symbol) else guess_asset_class(canon)
            market_condition = self.market_filter.get_condition(symbol, df_self=df, asset_class=asset_class)

            # Tester chaque stratégie
            for strat_name, strat in self.strategies.items():
                try:
                    if strat_name == 'breakout':
                        sig = strat.generate_signal(symbol, df, market_condition)
                    elif strat_name == 'englobante':
                        sig_e = strat.generate_signal(symbol, df)
                        from strategies.strategies import Signal
                        sig = Signal(ticker=symbol, strategy="Englobante Haussière")
                        sig.direction = sig_e.direction
                        sig.strength  = sig_e.strength
                        sig.entry     = sig_e.entry
                        sig.stop_loss = sig_e.stop_loss
                        sig.tp1       = sig_e.tp1
                        sig.tp2       = sig_e.tp2
                        sig.risk_reward = sig_e.risk_reward
                        sig.reason    = sig_e.reason
                    elif strat_name == 'liquidity_sweep':
                        sig_ls = strat.generate_signal(symbol, df)
                        from strategies.strategies import Signal
                        sig = Signal(ticker=symbol, strategy="Liquidity Sweep")
                        sig.direction = sig_ls.direction
                        sig.strength  = sig_ls.strength
                        sig.entry     = sig_ls.entry
                        sig.stop_loss = sig_ls.stop_loss
                        sig.tp1       = sig_ls.tp1
                        sig.tp2       = sig_ls.tp2
                        sig.risk_reward = sig_ls.risk_reward
                        sig.reason    = sig_ls.reason
                    elif strat_name == 'mean_reversion':
                        sig = strat.generate_signal(symbol, df, market_condition)
                    elif strat_name in ('pullback', 'bull_flag', 'double_bottom', 'inside_bar', 'orb'):
                        sig = strat.generate_signal(symbol, df)
                    else:
                        continue

                    if sig.direction and sig.strength >= 65:
                        signals_found.append((symbol, sig))
                except Exception as e:
                    logger.warning(f"Erreur stratégie {strat_name} / {symbol}: {e}")

        # ── 3. Exécuter les meilleurs signaux ────────────────
        signals_found.sort(key=lambda x: x[1].strength, reverse=True)
        self._log(f"Scan terminé : {len(signals_found)} signal(s) ≥ 65/100 sur {len(self.symboles)} symbole(s)")

        for symbol, sig in signals_found[:2]:  # Max 2 nouveaux trades par cycle
            # Vérifier qu'on n'est pas déjà en position sur ce symbole
            already_in = any(p.symbol == symbol for p in open_positions)
            if already_in:
                continue

            # Vérifier les limites de positions
            if len(open_positions) >= self.live_config['max_positions']:
                print(f"  ⚠️  Limite de {self.live_config['max_positions']} positions atteinte")
                break

            # Filtre d'actualités économiques (NFP, FOMC, CPI...)
            if self.live_config.get('avoid_news', True) and not is_synthetic(symbol):
                blocked, event = self.news.is_blocked(symbol)
                if blocked:
                    msg = f"News à fort impact : {event.title} @ {event.date.strftime('%H:%M UTC')}"
                    print(f"  📅 {symbol} bloqué — {msg}")
                    self._log(f"📅 {symbol} bloqué : {msg}")
                    self.notifier.notify_news_block(symbol, event.title, event.date.strftime('%H:%M UTC'))
                    continue

            # Calculer les lots (le slippage réduit la taille de position pour rester prudent,
            # important sur les indices volatils comme le DAX/US100)
            lots = self.mt5.calculate_lots(
                symbol       = symbol,
                entry        = sig.entry,
                stop_loss    = sig.stop_loss,
                risk_pct     = self.live_config['risk_per_trade_pct'] / 100,
                slippage_pct = self.config.slippage_pct,
            )

            if lots <= 0:        # lot minimum du broker incompatible avec le risque voulu
                continue

            candidate_risk = self.mt5.calculate_position_risk(
                symbol=symbol,
                volume=lots,
                entry=sig.entry,
                stop_loss=sig.stop_loss,
                slippage_pct=self.config.slippage_pct,
            )
            if candidate_risk is None:
                message = f"{symbol}: risque du nouveau trade impossible à calculer — ordre ignoré"
                logger.error(message)
                self._log(f"⛔ {message}")
                continue
            if open_risk + candidate_risk > max_open_risk:
                message = (
                    f"{symbol}: risque estimé {open_risk + candidate_risk:.2f} "
                    f"> limite {max_open_risk:.2f} — ordre ignoré"
                )
                self._log(f"⛔ {message}")
                print(f"  ⛔ {message}")
                continue

            # Confirmer et envoyer l'ordre
            print(f"\n  🟢 SIGNAL : {symbol} {sig.direction} | {sig.strategy}")
            print(f"     Force : {sig.strength:.0f}/100 | R/R : {sig.risk_reward:.1f}:1")
            print(f"     Lots  : {lots} | SL : {sig.stop_loss:.5f} | TP : {sig.tp1:.5f}")

            order_type = OrderType.BUY if sig.direction == 'LONG' else OrderType.SELL
            order = self.mt5.send_market_order(
                symbol      = symbol,
                order_type  = order_type,
                volume      = lots,
                stop_loss   = sig.stop_loss,
                take_profit = sig.tp1,
                comment     = f"Bot_{sig.strategy[:10]}"
            )

            if order.status == "FILLED" or "SIMULATION" in order.status:
                logger.info(
                    f"ORDRE EXÉCUTÉ : {symbol} {sig.direction} "
                    f"{lots}L @ {order.filled_price:.5f} "
                    f"SL:{sig.stop_loss:.5f} TP:{sig.tp1:.5f}"
                )
                self._log(f"🟢 {sig.direction} {symbol} {lots} lot(s) @ {order.filled_price:.5g} "
                          f"[{sig.strategy}] SL {sig.stop_loss:.5g} TP {sig.tp1:.5g}")
                self.notifier.notify_trade_opened(
                    symbol, sig.strategy, sig.direction, lots, order.filled_price, sig.stop_loss, sig.tp1)
                pos_id = order.position_id or order.ticket
                self._known_position_tickets.add(pos_id)
                refreshed_positions = self.mt5.get_open_positions()
                open_positions = refreshed_positions
                if not any(
                    position.ticket in (order.position_id, order.ticket)
                    for position in refreshed_positions
                ):
                    open_risk = max_open_risk
                    warning = "Position exécutée non confirmée dans la liste MT5; les entrées restantes de ce cycle sont bloquées"
                    logger.error(warning)
                    self._log(f"⛔ {warning}")
                    self.notifier.notify_error("Limite de risque ouvert", warning)
                else:
                    refreshed_risk = self._calculate_open_positions_risk(refreshed_positions)
                    if refreshed_risk is None:
                        open_risk = max_open_risk
                        warning = "Risque total après exécution impossible à confirmer; les entrées restantes de ce cycle sont bloquées"
                        logger.error(warning)
                        self._log(f"⛔ {warning}")
                        self.notifier.notify_error("Limite de risque ouvert", warning)
                    else:
                        open_risk = refreshed_risk
                self.journal.log_trade(
                    trade_id=f"{symbol}_{pos_id}",
                    ticker=symbol, strategy=sig.strategy, direction=sig.direction,
                    entry_date=datetime.now(), entry_price=order.filled_price, shares=lots,
                    stop_loss=sig.stop_loss, tp1=sig.tp1, tp2=sig.tp2, status='OPEN')
                if open_risk >= max_open_risk:
                    break
            else:
                logger.error(f"ERREUR ORDRE {symbol}: {order.error}")
                self._log(f"❌ Ordre refusé {symbol} : {order.error}")
                self.notifier.notify_error(f"Ordre {symbol}", order.error)

    # ────────────────────────────────────────────────────────────
    # BOUCLE PRINCIPALE
    # ────────────────────────────────────────────────────────────

    def _journal_open_tickets(self) -> set:
        """Tickets de position des trades encore OPEN dans le journal (trade_id = SYMBOLE_ticket)."""
        out = set()
        for tid in self.journal.open_trade_ids():
            try:
                out.add(int(tid.rsplit('_', 1)[1]))
            except (IndexError, ValueError):
                pass
        return out

    def _calculate_open_positions_risk(self, positions) -> Optional[float]:
        """Somme le risque jusqu'aux stops; None signifie qu'une position est non mesurable."""
        total_risk = 0.0
        for position in positions:
            if position.stop_loss <= 0:
                logger.error(
                    f"Position #{position.ticket} ({position.symbol}) sans stop-loss: "
                    "risque ouvert impossible à borner"
                )
                return None
            risk = self.mt5.calculate_position_risk(
                symbol=position.symbol,
                volume=position.volume,
                entry=position.open_price,
                stop_loss=position.stop_loss,
                slippage_pct=self.config.slippage_pct,
            )
            if risk is None or risk < 0:
                return None
            total_risk += risk
        return total_risk

    def _log(self, msg: str):
        """Ajoute une ligne horodatée au journal d'activité du dashboard."""
        self.activity.append(f"{datetime.now():%H:%M:%S}  {msg}")

    def _update_dashboard(self):
        """Réécrit la page de suivi HTML (à ouvrir dans Chrome)."""
        try:
            account = self.mt5.get_account_summary() or {}
            positions = self.mt5.get_open_positions()
            closed_rows = self.journal._read_all()
            stats = self.journal.compute_stats()
            guard_status = ("⏸ REPOS demandé via Telegram — " if self.user_paused else "") + self.drawdown_guard.status
            symbols = list(self.symbol_map.values())
            activity = list(self.activity)
            chart_symbol = symbols[0] if symbols else ""
            candles = []
            if chart_symbol:
                frame = self.mt5.get_ohlcv_mt5(chart_symbol, "H1", count=90)
                if frame is not None:
                    candles = [
                        {"time": index.isoformat(), "open": float(row["Open"]),
                         "high": float(row["High"]), "low": float(row["Low"]),
                         "close": float(row["Close"])}
                        for index, row in frame.tail(90).iterrows()
                    ]
            markers = []
            for position in positions:
                if position.symbol != chart_symbol:
                    continue
                markers.extend([
                    {"label": "Entrée", "price": float(position.open_price)},
                    {"label": "SL", "price": float(position.stop_loss)},
                    {"label": "TP", "price": float(position.take_profit)},
                ])
            market_chart = {"symbol": chart_symbol, "timeframe": "H1", "candles": candles,
                            "markers": markers}
            info = {
                    'started': self._session_start.strftime('%d/%m/%Y %H:%M'),
                    'last_cycle': self._last_cycle.strftime('%H:%M:%S') if self._last_cycle else '—',
                    'next_scan': (f"{max(0, int(self.live_config['scan_interval_seconds'] - (datetime.now() - self._last_cycle).total_seconds()))} s"
                                  if self._last_cycle else '—'),
                    'timeframe': self.live_config.get('timeframe', 'H1'),
                    'interval': self.live_config.get('scan_interval_seconds'),
                    'risk': self.live_config.get('risk_per_trade_pct'),
                    'max_positions': self.live_config.get('max_positions'),
                    'max_total_open_risk_pct': self.live_config.get('max_total_open_risk_pct', 3.0),
                    'daily_limit_pct': self.drawdown_guard.daily_limit_pct,
                    'weekly_limit_pct': self.drawdown_guard.weekly_limit_pct,
                    'consecutive_losses': self.drawdown_guard._consecutive_losses,
                    'max_consecutive_losses': self.drawdown_guard.max_consecutive_losses,
                    'daily_drawdown_pct': (
                        max(0.0, (self.drawdown_guard._day_start_equity
                                  - float(account.get('equity') or 0))
                            / self.drawdown_guard._day_start_equity * 100)
                        if self.drawdown_guard._day_start_equity > 0 else 0.0
                    ),
                    'weekly_drawdown_pct': (
                        max(0.0, (self.drawdown_guard._week_start_equity
                                  - float(account.get('equity') or 0))
                            / self.drawdown_guard._week_start_equity * 100)
                        if self.drawdown_guard._week_start_equity > 0 else 0.0
                    ),
                    'hours': (f"{self.live_config['trading_hours']['start']} → {self.live_config['trading_hours']['stop']}"
                              if self.live_config.get('trading_hours') else '24h/24'),
                    'limits': (f"jour -{self.drawdown_guard.daily_limit_pct}% · semaine -{self.drawdown_guard.weekly_limit_pct}% · "
                               f"{self.drawdown_guard.max_consecutive_losses} pertes d'affilée · "
                               f"risque ouvert max {self.live_config.get('max_total_open_risk_pct', 3.0)}%"),
                }
            path = write_live_dashboard(
                path=f"dashboard_live_{self.broker.lower()}.html",
                broker=self.broker,
                mode="DEMO" if self.demo else "REAL",
                account=account,
                positions=positions,
                closed_rows=closed_rows,
                stats=stats,
                guard_status=guard_status,
                symbols=symbols,
                activity=activity,
                info=info,
            )
            write_live_dashboard_state(
                path=f"dashboard_live_{self.broker.lower()}.json",
                broker=self.broker,
                mode="DEMO" if self.demo else "REAL",
                account=account,
                positions=positions,
                closed_rows=closed_rows,
                stats=stats,
                guard_status=guard_status,
                symbols=symbols,
                activity=activity,
                info=info,
                connections={
                    'bot': True,
                    'mt5': account.get('equity') is not None,
                },
                market_chart=market_chart,
            )
            return path
        except Exception as e:
            logger.warning(f"Dashboard non mis à jour : {e}")
            return None

    def _wait(self, seconds: float):
        """Attend `seconds` en traitant les commandes Telegram chaque seconde."""
        end = time.time() + seconds
        while time.time() < end and not self._stop_requested and not self._cycle_now:
            self._drain_miniapp_commands()
            for command in self.commander.drain():
                reply = self.commands.handle(command.text)
                self.commander.reply(
                    reply,
                    keyboard=command.text.lower().startswith(("/start", "/aide", "/help")),
                    chat_id=command.chat_id,
                )
                self._update_dashboard()
            time.sleep(1)
        self._cycle_now = False

    def _drain_miniapp_commands(self):
        """Apply Mini App requests in the MT5-owning main thread only."""
        path = f"miniapp_commands_{self.broker.lower()}.jsonl"
        requests = drain_miniapp_commands(path)
        for request in requests:
            action = request.get("action")
            if action == "pause":
                self.commands.handle("/pause")
                self._log("Mini App : bot mis en repos")
            elif action == "resume":
                self.commands.handle("/reprise")
                self._log("Mini App : trading repris")
        if requests:
            self._update_dashboard()

    def _check_connection(self):
        """Alerte Telegram si MT5 devient illisible (MT5 fermé, déconnecté…) puis quand ça revient."""
        ok = bool(self.mt5.get_account_summary())
        if not ok and not self._mt5_lost_alerted:
            self._mt5_lost_alerted = True
            self._log("⚠️ Connexion MT5 perdue")
            self.notifier.send("⚠️ Connexion à MetaTrader 5 perdue : MT5 est-il ouvert et connecté ?", parse_mode=None)
        elif ok and self._mt5_lost_alerted:
            self._mt5_lost_alerted = False
            self._log("✅ Connexion MT5 rétablie")
            self.notifier.send("✅ Connexion à MetaTrader 5 rétablie.", parse_mode=None)

    def check(self):
        """Diagnostic : connexion, solde, symboles, spread, lot calculé — AUCUN ordre."""
        if not self.connect():
            print("\n  ❌ Connexion échouée. Vérifiez login / mot de passe / serveur.")
            return
        self.mt5.print_account_dashboard()
        print("\n  Diagnostic des symboles :")
        for canon, real in self.symbol_map.items():
            px = self.mt5.get_price(real)
            ok = self.mt5.is_symbol_tradable(real)
            df = self.mt5.get_ohlcv_mt5(real, self.live_config.get('timeframe', 'H1'), count=300)
            bars = 0 if df is None else len(df)
            spread = px['spread'] if px else 'n/a'
            print(f"   {real:<28} tradable={'oui' if ok else 'NON (marché fermé?)'} "
                  f"| spread={spread} pts | bougies={bars}")
            if px and ok:
                dist = px['ask'] * 0.005
                lots = self.mt5.calculate_lots(real, px['ask'], px['ask'] - dist,
                                               self.live_config['risk_per_trade_pct'] / 100,
                                               self.config.slippage_pct)
                print(f"      lot pour SL à 0.5% et risque {self.live_config['risk_per_trade_pct']}% : {lots}")
        self.mt5.disconnect()

    def _verify_telegram(self) -> bool:
        """
        Vérifie la connexion Telegram au démarrage.
        Si le chat_id est invalide (ex: égal à l'ID du bot), lance l'appairage interactif.
        Retourne True si Telegram est fonctionnel, False sinon.
        """
        if self.no_telegram:
            print("  ⚠️  Telegram désactivé par --no-telegram (non recommandé)")
            self.notifier.enabled = False
            self.commander.enabled = False
            return True

        # 1. Vérifier que le token est valide
        ok_token, bot_info, err_token = get_me(self.notifier.bot_token or "")
        if not ok_token:
            print(f"\n  ❌ TELEGRAM : Token invalide — {err_token}")
            print("  ╔════════════════════════════════════════════════════╗")
            print("  ║  CONFIGURATION TELEGRAM REQUISE                   ║")
            print("  ╠════════════════════════════════════════════════════╣")
            print("  ║  1. Ouvrez Telegram → cherchez @BotFather         ║")
            print("  ║  2. Envoyez /newbot et suivez les instructions    ║")
            print("  ║  3. Copiez le token dans .env :                   ║")
            print("  ║     TELEGRAM_BOT_TOKEN=votre_token                ║")
            print("  ╚════════════════════════════════════════════════════╝")
            return False

        bot_id = str(bot_info.get("id", ""))
        bot_username = bot_info.get("username", "Bot")
        print(f"  📱 Bot Telegram : @{bot_username} (OK)")

        # 2. Vérifier que le chat_id n'est pas celui du bot
        current_chat_id = self.notifier.chat_id
        needs_pairing = (
            not current_chat_id
            or current_chat_id == bot_id
            or current_chat_id in ("VOTRE_CHAT_ID", "0", "")
        )

        if not needs_pairing:
            # 3. Tester l'envoi d'un message
            valid, diag, _ = self.notifier.verify_connection()
            if valid:
                print(f"  ✅ Telegram vérifié — {diag}")
                return True
            else:
                print(f"  ⚠️  Chat ID actuel invalide : {diag}")
                needs_pairing = True

        # 4. Appairage interactif
        if needs_pairing:
            if current_chat_id == bot_id:
                print(f"\n  ⚠️  Le TELEGRAM_CHAT_ID ({current_chat_id}) est l'ID du bot lui-même !")
                print("     Un bot ne peut pas s'envoyer des messages. Il faut votre chat ID personnel.\n")

            new_chat_id = wait_for_user_pairing(
                token=self.notifier.bot_token,
                bot_username=bot_username,
                timeout_seconds=120,
            )

            if new_chat_id:
                # Mettre à jour les objets en mémoire
                self.notifier.chat_id = new_chat_id
                self.notifier.enabled = True
                self.commander.chat_id = new_chat_id
                self.commander.enabled = True
                print(f"  ✅ Chat ID mis à jour : {new_chat_id}")
                print(f"     Le fichier .env a été mis à jour automatiquement.\n")
                return True
            else:
                print("\n  ❌ Appairage Telegram échoué. Le bot ne peut pas fonctionner sans Telegram.")
                print("     Relancez le bot et envoyez un message à @" + bot_username)
                print("     ou utilisez --no-telegram pour forcer le lancement (non recommandé).\n")
                return False

    def run(self):
        """Lance la boucle de trading live."""
        # ── Vérification Telegram obligatoire ──
        if not self._verify_telegram():
            return

        if not self.connect():
            print("\n  ❌ Connexion échouée. Vérifiez broker_credentials.py")
            return

        interval = self.live_config['scan_interval_seconds']
        mode_str = '🟡 DÉMO' if self.demo else '🔴 RÉEL'
        capital_label = " [💰 Petit Capital]" if self.small_capital_mode else ""

        print(f"\n  🤖 Bot Live démarré — {self.broker} {mode_str}{capital_label}")
        print(f"  Symboles : {', '.join(self.symbol_map.values())}")
        print(f"  Scan toutes les {interval}s | Ctrl+C pour arrêter\n")
        dash = self._update_dashboard()
        if dash:
            print(f"  🌐 Suivi live : ouvrez {os.path.abspath(dash)} dans Chrome")
        if self.commander.start():
            print("  📱 Pilotage Telegram actif (envoyez /aide à votre bot)")

            # Notification de démarrage enrichie
            balance = self.mt5.account_info.get('balance', 0)
            startup_msg = (
                f"🤖 Bot Live démarré — {self.broker} {mode_str}\n"
                f"💰 Balance: {balance:.2f}$\n"
            )
            if self.small_capital_mode:
                startup_msg += (
                    f"⚡ Mode Petit Capital actif\n"
                    f"   Positions max: {self.live_config['max_positions']}\n"
                    f"   Risque/trade: {self.live_config['risk_per_trade_pct']}%\n"
                )
            startup_msg += (
                f"{len(self.symbol_map)} symbole(s) surveillé(s).\n"
                f"Tapez /aide pour les commandes."
            )
            self.commander.reply_all(startup_msg, keyboard=True)
        elif not self.no_telegram:
            self.notifier.send(
                f"🤖 Bot Live démarré — {self.broker} {mode_str}\n"
                f"Symboles: {', '.join(self.symboles)}"
            )

        try:
            while not self._stop_requested:
                self._drain_miniapp_commands()
                try:
                    self._trading_cycle()
                except Exception as e:
                    logger.error(f"Erreur dans le cycle de trading : {e}")
                    self._log(f"❌ Erreur cycle : {e}")
                    self.notifier.notify_error("Cycle de trading", str(e))
                self._check_connection()
                self._update_dashboard()
                self.mt5.print_account_dashboard()
                print(f"\n  🛡️  Drawdown Guard : {self.drawdown_guard.status}")
                self.journal.print_summary()
                self._wait(interval)
            print("\n  ⛔ Arrêt demandé depuis Telegram.")
            self.notifier.send("⛔ Bot Live arrêté (commande /stop). Les trades ouverts restent protégés par leur SL/TP.", parse_mode=None)
        except KeyboardInterrupt:
            print("\n\n  ⛔ Bot arrêté.")
            self.notifier.send("⛔ Bot Live arrêté manuellement.")
        finally:
            self.commander.stop()
            path = self.journal.export_excel(f"trading_journal_live_{self.broker.lower()}.xlsx")
            print(f"  📁 Journal exporté : {path}")
            self.mt5.disconnect()
            print("  Déconnecté de MetaTrader 5.\n")


# ══════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot de Trading Live MT5")
    parser.add_argument('--broker',  choices=['deriv', 'xm', 'axiom'], default='deriv',
                        help='Broker à utiliser (défaut: deriv)')
    parser.add_argument('--check',   action='store_true', default=False,
                        help='Teste connexion + symboles + lots, sans passer aucun ordre')
    parser.add_argument('--demo',    action='store_true', default=True,
                        help='Utiliser le compte démo (RECOMMANDÉ)')
    parser.add_argument('--real',    action='store_true', default=False,
                        help='Utiliser le compte réel ⚠️ ')
    parser.add_argument('--no-telegram', action='store_true', default=False,
                        help='Désactiver Telegram (non recommandé — le bot fonctionnera sans alertes)')
    args = parser.parse_args()

    use_demo = not args.real

    if not use_demo:
        print("\n  ⚠️  Vous avez choisi le mode RÉEL.")
        print("  Votre argent réel sera engagé.")
        confirm = input("  Tapez 'CONFIRMER RÉEL' pour continuer : ")
        if confirm != "CONFIRMER RÉEL":
            print("  Annulé. Relancez sans --real pour le mode démo.")
            exit(0)

    bot = LiveTradingBot(broker=args.broker, demo=use_demo, no_telegram=args.no_telegram)
    if args.check:
        bot.check()
    else:
        bot.run()
