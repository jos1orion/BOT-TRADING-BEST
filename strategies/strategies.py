"""
Implémentation des 4 stratégies de trading.

Chaque stratégie retourne un objet Signal avec :
  - direction  : 'LONG' | 'SHORT' | None
  - strength   : 0–100 (confiance dans le signal)
  - entry      : prix d'entrée suggéré
  - stop_loss  : niveau de stop loss
  - tp1, tp2   : objectifs de profit
  - reason     : explication du signal
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
import pandas as pd
import numpy as np
from core.indicators import Indicators as I
from core.config import Config


@dataclass
class Signal:
    ticker:     str
    strategy:   str
    direction:  Optional[str]   = None   # 'LONG' | 'SHORT' | None
    strength:   float           = 0.0    # 0–100
    entry:      float           = 0.0
    stop_loss:  float           = 0.0
    tp1:        float           = 0.0
    tp2:        float           = 0.0
    risk_reward: float          = 0.0
    reason:     str             = ''
    checklist:  List[str]       = field(default_factory=list)

    def __str__(self):
        if not self.direction:
            return f"[{self.strategy}] {self.ticker} — Pas de signal"
        rr = f"R/R {self.risk_reward:.1f}:1" if self.risk_reward else ''
        return (f"[{self.strategy}] {self.ticker} {self.direction} "
                f"@ {self.entry:.2f}$ | SL {self.stop_loss:.2f}$ "
                f"| TP1 {self.tp1:.2f}$ | TP2 {self.tp2:.2f}$ | "
                f"Force {self.strength:.0f}/100 | {rr}")


# ══════════════════════════════════════════════════════════════════
# STRATÉGIE 1 — Breakout Momentum (ton document PDF)
# ══════════════════════════════════════════════════════════════════

class BreakoutStrategy:
    """
    Stratégie de momentum/breakout inspirée directement du PDF.
    
    Logique :
    1. Filtre marché : SPY/QQQ au-dessus EMA 8/21/50
    2. Action leader : au-dessus EMA 21/50, ADR > 3%
    3. Base de consolidation avec volume décroissant
    4. Cassure de résistance avec volume élevé (≥1.5× la moyenne)
    5. Stop Loss : plus bas de la bougie de breakout
    6. Scale Out : 25% → 25% → 50% avec trailing stop EMA 8/21
    """

    name = "Breakout Momentum"

    def __init__(self, config: Config):
        self.c = config

    def generate_signal(self, ticker: str, df: pd.DataFrame,
                        market_condition: str = 'BULL') -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)

        if df is None or len(df) < 60:
            return sig

        close  = df['Close']
        high   = df['High']
        low    = df['Low']
        volume = df['Volume']

        # ── Indicateurs ──────────────────────────────────────
        e8   = I.ema(close, 8)
        e21  = I.ema(close, 21)
        e50  = I.ema(close, 50)
        atr  = I.atr(high, low, close, 14)
        vol_ratio = I.volume_ratio(volume, 20)
        adr  = I.adr_pct(high, low, 20)

        current_price = close.iloc[-1]
        current_vol_ratio = vol_ratio.iloc[-1]

        # ── Checklist & Direction ─────────────────────────────
        checks = []
        score  = 0
        consolidation_window = 15
        resistance = high.iloc[-consolidation_window:-1].max()
        support    = low.iloc[-consolidation_window:-1].min()
        current_atr = atr.iloc[-1]

        # 1. Contexte et tendance
        is_bull = current_price > e21.iloc[-1] and current_price > e50.iloc[-1]
        is_bear = current_price < e21.iloc[-1] and current_price < e50.iloc[-1]

        direction = None
        if current_price > resistance and (is_bull or market_condition != 'BEAR'):
            direction = 'LONG'
            checks.append('✅ Tendance haussière / neutre favorable au Breakout')
            score += 25
        elif current_price < support and (is_bear or market_condition != 'BULL'):
            direction = 'SHORT'
            checks.append('✅ Tendance baissière / neutre favorable au Breakdown')
            score += 25
        else:
            checks.append('⏳ En consolidation dans le range support/résistance')
            score += 10

        # 2. Volatilité suffisante (ADR ou ATR relatif)
        rel_atr_pct = (current_atr / current_price) * 100 if current_price > 0 else 0
        if adr >= 0.5 or rel_atr_pct >= 0.15:
            checks.append(f'✅ Volatilité active (ATR relatif {rel_atr_pct:.2f}%)')
            score += 20
        else:
            checks.append(f'⚠️ Volatilité très faible ({rel_atr_pct:.2f}%)')
            score += 5

        # 3. Base de consolidation : compression des prix
        recent_ranges = high.iloc[-consolidation_window:].values - low.iloc[-consolidation_window:].values
        range_trend = np.polyfit(range(len(recent_ranges)), recent_ranges, 1)[0]
        if range_trend <= 0:
            checks.append('✅ Compression des prix avant cassure')
            score += 20
        else:
            checks.append('⚠️ Compression modérée')
            score += 10

        # 4. Volume : validation ou adaptation synthétique
        is_flat_vol = (volume.tail(20).std() < 1e-6) or (volume.iloc[-1] == 0)
        if current_vol_ratio >= self.c.breakout_volume_multiplier:
            checks.append(f'✅ Volume de cassure élevé ({current_vol_ratio:.1f}×)')
            score += 20
        elif is_flat_vol:
            checks.append('ℹ️ Volume synthétique/tick — confirmation basée sur le momentum')
            score += 18
        else:
            checks.append(f'⚠️ Volume régulier ({current_vol_ratio:.1f}×)')
            score += 10

        # 5. Déclenchement et niveaux
        if direction == 'LONG':
            checks.append(f'✅ CASSURE haussière de résistance @ {resistance:.2f}$')
            score += 15
            sl = min(low.iloc[-1], resistance) - 0.3 * current_atr
            risk = current_price - sl
            if risk <= 0:
                sl = current_price - 1.0 * current_atr
                risk = current_price - sl
            tp1 = current_price + 2.0 * risk
            tp2 = current_price + 3.5 * risk
            rr = (tp2 - current_price) / risk if risk > 0 else 0

            sig.direction = 'LONG'
            sig.strength = min(score, 100)
            sig.entry = current_price
            sig.stop_loss = sl
            sig.tp1 = tp1
            sig.tp2 = tp2
            sig.risk_reward = rr
            sig.reason = f"Breakout LONG @ {resistance:.2f}$ | R/R {rr:.1f}:1"

        elif direction == 'SHORT':
            checks.append(f'✅ CASSURE baissière de support @ {support:.2f}$')
            score += 15
            sl = max(high.iloc[-1], support) + 0.3 * current_atr
            risk = sl - current_price
            if risk <= 0:
                sl = current_price + 1.0 * current_atr
                risk = sl - current_price
            tp1 = current_price - 2.0 * risk
            tp2 = current_price - 3.5 * risk
            rr = (current_price - tp2) / risk if risk > 0 else 0

            sig.direction = 'SHORT'
            sig.strength = min(score, 100)
            sig.entry = current_price
            sig.stop_loss = sl
            sig.tp1 = tp1
            sig.tp2 = tp2
            sig.risk_reward = rr
            sig.reason = f"Breakdown SHORT @ {support:.2f}$ | R/R {rr:.1f}:1"

        else:
            sig.strength = min(score, 50)
            sig.reason = f"En attente de cassure [{support:.2f}$ – {resistance:.2f}$]"

        sig.checklist = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# STRATÉGIE 2 — CANSLIM (William O'Neil)
# ══════════════════════════════════════════════════════════════════

class CANSLIMStrategy:
    """
    Stratégie CANSLIM — combinaison analyse fondamentale + technique.
    
    Filtres :
    C — EPS quarterly growth > 25%
    A — EPS annual growth > 25%
    N — Nouveau plus haut sur 52 semaines
    S — Volume élevé sur la cassure
    L — Surperformance vs S&P 500 (RS > 0)
    I — Volume moyen en hausse (proxy soutien institutionnel)
    M — Marché en uptrend
    """

    name = "CANSLIM"

    def __init__(self, config: Config):
        self.c = config

    def generate_signal(self, ticker: str, df: pd.DataFrame,
                        fundamentals: Dict = None,
                        benchmark_close: pd.Series = None,
                        market_condition: str = 'BULL') -> Signal:

        sig = Signal(ticker=ticker, strategy=self.name)
        if df is None or len(df) < 60:
            return sig

        close  = df['Close']
        high   = df['High']
        low    = df['Low']
        volume = df['Volume']
        f      = fundamentals or {}

        e21  = I.ema(close, 21)
        e50  = I.ema(close, 50)
        atr  = I.atr(high, low, close, 14)
        vol_ratio = I.volume_ratio(volume, 50)

        current_price = close.iloc[-1]
        score = 0
        checks = []

        # M — Market direction
        if market_condition == 'BULL':
            checks.append('✅ M — Marché en uptrend confirmé')
            score += 15
        else:
            checks.append('❌ M — Marché défavorable')
            sig.checklist = checks
            return sig

        # C — Current quarterly EPS growth
        eps_growth = f.get('eps_growth_yoy')
        if eps_growth and eps_growth >= self.c.canslim_min_eps_growth:
            checks.append(f'✅ C — Croissance EPS +{eps_growth:.0f}% YoY (> 25%)')
            score += 15
        elif eps_growth:
            checks.append(f'⚠️  C — Croissance EPS +{eps_growth:.0f}% (< 25%)')
            score += 5
        else:
            checks.append('⚠️  C — Données EPS non disponibles')
            score += 5

        # A — Annual earnings trend (on utilise revenue_growth comme proxy)
        rev_growth = f.get('revenue_growth')
        if rev_growth and rev_growth >= 15:
            checks.append(f'✅ A — Croissance revenus +{rev_growth:.0f}% annuel')
            score += 10
        else:
            checks.append('⚠️  A — Croissance revenus insuffisante')

        # N — New high (prix proche du plus haut 52 semaines)
        high_52w = high.tail(252).max()
        pct_from_high = (high_52w - current_price) / high_52w * 100
        if pct_from_high <= 5:
            checks.append(f'✅ N — Proche du plus haut 52 semaines ({pct_from_high:.1f}% de distance)')
            score += 15
        elif pct_from_high <= 15:
            checks.append(f'⚠️  N — À {pct_from_high:.1f}% du plus haut 52 semaines')
            score += 8
        else:
            checks.append(f'❌ N — À {pct_from_high:.1f}% du plus haut 52 semaines')

        # S — Volume élevé (proxy float reduit + volume)
        avg_vol = volume.tail(50).mean()
        current_vol = volume.iloc[-1]
        vol_r = current_vol / avg_vol if avg_vol > 0 else 1
        if vol_r >= 1.5:
            checks.append(f'✅ S — Volume {vol_r:.1f}× la moyenne (pression acheteuse)')
            score += 15
        else:
            checks.append(f'⚠️  S — Volume normal ({vol_r:.1f}×)')
            score += 5

        # L — Leader : surperformance vs benchmark
        if benchmark_close is not None and len(benchmark_close) >= 63:
            rs = I.relative_strength(close, benchmark_close, 63)
            if rs > 5:
                checks.append(f'✅ L — Surperformance vs benchmark +{rs:.1f}% (3 mois)')
                score += 15
            elif rs > 0:
                checks.append(f'⚠️  L — Légère surperformance +{rs:.1f}%')
                score += 8
            else:
                checks.append(f'❌ L — Sous-performance vs benchmark ({rs:.1f}%)')
        else:
            checks.append('⚠️  L — Données benchmark non disponibles')
            score += 5

        # I — Institutional sponsorship (volume moyen en hausse)
        vol_3m_avg = volume.tail(63).mean()
        vol_6m_avg = volume.tail(126).mean()
        if vol_3m_avg > vol_6m_avg * 1.1:
            checks.append('✅ I — Volume moyen en hausse (soutien institutionnel probable)')
            score += 15
        else:
            checks.append('⚠️  I — Volume stable ou déclinant')
            score += 5

        # Au-dessus des EMA (condition technique finale)
        if current_price > e21.iloc[-1] and current_price > e50.iloc[-1]:
            checks.append('✅ Prix au-dessus MME 21 et MME 50')
            sig.direction = 'LONG'
        else:
            checks.append('❌ Prix sous les EMA — attendre')

        # Niveaux
        sl   = e50.iloc[-1]
        risk = current_price - sl
        tp1  = current_price * 1.10
        tp2  = current_price * 1.25
        rr   = (tp2 - current_price) / risk if risk > 0 else 0

        sig.strength   = min(score, 100)
        sig.entry      = current_price
        sig.stop_loss  = sl
        sig.tp1        = tp1
        sig.tp2        = tp2
        sig.risk_reward = rr
        sig.reason     = f"CANSLIM score {score}/100 | EPS +{eps_growth:.0f}%" if eps_growth else f"CANSLIM score {score}/100"
        sig.checklist  = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# STRATÉGIE 3 — Trend Following (Turtle Traders)
# ══════════════════════════════════════════════════════════════════

class TurtleStrategy:
    """
    Stratégie Trend Following inspirée des Turtle Traders.
    
    Système 1 (S1) : Donchian 20j / sortie 10j
    Système 2 (S2) : Donchian 55j / sortie 20j
    Position sizing basé sur l'ATR (N)
    Pyramidage jusqu'à 4 unités par marché
    """

    name = "Trend Following (Turtle)"

    def __init__(self, config: Config):
        self.c = config

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)

        if df is None or len(df) < 60:
            return sig

        close  = df['Close']
        high   = df['High']
        low    = df['Low']
        volume = df['Volume']

        atr_val = I.atr(high, low, close, self.c.turtle_atr_period)

        # Canaux de Donchian
        don20h, don20l = I.donchian_channel(high, low, self.c.turtle_donchian_s1)
        don55h, don55l = I.donchian_channel(high, low, self.c.turtle_donchian_s2)
        exit10l        = low.rolling(self.c.turtle_exit_s1).min()
        exit20l        = low.rolling(self.c.turtle_exit_s2).min()

        current_price  = close.iloc[-1]
        current_atr    = atr_val.iloc[-1]
        vol_ratio      = I.volume_ratio(volume, 20)

        checks = []
        score  = 0

        # Vérification S1 breakout (plus haut 20j)
        prev_don20h = don20h.iloc[-2]
        s1_breakout = (close.iloc[-2] <= prev_don20h) and (current_price > don20h.iloc[-1])

        # Vérification S2 breakout (plus haut 55j)
        prev_don55h = don55h.iloc[-2]
        s2_breakout = (close.iloc[-2] <= prev_don55h) and (current_price > don55h.iloc[-1])

        # ADX — force de la tendance
        adx = I.adx(high, low, close, 14)
        adx_val = adx.iloc[-1]

        if adx_val > 25:
            checks.append(f'✅ ADX {adx_val:.0f} — Tendance forte')
            score += 20
        elif adx_val > 20:
            checks.append(f'⚠️  ADX {adx_val:.0f} — Tendance modérée')
            score += 10
        else:
            checks.append(f'❌ ADX {adx_val:.0f} — Pas de tendance (marché en range)')

        if s2_breakout:
            checks.append(f'✅ CASSURE S2 — Plus haut 55j @ {don55h.iloc[-1]:.2f}$ (signal fort)')
            score += 40
            sig.direction = 'LONG'
            sl = current_price - 2 * current_atr
        elif s1_breakout:
            checks.append(f'✅ CASSURE S1 — Plus haut 20j @ {don20h.iloc[-1]:.2f}$ (signal standard)')
            score += 30
            sig.direction = 'LONG'
            sl = current_price - 2 * current_atr
        else:
            sl = current_price - 2 * current_atr
            checks.append(f'⏳ En range | S1 @ {don20h.iloc[-1]:.2f}$ | S2 @ {don55h.iloc[-1]:.2f}$')

        # Volume confirmation
        if vol_ratio.iloc[-1] > 1.3:
            checks.append(f'✅ Volume {vol_ratio.iloc[-1]:.1f}× la moyenne')
            score += 20
        else:
            checks.append(f'⚠️  Volume faible ({vol_ratio.iloc[-1]:.1f}×)')

        # Niveaux Fibonacci comme objectifs (style Turtle : laisser courir)
        tp1 = current_price + 2 * current_atr    # TP1 = +2 ATR
        tp2 = current_price + 4 * current_atr    # TP2 = +4 ATR (laisser courir)
        risk = current_price - sl
        rr   = (tp2 - current_price) / risk if risk > 0 else 0

        # Calcul de la taille de position recommandée (formule Turtle)
        position_size_msg = f"Sizing : 1% capital / {current_atr:.2f}$ (ATR) = "
        if current_atr > 0:
            units = int((self.c.initial_capital * self.c.turtle_unit_risk) / current_atr)
            position_size_msg += f"{units} actions (1 unité)"
        checks.append(f'📊 {position_size_msg}')

        sig.strength    = min(score, 100)
        sig.entry       = current_price
        sig.stop_loss   = sl
        sig.tp1         = tp1
        sig.tp2         = tp2
        sig.risk_reward = rr
        sig.reason      = f"S{'2' if s2_breakout else '1'} breakout | ATR={current_atr:.2f}$ | ADX={adx_val:.0f}"
        sig.checklist   = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# STRATÉGIE 4 — Mean Reversion (Bollinger + RSI)
# ══════════════════════════════════════════════════════════════════

class MeanReversionStrategy:
    """
    Stratégie Mean Reversion.
    
    Signal d'achat : prix sous la bande inférieure de Bollinger + RSI < 30
    Signal de vente : prix sur la bande supérieure + RSI > 70
    Target : retour à la SMA 20 (bande centrale)
    Filtre : uniquement en marché range (ADX < 25)
    """

    name = "Mean Reversion"

    def __init__(self, config: Config):
        self.c = config

    def generate_signal(self, ticker: str, df: pd.DataFrame,
                        market_condition: str = 'BULL') -> Signal:

        sig = Signal(ticker=ticker, strategy=self.name)

        if df is None or len(df) < 30:
            return sig

        close  = df['Close']
        high   = df['High']
        low    = df['Low']

        bb_upper, bb_mid, bb_lower = I.bollinger_bands(
            close, self.c.bb_period, self.c.bb_std)
        rsi_vals = I.rsi(close, self.c.rsi_period)
        adx      = I.adx(high, low, close, 14)
        atr      = I.atr(high, low, close, 14)
        sma200   = I.sma(close, 200)

        current_price = close.iloc[-1]
        current_rsi   = rsi_vals.iloc[-1]
        current_adx   = adx.iloc[-1]
        current_bb_l  = bb_lower.iloc[-1]
        current_bb_u  = bb_upper.iloc[-1]
        current_bb_m  = bb_mid.iloc[-1]
        current_atr   = atr.iloc[-1]

        checks = []
        score  = 0

        # Filtre ADX : Mean Reversion fonctionne mal en marché tendanciel
        if current_adx < 20:
            checks.append(f'✅ ADX {current_adx:.0f} — Marché en range (favorable)')
            score += 25
        elif current_adx < 30:
            checks.append(f'⚠️  ADX {current_adx:.0f} — Tendance modérée (risque accru)')
            score += 10
        else:
            checks.append(f'❌ ADX {current_adx:.0f} — Tendance forte (Mean Reversion déconseillé)')
            sig.checklist = checks
            return sig

        # Détection des divergences RSI (5 bougies)
        bullish_div = False
        bearish_div = False
        if len(close) >= 6:
            prev_low_price = close.iloc[-6:-1].min()
            prev_low_rsi   = rsi_vals.iloc[-6:-1].min()
            if current_price < prev_low_price and current_rsi > prev_low_rsi:
                bullish_div = True
            prev_high_price = close.iloc[-6:-1].max()
            prev_high_rsi   = rsi_vals.iloc[-6:-1].max()
            if current_price > prev_high_price and current_rsi < prev_high_rsi:
                bearish_div = True

        # Signal LONG (survente en range ou retournement)
        if (current_price <= current_bb_l or current_rsi <= self.c.rsi_oversold):
            checks.append(f'✅ Zone de SURVENTE : Prix {current_price:.2f}$ (BB inf {current_bb_l:.2f}$) | RSI {current_rsi:.0f}')
            score += 45
            if bullish_div:
                checks.append('✅ Divergence haussière RSI (signal renforcé)')
                score += 25
            if current_adx < 25 or market_condition != 'BEAR' or bullish_div:
                sig.direction = 'LONG'
                score += 10
            else:
                checks.append('⚠️ Tendance baissière forte — attente de divergence haussière')

            sl = current_price - 1.2 * current_atr
            risk = current_price - sl
            tp1 = max(current_bb_m, current_price + 1.2 * risk)
            tp2 = current_bb_u
            rr = (tp1 - current_price) / risk if risk > 0 else 0

            sig.strength    = min(score, 100)
            sig.entry       = current_price
            sig.stop_loss   = sl
            sig.tp1         = tp1
            sig.tp2         = tp2
            sig.risk_reward = rr
            sig.reason      = f"Mean Reversion LONG | RSI {current_rsi:.0f} | Target SMA20 {current_bb_m:.2f}$"

        # Signal SHORT (surachat en range ou retournement)
        elif (current_price >= current_bb_u or current_rsi >= self.c.rsi_overbought):
            checks.append(f'✅ Zone de SURACHAT : Prix {current_price:.2f}$ (BB sup {current_bb_u:.2f}$) | RSI {current_rsi:.0f}')
            score += 45
            if bearish_div:
                checks.append('✅ Divergence baissière RSI (signal renforcé)')
                score += 25
            if current_adx < 25 or market_condition != 'BULL' or bearish_div:
                sig.direction = 'SHORT'
                score += 10
            else:
                checks.append('⚠️ Tendance haussière forte — attente de divergence baissière')

            sl = current_price + 1.2 * current_atr
            risk = sl - current_price
            tp1 = min(current_bb_m, current_price - 1.2 * risk)
            tp2 = current_bb_l
            rr = (current_price - tp1) / risk if risk > 0 else 0

            sig.direction   = 'SHORT'
            sig.strength    = min(score, 100)
            sig.entry       = current_price
            sig.stop_loss   = sl
            sig.tp1         = tp1
            sig.tp2         = tp2
            sig.risk_reward = rr
            sig.reason      = f"Mean Reversion SHORT | RSI {current_rsi:.0f} | Target SMA20 {current_bb_m:.2f}$"

        else:
            checks.append(f'⏳ Marché équilibré | RSI {current_rsi:.0f} | BB [{current_bb_l:.2f} – {current_bb_u:.2f}]')
            sig.strength = min(score, 40)
            sig.reason = "Pas d'extrême de survente/surachat"

        sig.checklist   = checks
        return sig
