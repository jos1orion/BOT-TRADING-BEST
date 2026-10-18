"""
Implémentation des 5 stratégies restantes du catalogue (strategies/catalogue.py) :

  #2  Pullback sur Tendance
  #4  Bull Flag (Drapeau Haussier)
  #5  Double Bottom
  #6  Inside Bar Breakout
  #7  Opening Range Breakout (ORB)

Toutes retournent un objet `Signal` (voir strategies/strategies.py) afin de
s'intégrer directement dans le moteur (core/engine.py) et le live trading.

⚠️ Ce sont des implémentations "raisonnables" des concepts décrits dans le
catalogue — elles doivent être backtestées (voir README) avant tout usage réel.
"""

from __future__ import annotations

from typing import Optional, Tuple, List
import numpy as np
import pandas as pd

from core.indicators import Indicators as I
from core.config import Config
from strategies.strategies import Signal


# ══════════════════════════════════════════════════════════════════
# #2 — PULLBACK SUR TENDANCE
# ══════════════════════════════════════════════════════════════════

class PullbackStrategy:
    """
    Cassure de structure -> pullback sur le niveau cassé -> bougie de
    confirmation (englobante / clôture haussière) -> entrée.
    """
    name = "Pullback sur Tendance"

    def __init__(self, config: Config, lookback_structure: int = 20,
                 pullback_window: int = 5, min_rr: float = 2.0):
        self.c = config
        self.lookback_structure = lookback_structure
        self.pullback_window = pullback_window
        self.min_rr = min_rr

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)
        if df is None or len(df) < self.lookback_structure + 20:
            return sig

        close, high, low = df['Close'], df['High'], df['Low']
        e50 = I.sma(close, 50)
        atr = I.atr(high, low, close, 14)
        adx = I.adx(high, low, close, 14)

        checks: List[str] = []
        score = 0
        current_price = close.iloc[-1]
        current_atr = atr.iloc[-1]
        adx_val = adx.iloc[-1]

        # 1. Filtre tendance et ADX
        above_ma = current_price > e50.iloc[-1]
        below_ma = current_price < e50.iloc[-1]

        if adx_val >= 18:
            checks.append(f"✅ ADX {adx_val:.0f} — tendance suffisante")
            score += 20
        else:
            checks.append(f"⚠️ ADX {adx_val:.0f} — tendance faible")
            score += 5

        # ── PULLBACK HAUSSIER (LONG) ──
        if above_ma:
            checks.append("✅ Tendance haussière (prix > MA50)")
            score += 20
            struct_high = high.iloc[-(self.lookback_structure + self.pullback_window):-self.pullback_window].max()
            breakout_happened = high.iloc[-(self.pullback_window+2):-1].max() > struct_high * 0.999
            if not breakout_happened:
                checks.append("❌ Pas de cassure de structure haussière identifiée")
                sig.checklist = checks
                return sig

            checks.append(f"✅ Cassure de structure récente au-dessus de {struct_high:.2f}$")
            score += 20

            distance = abs(current_price - struct_high)
            if distance <= 1.8 * current_atr and current_price >= struct_high - 0.5 * current_atr:
                checks.append(f"✅ Pullback sur la zone cassée ({struct_high:.2f}$)")
                score += 20
            else:
                checks.append("⏳ Prix en dehors de la zone optimale de pullback")
                sig.strength = min(score, 50)
                sig.checklist = checks
                return sig

            confirm = close.iloc[-1] > df['Open'].iloc[-1] or (close.iloc[-1] > low.iloc[-1] + 0.5 * (high.iloc[-1] - low.iloc[-1]))
            if confirm:
                checks.append("✅ Bougie de confirmation haussière")
                score += 20
                sig.direction = 'LONG'
            else:
                checks.append("⏳ En attente de confirmation haussière")
                sig.strength = min(score, 50)
                sig.checklist = checks
                return sig

            sl = min(low.iloc[-self.pullback_window:].min(), struct_high - 0.4 * current_atr)
            risk = current_price - sl
            if risk <= 0:
                sl = current_price - 1.0 * current_atr
                risk = current_price - sl
            tp1 = current_price + risk * self.min_rr
            tp2 = current_price + risk * (self.min_rr + 1)
            rr = (tp2 - current_price) / risk if risk > 0 else 0

            sig.strength = min(score, 100)
            sig.entry = current_price
            sig.stop_loss = sl
            sig.tp1 = tp1
            sig.tp2 = tp2
            sig.risk_reward = rr
            sig.reason = f"Pullback LONG sur {struct_high:.2f}$ | R/R {rr:.1f}:1"
            sig.checklist = checks
            return sig

        # ── PULLBACK BAISSIER (SHORT) ──
        elif below_ma:
            checks.append("✅ Tendance baissière (prix < MA50)")
            score += 20
            struct_low = low.iloc[-(self.lookback_structure + self.pullback_window):-self.pullback_window].min()
            breakdown_happened = low.iloc[-(self.pullback_window+2):-1].min() < struct_low * 1.001
            if not breakdown_happened:
                checks.append("❌ Pas de cassure de support récent identifiée")
                sig.checklist = checks
                return sig

            checks.append(f"✅ Cassure de structure baissière sous {struct_low:.2f}$")
            score += 20

            distance = abs(current_price - struct_low)
            if distance <= 1.8 * current_atr and current_price <= struct_low + 0.5 * current_atr:
                checks.append(f"✅ Pullback sur le support devenu résistance ({struct_low:.2f}$)")
                score += 20
            else:
                checks.append("⏳ Prix en dehors de la zone optimale de pullback")
                sig.strength = min(score, 50)
                sig.checklist = checks
                return sig

            confirm = close.iloc[-1] < df['Open'].iloc[-1] or (close.iloc[-1] < high.iloc[-1] - 0.5 * (high.iloc[-1] - low.iloc[-1]))
            if confirm:
                checks.append("✅ Bougie de confirmation baissière")
                score += 20
                sig.direction = 'SHORT'
            else:
                checks.append("⏳ En attente de confirmation baissière")
                sig.strength = min(score, 50)
                sig.checklist = checks
                return sig

            sl = max(high.iloc[-self.pullback_window:].max(), struct_low + 0.4 * current_atr)
            risk = sl - current_price
            if risk <= 0:
                sl = current_price + 1.0 * current_atr
                risk = sl - current_price
            tp1 = current_price - risk * self.min_rr
            tp2 = current_price - risk * (self.min_rr + 1)
            rr = (current_price - tp2) / risk if risk > 0 else 0

            sig.strength = min(score, 100)
            sig.entry = current_price
            sig.stop_loss = sl
            sig.tp1 = tp1
            sig.tp2 = tp2
            sig.risk_reward = rr
            sig.reason = f"Pullback SHORT sous {struct_low:.2f}$ | R/R {rr:.1f}:1"
            sig.checklist = checks
            return sig

        sig.checklist = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# #4 — BULL FLAG (DRAPEAU HAUSSIER)
# ══════════════════════════════════════════════════════════════════

class BullFlagStrategy:
    """
    Mât haussier fort (momentum) suivi d'une consolidation descendante
    en canal parallèle (le drapeau). Entrée à la cassure du drapeau.
    """
    name = "Bull Flag"

    def __init__(self, config: Config, mat_window: int = 10,
                 flag_window: int = 10, min_mat_move_pct: float = 2.0):
        self.c = config
        self.mat_window = mat_window
        self.flag_window = flag_window
        self.min_mat_move_pct = min_mat_move_pct

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)
        total_window = self.mat_window + self.flag_window
        if df is None or len(df) < total_window + 20:
            return sig

        close, high, low, volume = df['Close'], df['High'], df['Low'], df['Volume']
        atr = I.atr(high, low, close, 14)
        current_atr = atr.iloc[-1]
        current_price = close.iloc[-1]

        checks: List[str] = []
        score = 0

        # 1. Le mât : impulsion nette avant le drapeau
        mat_start = close.iloc[-total_window]
        mat_end = close.iloc[-self.flag_window]
        mat_move = mat_end - mat_start
        mat_move_pct = (mat_end / mat_start - 1) * 100 if mat_start > 0 else 0

        is_bull_mat = mat_move >= 2.0 * current_atr or mat_move_pct >= self.min_mat_move_pct
        is_bear_mat = mat_move <= -2.0 * current_atr or mat_move_pct <= -self.min_mat_move_pct

        if not (is_bull_mat or is_bear_mat):
            checks.append(f"❌ Mât insuffisant ({mat_move_pct:+.1f}%, attendu ≥ 2 ATR)")
            sig.checklist = checks
            return sig

        # 2. Le drapeau : consolidation
        flag_closes = close.iloc[-self.flag_window:]
        flag_trend = np.polyfit(range(len(flag_closes)), flag_closes.values, 1)[0]
        flag_range = flag_closes.max() - flag_closes.min()
        flag_volume = volume.iloc[-self.flag_window:]
        vol_trend = np.polyfit(range(len(flag_volume)), flag_volume.values, 1)[0]
        current_vol_ratio = I.volume_ratio(volume, 20).iloc[-1]
        is_flat_vol = (volume.tail(20).std() < 1e-6) or (volume.iloc[-1] == 0)

        # ── BULL FLAG (LONG) ──
        if is_bull_mat:
            checks.append(f"✅ Mât haussier net : +{mat_move_pct:.1f}% ({mat_move/current_atr:.1f} ATR)")
            score += 30

            if flag_trend <= 0.05 and flag_range < abs(mat_move) * 0.65:
                checks.append("✅ Drapeau : consolidation ordonnée")
                score += 25
            else:
                checks.append("⚠️ Drapeau étendu")
                score += 10

            flag_high = high.iloc[-self.flag_window:-1].max()
            breakout = current_price > flag_high
            if breakout and (current_vol_ratio >= 1.15 or is_flat_vol):
                checks.append(f"✅ CASSURE haussière du drapeau @ {flag_high:.2f}$")
                score += 35
                sig.direction = 'LONG'
            else:
                checks.append(f"⏳ En attente de cassure au-dessus de {flag_high:.2f}$")
                sig.strength = min(score, 50)
                sig.checklist = checks
                return sig

            sl = flag_closes.min() - 0.4 * current_atr
            risk = current_price - sl
            if risk <= 0:
                sl = current_price - 1.0 * current_atr
                risk = current_price - sl
            tp1 = current_price + risk * 2.0
            tp2 = current_price + risk * 3.5
            rr = (tp2 - current_price) / risk if risk > 0 else 0

            sig.strength = min(score, 100)
            sig.entry = current_price
            sig.stop_loss = sl
            sig.tp1 = tp1
            sig.tp2 = tp2
            sig.risk_reward = rr
            sig.reason = f"Bull Flag | Mât +{mat_move_pct:.1f}% | R/R {rr:.1f}:1"
            sig.checklist = checks
            return sig

        # ── BEAR FLAG (SHORT) ──
        elif is_bear_mat:
            checks.append(f"✅ Mât baissier net : {mat_move_pct:.1f}% ({abs(mat_move)/current_atr:.1f} ATR)")
            score += 30

            if flag_trend >= -0.05 and flag_range < abs(mat_move) * 0.65:
                checks.append("✅ Drapeau : consolidation ascendante ordonnée")
                score += 25
            else:
                checks.append("⚠️ Drapeau étendu")
                score += 10

            flag_low = low.iloc[-self.flag_window:-1].min()
            breakdown = current_price < flag_low
            if breakdown and (current_vol_ratio >= 1.15 or is_flat_vol):
                checks.append(f"✅ CASSURE baissière du drapeau @ {flag_low:.2f}$")
                score += 35
                sig.direction = 'SHORT'
            else:
                checks.append(f"⏳ En attente de cassure sous {flag_low:.2f}$")
                sig.strength = min(score, 50)
                sig.checklist = checks
                return sig

            sl = flag_closes.max() + 0.4 * current_atr
            risk = sl - current_price
            if risk <= 0:
                sl = current_price + 1.0 * current_atr
                risk = sl - current_price
            tp1 = current_price - risk * 2.0
            tp2 = current_price - risk * 3.5
            rr = (current_price - tp2) / risk if risk > 0 else 0

            sig.strength = min(score, 100)
            sig.entry = current_price
            sig.stop_loss = sl
            sig.tp1 = tp1
            sig.tp2 = tp2
            sig.risk_reward = rr
            sig.reason = f"Bear Flag | Mât {mat_move_pct:.1f}% | R/R {rr:.1f}:1"
            sig.checklist = checks
            return sig

        sig.checklist = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# #5 — DOUBLE BOTTOM
# ══════════════════════════════════════════════════════════════════

class DoubleBottomStrategy:
    """
    Deux creux à niveau comparable (±2%) après une tendance baissière,
    neckline sur le HAUT entre les deux creux. Entrée à la cassure
    de la neckline.
    """
    name = "Double Bottom"

    def __init__(self, config: Config, lookback: int = 90,
                 tolerance_pct: float = 2.0, min_gap_bars: int = 8):
        self.c = config
        self.lookback = lookback
        self.tolerance_pct = tolerance_pct
        self.min_gap_bars = min_gap_bars

    def _find_swings(self, series: pd.Series, mode: str = 'low', window: int = 5) -> List[Tuple[int, float]]:
        n = len(series)
        pivots = []
        for i in range(window, n - window):
            seg = series.iloc[i - window:i + window + 1]
            if mode == 'low' and series.iloc[i] == seg.min():
                pivots.append((i, series.iloc[i]))
            elif mode == 'high' and series.iloc[i] == seg.max():
                pivots.append((i, series.iloc[i]))
        return pivots

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)
        if df is None or len(df) < self.lookback:
            return sig

        close, high, low = df['Close'], df['High'], df['Low']
        sub = df.iloc[-self.lookback:]
        sub_low = sub['Low'].reset_index(drop=True)
        sub_high = sub['High'].reset_index(drop=True)

        checks: List[str] = []
        atr = I.atr(high, low, close, 14).iloc[-1]
        current_price = close.iloc[-1]
        current_vol_ratio = I.volume_ratio(df['Volume'], 20).iloc[-1]
        is_flat_vol = (df['Volume'].tail(20).std() < 1e-6) or (df['Volume'].iloc[-1] == 0)

        # ── 1. Chercher un DOUBLE BOTTOM (LONG) ──
        pivots_low = self._find_swings(sub_low, 'low')
        best_bottoms = None
        for i in range(len(pivots_low) - 1):
            for j in range(i + 1, len(pivots_low)):
                idx1, p1 = pivots_low[i]
                idx2, p2 = pivots_low[j]
                if idx2 - idx1 < self.min_gap_bars:
                    continue
                if abs(p1 - p2) / p1 * 100 <= self.tolerance_pct:
                    best_bottoms = (idx1, p1, idx2, p2)

        if best_bottoms is not None:
            idx1, p1, idx2, p2 = best_bottoms
            neckline = sub_high.iloc[idx1:idx2 + 1].max()
            if current_price > neckline:
                score = 30 + 15 + (35 if (current_vol_ratio >= 1.15 or is_flat_vol) else 25)
                sig.direction = 'LONG'
                checks.append(f"✅ Double Bottom détecté ({p1:.2f}$ et {p2:.2f}$)")
                checks.append(f"✅ CASSURE de la neckline @ {neckline:.2f}$")

                sl = min(p1, p2) - 0.35 * atr
                risk = current_price - sl
                pattern_height = neckline - min(p1, p2)
                tp1 = current_price + max(risk * 1.5, pattern_height * 0.5)
                tp2 = current_price + max(risk * 2.5, pattern_height * 1.0)
                rr = (tp2 - current_price) / risk if risk > 0 else 0

                sig.strength = min(score, 100)
                sig.entry = current_price
                sig.stop_loss = sl
                sig.tp1 = tp1
                sig.tp2 = tp2
                sig.risk_reward = rr
                sig.reason = f"Double Bottom | Neckline {neckline:.2f}$ | R/R {rr:.1f}:1"
                sig.checklist = checks
                return sig

        # ── 2. Chercher un DOUBLE TOP (SHORT) ──
        pivots_high = self._find_swings(sub_high, 'high')
        best_tops = None
        for i in range(len(pivots_high) - 1):
            for j in range(i + 1, len(pivots_high)):
                idx1, p1 = pivots_high[i]
                idx2, p2 = pivots_high[j]
                if idx2 - idx1 < self.min_gap_bars:
                    continue
                if abs(p1 - p2) / p1 * 100 <= self.tolerance_pct:
                    best_tops = (idx1, p1, idx2, p2)

        if best_tops is not None:
            idx1, p1, idx2, p2 = best_tops
            neckline = sub_low.iloc[idx1:idx2 + 1].min()
            if current_price < neckline:
                score = 30 + 15 + (35 if (current_vol_ratio >= 1.15 or is_flat_vol) else 25)
                sig.direction = 'SHORT'
                checks.append(f"✅ Double Top détecté ({p1:.2f}$ et {p2:.2f}$)")
                checks.append(f"✅ CASSURE de la neckline support @ {neckline:.2f}$")

                sl = max(p1, p2) + 0.35 * atr
                risk = sl - current_price
                pattern_height = max(p1, p2) - neckline
                tp1 = current_price - max(risk * 1.5, pattern_height * 0.5)
                tp2 = current_price - max(risk * 2.5, pattern_height * 1.0)
                rr = (current_price - tp2) / risk if risk > 0 else 0

                sig.strength = min(score, 100)
                sig.entry = current_price
                sig.stop_loss = sl
                sig.tp1 = tp1
                sig.tp2 = tp2
                sig.risk_reward = rr
                sig.reason = f"Double Top | Neckline {neckline:.2f}$ | R/R {rr:.1f}:1"
                sig.checklist = checks
                return sig

        checks.append("⏳ En attente de formation ou cassure de Double Bottom / Top")
        sig.strength = 20
        sig.checklist = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# #6 — INSIDE BAR BREAKOUT
# ══════════════════════════════════════════════════════════════════

class InsideBarStrategy:
    """
    Une bougie (inside bar) contenue entièrement dans le range de la
    bougie précédente (bougie mère). Entrée à la cassure du range de
    la bougie mère.
    """
    name = "Inside Bar Breakout"

    def __init__(self, config: Config, min_rr: float = 1.5):
        self.c = config
        self.min_rr = min_rr

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)
        if df is None or len(df) < 30:
            return sig

        close, high, low = df['Close'], df['High'], df['Low']
        atr = I.atr(high, low, close, 14)

        checks: List[str] = []

        # L'inside bar est l'avant-dernière bougie ; on cherche la cassure sur la dernière
        mother_high = high.iloc[-3]
        mother_low = low.iloc[-3]
        inside_high = high.iloc[-2]
        inside_low = low.iloc[-2]

        is_inside = inside_high <= mother_high and inside_low >= mother_low
        if not is_inside:
            checks.append("⏳ Pas d'inside bar détectée sur l'avant-dernière bougie")
            sig.checklist = checks
            return sig

        checks.append(f"✅ Inside bar détectée (mère : {mother_low:.2f}–{mother_high:.2f}$)")
        score = 40

        # Qualité : inside bar significativement plus petite que la mère = bonne compression
        mother_range = mother_high - mother_low
        inside_range = inside_high - inside_low
        compression = 1 - (inside_range / mother_range) if mother_range > 0 else 0
        if compression >= 0.4:
            checks.append(f"✅ Bonne compression ({compression*100:.0f}% plus petite que la mère)")
            score += 20
        else:
            checks.append(f"⚠️  Compression faible ({compression*100:.0f}%)")
            score += 5

        current_price = close.iloc[-1]
        current_vol_ratio = I.volume_ratio(df['Volume'], 20).iloc[-1]
        is_flat_vol = (df['Volume'].tail(20).std() < 1e-6) or (df['Volume'].iloc[-1] == 0)
        current_atr = atr.iloc[-1]

        if current_price > mother_high:
            checks.append(f"✅ CASSURE haussière de l'Inside Bar @ {mother_high:.2f}$")
            score += 40
            sig.direction = 'LONG'
            sl = mother_low - 0.2 * current_atr
            risk = current_price - sl
            if risk <= 0:
                sl = current_price - 1.0 * current_atr
                risk = current_price - sl
            tp1 = current_price + risk * self.min_rr
            tp2 = current_price + risk * (self.min_rr + 1.5)
            rr = (tp2 - current_price) / risk if risk > 0 else 0

        elif current_price < mother_low:
            checks.append(f"✅ CASSURE baissière de l'Inside Bar @ {mother_low:.2f}$")
            score += 40
            sig.direction = 'SHORT'
            sl = mother_high + 0.2 * current_atr
            risk = sl - current_price
            if risk <= 0:
                sl = current_price + 1.0 * current_atr
                risk = sl - current_price
            tp1 = current_price - risk * self.min_rr
            tp2 = current_price - risk * (self.min_rr + 1.5)
            rr = (current_price - tp2) / risk if risk > 0 else 0

        else:
            checks.append(f"⏳ Prix dans le range mère [{mother_low:.2f}$ – {mother_high:.2f}$]")
            sig.strength = min(score, 40)
            sig.checklist = checks
            return sig

        if current_vol_ratio >= 1.15:
            checks.append(f"✅ Volume de confirmation ({current_vol_ratio:.1f}×)")
        elif is_flat_vol:
            checks.append("ℹ️ Volume tick synthétique — validation momentum")

        sig.strength = min(score, 100)
        sig.entry = current_price
        sig.stop_loss = sl
        sig.tp1 = tp1
        sig.tp2 = tp2
        sig.risk_reward = rr
        sig.reason = f"Inside Bar {sig.direction} | Mère [{mother_low:.2f}–{mother_high:.2f}$] | R/R {rr:.1f}:1"
        sig.checklist = checks
        return sig


# ══════════════════════════════════════════════════════════════════
# #7 — OPENING RANGE BREAKOUT (ORB)
# ══════════════════════════════════════════════════════════════════

class OpeningRangeBreakoutStrategy:
    """
    Range formé pendant les N premières bougies d'une session,
    puis trade la cassure haussière ou baissière de ce range.
    """
    name = "Opening Range Breakout"

    def __init__(self, config: Config, or_bars: int = 4, min_rr: float = 2.0):
        self.c = config
        self.or_bars = or_bars
        self.min_rr = min_rr

    def generate_signal(self, ticker: str, df: pd.DataFrame,
                         session_start_hour: Optional[int] = None) -> Signal:
        sig = Signal(ticker=ticker, strategy=self.name)
        eff_bars = min(self.or_bars, 4)
        if df is None or len(df) < eff_bars + 6:
            return sig

        checks: List[str] = []

        # Isoler la session du jour courant si l'index a une date
        today_df = df
        if hasattr(df.index, 'date') and len(df.index) > 0:
            last_date = df.index[-1].date()
            today_df = df[df.index.map(lambda d: d.date()) == last_date]

        if len(today_df) <= eff_bars:
            checks.append("⏳ Formation de l'opening range en cours")
            sig.checklist = checks
            return sig

        opening_range = today_df.iloc[:eff_bars]
        or_high = opening_range['High'].max()
        or_low = opening_range['Low'].min()
        checks.append(f"✅ Opening Range ({eff_bars} b.) : {or_low:.2f}$ – {or_high:.2f}$")

        current_price = df['Close'].iloc[-1]
        current_vol_ratio = I.volume_ratio(df['Volume'], 20).iloc[-1]
        is_flat_vol = (df['Volume'].tail(20).std() < 1e-6) or (df['Volume'].iloc[-1] == 0)

        score = 30
        atr = I.atr(df['High'], df['Low'], df['Close'], 14).iloc[-1]
        or_range = or_high - or_low

        if or_range < atr * 0.3:
            checks.append("⚠️ Range d'ouverture étroit")
            score -= 5

        if current_price > or_high:
            checks.append(f"✅ CASSURE haussière de l'ORB @ {or_high:.2f}$")
            score += 45
            sig.direction = 'LONG'
            sl = or_low
            risk = current_price - sl
            if risk <= 0:
                sl = current_price - 1.0 * atr
                risk = current_price - sl
            tp1 = current_price + max(risk * self.min_rr, or_range * 1.5)
            tp2 = current_price + max(risk * (self.min_rr + 1), or_range * 2.5)
            rr = (tp2 - current_price) / risk if risk > 0 else 0

        elif current_price < or_low:
            checks.append(f"✅ CASSURE baissière de l'ORB @ {or_low:.2f}$")
            score += 45
            sig.direction = 'SHORT'
            sl = or_high
            risk = sl - current_price
            if risk <= 0:
                sl = current_price + 1.0 * atr
                risk = sl - current_price
            tp1 = current_price - max(risk * self.min_rr, or_range * 1.5)
            tp2 = current_price - max(risk * (self.min_rr + 1), or_range * 2.5)
            rr = (current_price - tp2) / risk if risk > 0 else 0

        else:
            checks.append(f"⏳ Prix dans l'ORB [{or_low:.2f}$ – {or_high:.2f}$]")
            sig.strength = min(score, 40)
            sig.checklist = checks
            return sig

        if current_vol_ratio >= 1.2:
            score += 15
            checks.append(f"✅ Volume au-dessus de la moyenne ({current_vol_ratio:.1f}×)")
        elif is_flat_vol:
            score += 10
            checks.append("ℹ️ Volume régulier/synthétique")

        sig.strength = min(score, 100)
        sig.entry = current_price
        sig.stop_loss = sl
        sig.tp1 = tp1
        sig.tp2 = tp2
        sig.risk_reward = rr
        sig.reason = f"ORB {sig.direction} | Range [{or_low:.2f}–{or_high:.2f}$] | R/R {rr:.1f}:1"
        sig.checklist = checks
        return sig
