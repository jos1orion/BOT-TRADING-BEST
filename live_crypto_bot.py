"""
Bot crypto autonome — BingX, mode PAPER par défaut.
════════════════════════════════════════════════════

Boucle : scan périodique du watchlist → génération de signal
(Mean Reversion / Liquidity Sweep) → sizing selon risk_per_trade →
vérification drawdown guard → ouverture/suivi de position → journal +
notifications Telegram.

⚠️ LIMITES IMPORTANTES DE CETTE VERSION :
- Tourne en mode PAPER par défaut (ordres simulés). Passer en argent réel
  nécessite de changer BINGX_MODE=live dans .env, EN CONNAISSANCE DE CAUSE,
  après avoir vu des résultats de paper trading convaincants sur plusieurs
  jours/semaines — pas avant.
- L'état des positions est sauvegardé dans `crypto_bot_state.json` pour
  survivre à un redémarrage, mais ce n'est pas une base de données
  transactionnelle : en cas de crash pendant une écriture, une position
  peut être désynchronisée. Vérifier manuellement de temps en temps.
- Les données de marché viennent de l'API BingX (klines) — le format
  exact de la réponse n'a pas pu être validé dans cet environnement de
  développement (pas d'accès réseau). Vérifier `_klines_to_dataframe()`
  contre une vraie réponse avant usage réel et ajuster si besoin.
- Une seule position par ticker à la fois, pas de pyramidage.
- Aucune limite de nombre de cycles : le script tourne jusqu'à Ctrl+C ou
  jusqu'à ce que le drawdown guard le mette en pause (pause = le bot
  continue de tourner mais n'ouvre plus de nouvelles positions).
"""

import argparse
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from core.crypto_config import CryptoConfig
from core.brokers.bingx_connector import BingXConnector, BingXOrder
from core.drawdown_guard import DrawdownGuard
from core.journal import TradeJournal
from core.notifier import TelegramNotifier
from dashboard import generate_dashboard
from strategies.strategies import MeanReversionStrategy
from strategies.liquidity_sweep import LiquiditySweepStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("crypto_bot")

STATE_PATH = "crypto_bot_state.json"

# Mapping ticker interne (yfinance-like, pour cohérence avec le backtest)
# -> symbole BingX réel utilisé pour les ordres/klines.
TICKER_TO_BINGX = {
    "BTC-USD": "BTC-USDT", "ETH-USD": "ETH-USDT", "SOL-USD": "SOL-USDT",
    "BNB-USD": "BNB-USDT", "XRP-USD": "XRP-USDT", "ADA-USD": "ADA-USDT",
    "DOGE-USD": "DOGE-USDT", "AVAX-USD": "AVAX-USDT",
}


@dataclass
class OpenPosition:
    ticker: str
    strategy: str
    direction: str
    entry_price: float
    quantity: float
    stop_loss: float
    tp1: float
    entry_time: str
    trade_id: str


class CryptoLiveBot:
    def __init__(self, config: CryptoConfig, connector: BingXConnector,
                 scan_interval_seconds: int = 300):
        self.config = config
        self.connector = connector
        self.scan_interval = scan_interval_seconds

        self.strategies = {
            "mean_reversion": MeanReversionStrategy(config),
            "liquidity_sweep": LiquiditySweepStrategy(config),
        }

        self.drawdown_guard = DrawdownGuard(
            daily_limit_pct=config.drawdown_daily_limit_pct,
            weekly_limit_pct=config.drawdown_weekly_limit_pct,
            max_consecutive_losses=config.max_consecutive_losses,
        )
        self.journal = TradeJournal(csv_path="crypto_trading_journal.csv")
        self.notifier = TelegramNotifier.from_credentials()

        self.cash: float = config.initial_capital
        self.open_positions: Dict[str, OpenPosition] = {}
        self.lock = threading.Lock()          # protège cash/open_positions
        self.manual_pause = threading.Event() # pilotable depuis l'extérieur (ex: Telegram)
        self._load_state()

    # ── Persistance ──────────────────────────────────────────────
    def _load_state(self):
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH) as f:
                    state = json.load(f)
                self.cash = state.get("cash", self.config.initial_capital)
                self.open_positions = {
                    k: OpenPosition(**v) for k, v in state.get("positions", {}).items()
                }
                logger.info("État restauré: cash=%.2f, %d position(s) ouverte(s)",
                            self.cash, len(self.open_positions))
            except Exception as e:
                logger.warning("Impossible de charger l'état précédent (%s) — repart de zéro", e)

    def _save_state(self):
        state = {
            "cash": self.cash,
            "positions": {k: asdict(v) for k, v in self.open_positions.items()},
            "last_update": datetime.now().isoformat(),
        }
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)

    # ── Données de marché (BingX) ───────────────────────────────
    def _klines_to_dataframe(self, raw: dict) -> Optional[pd.DataFrame]:
        """
        Convertit la réponse BingX klines en DataFrame OHLCV standard.

        ⚠️ Le format exact de `raw["data"]` (liste de listes vs liste de
        dicts, ordre des champs) n'a pas pu être vérifié sans réseau.
        Cette fonction gère les deux formats les plus courants chez les
        exchanges crypto — à ajuster si BingX renvoie autre chose (imprimer
        `raw` une première fois pour vérifier).
        """
        data = raw.get("data") if isinstance(raw, dict) else None
        if not data:
            logger.error("Réponse klines inattendue: %s", raw)
            return None

        rows = []
        try:
            if isinstance(data[0], dict):
                for k in data:
                    rows.append({
                        "Open": float(k.get("open", k.get("o"))),
                        "High": float(k.get("high", k.get("h"))),
                        "Low": float(k.get("low", k.get("l"))),
                        "Close": float(k.get("close", k.get("c"))),
                        "Volume": float(k.get("volume", k.get("v", 0))),
                        "time": k.get("time", k.get("openTime", k.get("t"))),
                    })
            else:  # liste de listes, style [time, open, high, low, close, volume, ...]
                for k in data:
                    rows.append({
                        "time": k[0], "Open": float(k[1]), "High": float(k[2]),
                        "Low": float(k[3]), "Close": float(k[4]), "Volume": float(k[5]),
                    })
        except (IndexError, ValueError, TypeError) as e:
            logger.error("Erreur de parsing klines (%s) — vérifier _klines_to_dataframe()", e)
            return None

        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], unit="ms", errors="coerce")
        df = df.set_index("time").sort_index()
        return df[["Open", "High", "Low", "Close", "Volume"]]

    def get_market_data(self, bingx_symbol: str) -> Optional[pd.DataFrame]:
        raw = self.connector.get_klines(bingx_symbol, interval="1h", limit=300)
        if "error" in raw:
            logger.error("Erreur API klines %s: %s", bingx_symbol, raw["error"])
            return None
        return self._klines_to_dataframe(raw)

    # ── Sizing (fractionnaire, adapté crypto) ───────────────────
    def calculate_quantity(self, entry: float, stop_loss: float) -> float:
        risk_amount = self.cash * self.config.risk_per_trade
        risk_per_unit = abs(entry - stop_loss)
        if risk_per_unit <= 0:
            return 0.0
        qty = risk_amount / risk_per_unit
        # Plafond : jamais plus de 20% du capital sur une seule position
        max_value = self.cash * 0.20
        max_qty = max_value / entry if entry > 0 else 0
        return round(min(qty, max_qty), 6)

    # ── Boucle principale ────────────────────────────────────────
    def run_once(self):
        equity = self.cash + sum(
            p.quantity * p.entry_price for p in self.open_positions.values()
        )
        self.drawdown_guard.update_period(equity)
        paused, reason = self.drawdown_guard.check(equity)
        if self.manual_pause.is_set():
            paused, reason = True, "Pause manuelle (Telegram)"
        if paused:
            logger.warning("⏸️  Bot en pause: %s", reason)
            self.notifier.notify_pause(reason)

        for ticker, bingx_symbol in TICKER_TO_BINGX.items():
            try:
                self._process_ticker(ticker, bingx_symbol, allow_new_entries=not paused)
            except Exception as e:
                logger.exception("Erreur sur %s: %s", ticker, e)
                self.notifier.notify_error(ticker, str(e))

        self._save_state()

        try:
            generate_dashboard(drawdown_guard=self.drawdown_guard)
        except Exception as e:
            logger.warning("Génération du dashboard échouée (non bloquant): %s", e)

    def _process_ticker(self, ticker: str, bingx_symbol: str, allow_new_entries: bool):
        df = self.get_market_data(bingx_symbol)
        if df is None or len(df) < 210:
            logger.info("%s: données insuffisantes, ignoré ce cycle", ticker)
            return

        current_price = df["Close"].iloc[-1]

        # ── Position déjà ouverte : vérifier SL/TP ──────────────
        if ticker in self.open_positions:
            pos = self.open_positions[ticker]
            if current_price <= pos.stop_loss:
                self._close_position(ticker, pos, current_price, "STOP_LOSS")
            elif current_price >= pos.tp1:
                self._close_position(ticker, pos, current_price, "TP1")
            return  # une seule position à la fois, rien d'autre à faire

        if not allow_new_entries:
            return

        # ── Recherche d'un nouveau signal ───────────────────────
        for strat_name, strat in self.strategies.items():
            sig = strat.generate_signal(ticker, df)
            if getattr(sig, "direction", None) == "LONG":
                self._open_position(ticker, bingx_symbol, strat_name, sig, current_price)
                break  # une seule stratégie à la fois par ticker

    def _open_position(self, ticker, bingx_symbol, strat_name, sig, current_price):
        with self.lock:
            qty = self.calculate_quantity(sig.entry, sig.stop_loss)
            if qty <= 0:
                logger.info("%s: quantité calculée nulle, signal ignoré", ticker)
                return

            order = self.connector.place_order(BingXOrder(
                symbol=bingx_symbol, side="BUY", order_type="MARKET", quantity=qty,
            ))
            trade_id = f"{ticker}-{int(time.time())}"
            pos = OpenPosition(
                ticker=ticker, strategy=strat_name, direction="LONG",
                entry_price=current_price, quantity=qty,
                stop_loss=sig.stop_loss, tp1=sig.tp1,
                entry_time=datetime.now().isoformat(), trade_id=trade_id,
            )
            self.open_positions[ticker] = pos
            self.cash -= qty * current_price

        self.journal.log_trade(
            trade_id=trade_id, ticker=ticker, strategy=strat_name, direction="LONG",
            entry_date=datetime.now(), entry_price=current_price, shares=qty,
            stop_loss=sig.stop_loss, tp1=sig.tp1, status="OPEN",
        )
        self.notifier.notify_trade_opened(ticker, strat_name, "LONG", qty, current_price,
                                           sig.stop_loss, sig.tp1)
        logger.info("✅ Position ouverte: %s x%.6f @ %.2f (SL=%.2f TP1=%.2f) [%s]",
                    ticker, qty, current_price, sig.stop_loss, sig.tp1, strat_name)

    def _close_position(self, ticker, pos: OpenPosition, exit_price: float, reason: str):
        self.connector.place_order(BingXOrder(
            symbol=TICKER_TO_BINGX[ticker], side="SELL", order_type="MARKET",
            quantity=pos.quantity,
        ))
        pnl = (exit_price - pos.entry_price) * pos.quantity
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        with self.lock:
            self.cash += pos.quantity * exit_price
            del self.open_positions[ticker]

        self.journal.log_trade(
            trade_id=pos.trade_id, ticker=ticker, strategy=pos.strategy, direction="LONG",
            entry_date=pos.entry_time, entry_price=pos.entry_price, shares=pos.quantity,
            exit_date=datetime.now(), exit_price=exit_price, exit_reason=reason,
            stop_loss=pos.stop_loss, tp1=pos.tp1, pnl=pnl, status="CLOSED",
        )
        self.drawdown_guard.record_trade_result(pnl)
        self.notifier.notify_trade_closed(ticker, pnl, pnl_pct, reason)
        logger.info("🔔 Position fermée: %s @ %.2f (%s) PnL=%.2f (%.2f%%)",
                    ticker, exit_price, reason, pnl, pnl_pct)

    def run_forever(self):
        logger.info("Démarrage du bot crypto — mode=%s | risque/trade=%.1f%% | "
                    "intervalle=%ds", self.connector.mode,
                    self.config.risk_per_trade * 100, self.scan_interval)
        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.exception("Erreur non gérée dans le cycle: %s", e)
                self.notifier.notify_error("run_once", str(e))
            time.sleep(self.scan_interval)


def main():
    parser = argparse.ArgumentParser(description="Bot crypto autonome (BingX)")
    parser.add_argument("--interval", type=int, default=300,
                         help="Intervalle entre chaque scan, en secondes (défaut: 300)")
    parser.add_argument("--risk", type=float, default=2.5,
                         help="Risque par trade en %% (défaut: 2.5)")
    args = parser.parse_args()

    config = CryptoConfig()
    config.risk_per_trade = args.risk / 100.0

    mode = os.getenv("BINGX_MODE", "paper")
    connector = BingXConnector(
        api_key=os.getenv("BINGX_API_KEY", ""),
        api_secret=os.getenv("BINGX_API_SECRET", ""),
        mode=mode,
    )

    if mode == "live":
        confirm = input(
            "⚠️  MODE LIVE — de l'argent réel sera engagé. "
            "Tape EXACTEMENT 'JE COMPRENDS LE RISQUE' pour continuer: "
        )
        if confirm.strip() != "JE COMPRENDS LE RISQUE":
            print("Annulé.")
            return

    bot = CryptoLiveBot(config, connector, scan_interval_seconds=args.interval)
    bot.run_forever()


if __name__ == "__main__":
    main()
