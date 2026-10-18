"""
Fabrique de stratégies + évaluation d'un signal de façon uniforme.
Utilisé par le backtest MT5 (même logique d'appel que live_trading.py).
"""
from __future__ import annotations

from typing import Dict, Optional, NamedTuple

from strategies.strategies import BreakoutStrategy, MeanReversionStrategy
from strategies.englobante import EnglobanteHaussiere
from strategies.liquidity_sweep import LiquiditySweepStrategy
from strategies.patterns import (
    PullbackStrategy, BullFlagStrategy, DoubleBottomStrategy,
    InsideBarStrategy, OpeningRangeBreakoutStrategy,
)

NEEDS_MARKET_CONDITION = ("breakout", "mean_reversion")


class SimpleSignal(NamedTuple):
    direction: str      # 'LONG' | 'SHORT'
    strength: float
    entry: float
    stop_loss: float
    tp1: float


def build_strategies(config) -> Dict[str, object]:
    return {
        'breakout':        BreakoutStrategy(config),
        'englobante':      EnglobanteHaussiere(config, variante='sur_ma'),
        'liquidity_sweep': LiquiditySweepStrategy(config),
        'mean_reversion':  MeanReversionStrategy(config),
        'pullback':        PullbackStrategy(config),
        'bull_flag':       BullFlagStrategy(config),
        'double_bottom':   DoubleBottomStrategy(config),
        'inside_bar':      InsideBarStrategy(config),
        'orb':             OpeningRangeBreakoutStrategy(config),
    }


def evaluate(name: str, strat, symbol: str, df, market_condition: str = 'NEUTRAL') -> Optional[SimpleSignal]:
    """Retourne un SimpleSignal ou None (pas de signal / signal incomplet)."""
    if name in NEEDS_MARKET_CONDITION:
        sig = strat.generate_signal(symbol, df, market_condition)
    else:
        sig = strat.generate_signal(symbol, df)
    if not getattr(sig, 'direction', None):
        return None
    entry, sl, tp = sig.entry, sig.stop_loss, sig.tp1
    if not entry or not sl or not tp:
        return None
    return SimpleSignal(sig.direction, float(sig.strength), float(entry), float(sl), float(tp))
