"""
Reconstructions "façon Bobby" — 3 hypothèses de stratégie déduites des
seules statistiques publiques du robot forex montré dans la vidéo
"J'ai développé le robot de trading le plus rentable sur le Forex"
(chaîne Leo Trading-Algo) : win rate ~68%, profit factor 1.41, gain
moyen < perte moyenne, ~1000 trades/13 ans, sur une paire qui "respire"
(support/résistance) plutôt que directionnelle.

⚠️ IMPORTANT : l'auteur de la vidéo ne révèle jamais la logique réelle
de décision de son robot — c'est explicitement le contenu payant de
son accompagnement. Les 3 classes ci-dessous ne sont donc PAS son
algorithme. Ce sont des implémentations plausibles, construites à la
main, qui *pourraient* produire un profil statistique similaire.
Elles doivent être backtestées et jugées sur leurs propres mérites
(voir Backtest Ledger) avant tout usage réel — au même titre que les
autres stratégies du bot.

Les 3 variantes partagent la même intuition (éviter grille/martingale,
préférer un instrument qui respecte ses niveaux, sortir vite, laisser
un stop plus large derrière la structure) mais diffèrent sur le
déclencheur d'entrée :

  A. SRMeanReversionStrategy  — rejet d'un niveau de support/résistance
  B. RangeChannelStrategy     — position dans un canal Donchian, plus mécanique
  C. SoftTrendPullbackStrategy — pullback dans une tendance douce (pas forte)
"""

from __future__ import annotations

from typing import List, Optional
import pandas as pd
import numpy as np

from core.indicators import Indicators as I
from core.config import Config
from strategies.strategies import Signal


def _swing_levels(high: pd.Series, low: pd.Series, lookback: int):
    """Niveaux de support (plus bas) / résistance (plus haut) sur la fenêtre."""
    swing_low = low.rolling(lookback).min()
    swing_high = high.rolling(lookback).max()
    return swing_low, swing_high


# ══════════════════════════════════════════════════════════════════
# A — RETOUR À LA MOYENNE SUR SUPPORT / RÉSISTANCE
# ══════════════════════════════════════════════════════════════════

class SRMeanReversionStrategy:
    """
    Hypothèse : entrée sur rejet d'un niveau de S/R (mèche qui dépasse
    le niveau puis clôture dedans = rejet), TP proche vers le milieu du
    range, SL plus large placé derrière le niveau cassé.
    Filtre : uniquement en range (ADX bas) — jamais si le marché devient
    trop directionnel.
    """

    name = "SR Mean Reversion (reconstruction)"

    def __init__(self, config: Config):
        self.c = config

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)
        lb = self.c.srrev_lookback
        if df is None or len(df) < lb + 10:
            return sig

        high, low, close = df['High'], df['Low'], df['Close']
        atr = I.atr(high, low, close, 14)
        adx = I.adx(high, low, close, 14)
        rsi = I.rsi(close, self.c.rsi_period)

        # Niveaux calculés sur la fenêtre PRÉCÉDENTE (hors bougie courante)
        swing_low, swing_high = _swing_levels(high.shift(1), low.shift(1), lb)

        price = close.iloc[-1]
        bar_low, bar_high = low.iloc[-1], high.iloc[-1]
        s = swing_low.iloc[-1]
        r = swing_high.iloc[-1]
        current_atr = atr.iloc[-1]
        current_adx = adx.iloc[-1]
        current_rsi = rsi.iloc[-1]

        checks: List[str] = []
        score = 0

        if pd.isna(s) or pd.isna(r) or current_atr <= 0:
            return sig

        if current_adx <= self.c.srrev_adx_max:
            checks.append(f'✅ ADX {current_adx:.0f} — range confirmé (≤ {self.c.srrev_adx_max:.0f})')
            score += 20
        else:
            checks.append(f'❌ ADX {current_adx:.0f} — trop directionnel, retour à la moyenne écarté')
            sig.checklist = checks
            return sig

        tolerance = s * (self.c.srrev_touch_tolerance_pct / 100.0)

        # Rejet du support : la mèche basse a touché/dépassé le niveau,
        # mais la clôture est repassée au-dessus, dans la moitié haute
        # de la bougie (mèche de rejet plutôt que simple bruit).
        touched_support = bar_low <= s + tolerance
        bar_range = bar_high - bar_low
        closed_upper_half = bar_range > 0 and (price - bar_low) >= 0.5 * bar_range
        rejected_support = touched_support and price > s and closed_upper_half

        if rejected_support and current_rsi < 55:
            checks.append(f'✅ Rejet du support {s:.5f} (mèche {bar_low:.5f} → clôture {price:.5f})')
            checks.append(f'✅ RSI {current_rsi:.0f} — pas encore suracheté')
            score += 55
            sig.direction = 'LONG'
            sl = min(bar_low, s) - 1.0 * current_atr        # SL large, derrière la structure
            tp1 = s + (r - s) * 0.5                         # milieu du range
            tp2 = r                                          # résistance
        else:
            checks.append(f'⏳ Pas de rejet net du support ({s:.5f}) — prix {price:.5f}')
            sig.checklist = checks
            return sig

        risk = price - sl
        rr = (tp1 - price) / risk if risk > 0 else 0

        sig.strength = min(score, 100)
        sig.entry = price
        sig.stop_loss = sl
        sig.tp1 = tp1
        sig.tp2 = tp2
        sig.risk_reward = rr
        sig.reason = f"Rejet support {s:.5f} | range [{s:.5f}–{r:.5f}] | ADX={current_adx:.0f}"
        sig.checklist = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# B — RANGE TRADING (CANAL DONCHIAN)
# ══════════════════════════════════════════════════════════════════

class RangeChannelStrategy:
    """
    Hypothèse : version plus mécanique de A — pas de lecture de bougie,
    juste la position du prix dans un canal Donchian, sous filtre ADX
    strict. Achat près du bas du canal, cible le haut/milieu du canal.
    """

    name = "Range Channel (reconstruction)"

    def __init__(self, config: Config):
        self.c = config

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)
        period = self.c.range_donchian_period
        if df is None or len(df) < period + 10:
            return sig

        high, low, close = df['High'], df['Low'], df['Close']
        upper, lower = I.donchian_channel(high, low, period)
        adx = I.adx(high, low, close, 14)
        atr = I.atr(high, low, close, 14)

        price = close.iloc[-1]
        ch_low = lower.iloc[-1]
        ch_high = upper.iloc[-1]
        current_adx = adx.iloc[-1]
        current_atr = atr.iloc[-1]

        checks: List[str] = []
        if pd.isna(ch_low) or pd.isna(ch_high) or ch_high <= ch_low:
            return sig

        channel_width = ch_high - ch_low
        position_in_channel = (price - ch_low) / channel_width  # 0 = bas, 1 = haut

        if current_adx > self.c.range_adx_max:
            checks.append(f'❌ ADX {current_adx:.0f} — hors range, stratégie écartée')
            sig.checklist = checks
            return sig
        checks.append(f'✅ ADX {current_adx:.0f} — range strict confirmé')

        score = 0
        if position_in_channel <= 0.15:
            checks.append(f'✅ Prix dans le 1er décile du canal ({position_in_channel:.0%})')
            score += 60
            sig.direction = 'LONG'
            sl = ch_low - 0.5 * current_atr
            tp1 = ch_low + channel_width * 0.5
            tp2 = ch_high
        else:
            checks.append(f'⏳ Prix à {position_in_channel:.0%} du canal — pas assez bas')
            sig.checklist = checks
            return sig

        risk = price - sl
        rr = (tp1 - price) / risk if risk > 0 else 0

        sig.strength = score
        sig.entry = price
        sig.stop_loss = sl
        sig.tp1 = tp1
        sig.tp2 = tp2
        sig.risk_reward = rr
        sig.reason = f"Canal [{ch_low:.5f}–{ch_high:.5f}] | position={position_in_channel:.0%} | ADX={current_adx:.0f}"
        sig.checklist = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# C — PULLBACK EN TENDANCE DOUCE
# ══════════════════════════════════════════════════════════════════

class SoftTrendPullbackStrategy:
    """
    Hypothèse : pas un vrai trend-follower (Turtle couvre déjà ce cas) —
    achète les creux dans une tendance MODÉRÉE (ADX moyen, pas fort),
    sort vite dès le premier signe de reprise. Beaucoup de petits gains,
    perte plus large si le pullback devient un retournement complet.
    """

    name = "Soft Trend Pullback (reconstruction)"

    def __init__(self, config: Config):
        self.c = config

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)
        slow_p = self.c.pullback_ema_slow
        if df is None or len(df) < slow_p + 20:
            return sig

        high, low, close = df['High'], df['Low'], df['Close']
        ema_fast = I.ema(close, self.c.pullback_ema_fast)
        ema_slow = I.ema(close, slow_p)
        adx = I.adx(high, low, close, 14)
        rsi = I.rsi(close, self.c.rsi_period)
        atr = I.atr(high, low, close, 14)

        price = close.iloc[-1]
        ef, es = ema_fast.iloc[-1], ema_slow.iloc[-1]
        current_adx = adx.iloc[-1]
        current_rsi = rsi.iloc[-1]
        current_atr = atr.iloc[-1]

        checks: List[str] = []

        soft_trend = self.c.pullback_adx_min <= current_adx <= self.c.pullback_adx_max
        uptrend = ef > es
        if not (soft_trend and uptrend):
            checks.append(f'❌ ADX {current_adx:.0f} hors zone [{self.c.pullback_adx_min:.0f}-{self.c.pullback_adx_max:.0f}] ou pas de tendance haussière douce')
            sig.checklist = checks
            return sig
        checks.append(f'✅ Tendance douce haussière (ADX {current_adx:.0f}, EMA{self.c.pullback_ema_fast} > EMA{slow_p})')

        near_fast_ema = abs(price - ef) <= 0.6 * current_atr
        turning_up = current_rsi > rsi.iloc[-2] and 40 <= current_rsi <= 55

        score = 25
        if near_fast_ema and turning_up:
            checks.append(f'✅ Pullback vers EMA{self.c.pullback_ema_fast} ({ef:.5f}) avec RSI qui remonte ({current_rsi:.0f})')
            score += 55
            sig.direction = 'LONG'
            sl = min(low.iloc[-5:].min(), es) - 0.5 * current_atr
            tp1 = price + 1.0 * current_atr     # sortie rapide, comme décrit
            tp2 = price + 2.0 * current_atr
        else:
            checks.append(f'⏳ Pas de pullback exploitable actuellement (RSI {current_rsi:.0f}, écart EMA {abs(price-ef):.5f})')
            sig.checklist = checks
            return sig

        risk = price - sl
        rr = (tp1 - price) / risk if risk > 0 else 0

        sig.strength = min(score, 100)
        sig.entry = price
        sig.stop_loss = sl
        sig.tp1 = tp1
        sig.tp2 = tp2
        sig.risk_reward = rr
        sig.reason = f"Pullback EMA{self.c.pullback_ema_fast}={ef:.5f} | RSI={current_rsi:.0f} | ADX={current_adx:.0f}"
        sig.checklist = checks
        return sig
