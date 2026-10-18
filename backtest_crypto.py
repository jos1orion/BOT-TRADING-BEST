"""
Backtest — Mean Reversion & Liquidity Sweep sur cryptomonnaies.

Utilise des données quotidiennes gratuites (yfinance) pour BTC, ETH,
SOL, BNB, XRP, ADA, DOGE, AVAX. Objectif : mesurer le VRAI win rate,
profit factor et drawdown de ces deux stratégies sur crypto — pas de
chiffre décidé d'avance.

Hypothèses de simulation (à connaître avant de lire les résultats) :
- Entrée simulée à l'OUVERTURE du jour suivant le signal (pas de
  lookahead : le signal est calculé sur les données jusqu'à J, l'entrée
  se fait à l'ouverture de J+1).
- Si le Stop Loss ET le Take Profit sont touchés le même jour, on
  suppose le Stop Loss touché en premier (hypothèse conservatrice).
- Une seule position par ticker à la fois.
- Slippage et commission de core.config.Config appliqués (slippage_pct).
- Sortie totale au TP1 (pas de scale-out partiel dans cette version,
  pour garder le calcul du win rate simple et non-ambigu).

⚠️ Un backtest sur données journalières ne capture pas le bruit intraday.
Les résultats ici donnent une indication directionnelle, pas une
garantie de performance en trading réel.
"""

import argparse
from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd
import numpy as np

from core.crypto_config import CryptoConfig
from core.data import DataFetcher
from strategies.strategies import MeanReversionStrategy
from strategies.liquidity_sweep import LiquiditySweepStrategy


@dataclass
class Trade:
    ticker: str
    strategy: str
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    stop_loss: float = 0.0
    tp1: float = 0.0
    outcome: str = ""          # "WIN" | "LOSS" | "OPEN"
    r_multiple: float = 0.0
    pnl_pct: float = 0.0


def simulate_strategy(ticker: str, df: pd.DataFrame, strategy, strategy_name: str,
                       config: CryptoConfig, min_lookback: int = 210) -> List[Trade]:
    """
    Parcourt le DataFrame jour par jour (sans lookahead), ouvre une
    position simulée quand la stratégie donne un signal LONG, et la
    referme au premier Stop Loss ou Take Profit atteint.
    """
    trades: List[Trade] = []
    open_trade: Optional[Trade] = None
    slip = config.slippage_pct / 100.0

    n = len(df)
    for i in range(min_lookback, n - 1):
        window = df.iloc[:i + 1]

        # ── Gestion de la position ouverte ──────────────────────
        if open_trade is not None:
            day = df.iloc[i]
            hit_sl = day['Low'] <= open_trade.stop_loss
            hit_tp = day['High'] >= open_trade.tp1

            if hit_sl and hit_tp:
                # Hypothèse conservatrice : le SL a été touché en premier
                exit_price = open_trade.stop_loss * (1 - slip)
                outcome = "LOSS"
            elif hit_sl:
                exit_price = open_trade.stop_loss * (1 - slip)
                outcome = "LOSS"
            elif hit_tp:
                exit_price = open_trade.tp1 * (1 - slip)
                outcome = "WIN"
            else:
                continue  # position toujours ouverte, jour suivant

            open_trade.exit_date = df.index[i]
            open_trade.exit_price = exit_price
            open_trade.outcome = outcome
            risk = open_trade.entry_price - open_trade.stop_loss
            open_trade.r_multiple = ((exit_price - open_trade.entry_price) / risk
                                      if risk > 0 else 0.0)
            open_trade.pnl_pct = (exit_price - open_trade.entry_price) / open_trade.entry_price * 100
            trades.append(open_trade)
            open_trade = None
            continue  # une seule position à la fois

        # ── Recherche d'un nouveau signal ───────────────────────
        try:
            sig = strategy.generate_signal(ticker, window)
        except Exception:
            continue

        direction = getattr(sig, "direction", None)
        if direction == "LONG":
            entry_price = df.iloc[i + 1]['Open'] * (1 + slip)  # entrée J+1
            open_trade = Trade(
                ticker=ticker, strategy=strategy_name,
                entry_date=df.index[i + 1], entry_price=entry_price,
                stop_loss=sig.stop_loss, tp1=sig.tp1,
            )

    return trades


def compute_stats(trades: List[Trade]) -> dict:
    closed = [t for t in trades if t.outcome in ("WIN", "LOSS")]
    if not closed:
        return {"total_trades": 0}

    wins = [t for t in closed if t.outcome == "WIN"]
    losses = [t for t in closed if t.outcome == "LOSS"]

    win_rate = len(wins) / len(closed) * 100
    avg_win_r = np.mean([t.r_multiple for t in wins]) if wins else 0.0
    avg_loss_r = np.mean([t.r_multiple for t in losses]) if losses else 0.0
    gross_profit = sum(t.r_multiple for t in wins)
    gross_loss = abs(sum(t.r_multiple for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    # Max drawdown sur la courbe d'équité en R cumulés
    equity = np.cumsum([t.r_multiple for t in closed])
    running_max = np.maximum.accumulate(equity) if len(equity) else np.array([0])
    drawdown = running_max - equity
    max_dd_r = drawdown.max() if len(drawdown) else 0.0

    return {
        "total_trades": len(closed),
        "win_rate_pct": round(win_rate, 1),
        "avg_win_r": round(avg_win_r, 2),
        "avg_loss_r": round(avg_loss_r, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "inf",
        "expectancy_r": round(np.mean([t.r_multiple for t in closed]), 2),
        "max_drawdown_r": round(max_dd_r, 2),
    }


def run_backtest(period: str = "2y"):
    config = CryptoConfig()
    data = DataFetcher(verbose=True)

    strategies = {
        "mean_reversion": MeanReversionStrategy(config),
        "liquidity_sweep": LiquiditySweepStrategy(config),
    }

    all_results = {}
    for strat_name, strat in strategies.items():
        print(f"\n{'='*70}\n  STRATÉGIE : {strat_name}\n{'='*70}")
        all_trades = []
        for ticker in config.watchlist:
            df = data.get_ohlcv(ticker, period=period, interval="1d")
            if df is None or len(df) < 220:
                print(f"  ⚠️  {ticker}: données insuffisantes, ignoré")
                continue
            trades = simulate_strategy(ticker, df, strat, strat_name, config)
            all_trades.extend(trades)
            stats = compute_stats(trades)
            print(f"  {ticker:10s} → {stats}")

        combined = compute_stats(all_trades)
        print(f"\n  >>> TOTAL {strat_name} (tous tickers) : {combined}")
        all_results[strat_name] = combined

    print(f"\n{'='*70}\n  RÉSUMÉ FINAL\n{'='*70}")
    for strat_name, stats in all_results.items():
        print(f"  {strat_name:20s} : {stats}")

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest crypto Mean Reversion / Liquidity Sweep")
    parser.add_argument("--period", default="2y",
                         help="Période yfinance (ex: 1y, 2y, 5y, max)")
    args = parser.parse_args()
    run_backtest(period=args.period)
