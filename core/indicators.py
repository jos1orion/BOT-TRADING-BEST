"""
Bibliothèque d'indicateurs techniques.
Tous calculés from scratch sur pandas — pas de dépendance à TA-Lib.
"""

import numpy as np
import pandas as pd
from typing import Tuple


class Indicators:

    # ── Moyennes mobiles ──────────────────────────────────────────

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()

    # ── Volatilité ────────────────────────────────────────────────

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 14) -> pd.Series:
        """Average True Range — mesure la volatilité journalière."""
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def bollinger_bands(close: pd.Series, period: int = 20,
                        std: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Retourne (upper, mid, lower)."""
        mid   = close.rolling(period).mean()
        sigma = close.rolling(period).std()
        return mid + std * sigma, mid, mid - std * sigma

    @staticmethod
    def donchian_channel(high: pd.Series, low: pd.Series,
                         period: int = 20) -> Tuple[pd.Series, pd.Series]:
        """Retourne (channel_high, channel_low)."""
        return high.rolling(period).max(), low.rolling(period).min()

    # ── Oscillateurs ─────────────────────────────────────────────

    @staticmethod
    def rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """RSI — Relative Strength Index."""
        delta = close.diff()
        gain  = delta.clip(lower=0)
        loss  = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(close: pd.Series,
             fast: int = 12, slow: int = 26, signal: int = 9
             ) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Retourne (macd_line, signal_line, histogram)."""
        fast_ema   = close.ewm(span=fast,   adjust=False).mean()
        slow_ema   = close.ewm(span=slow,   adjust=False).mean()
        macd_line  = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram  = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                   k_period: int = 14, d_period: int = 3
                   ) -> Tuple[pd.Series, pd.Series]:
        """Retourne (%K, %D)."""
        lowest_low   = low.rolling(k_period).min()
        highest_high = high.rolling(k_period).max()
        k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
        d = k.rolling(d_period).mean()
        return k, d

    # ── Volume ───────────────────────────────────────────────────

    @staticmethod
    def volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
        """Ratio volume actuel / volume moyen sur N jours."""
        avg_vol = volume.rolling(period).mean()
        return volume / avg_vol.replace(0, np.nan)

    @staticmethod
    def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
        """On-Balance Volume."""
        direction = np.sign(close.diff()).fillna(0)
        return (direction * volume).cumsum()

    @staticmethod
    def vwap(high: pd.Series, low: pd.Series, close: pd.Series,
             volume: pd.Series) -> pd.Series:
        """Volume Weighted Average Price."""
        typical = (high + low + close) / 3
        return (typical * volume).cumsum() / volume.cumsum()

    # ── Trend ────────────────────────────────────────────────────

    @staticmethod
    def adx(high: pd.Series, low: pd.Series, close: pd.Series,
            period: int = 14) -> pd.Series:
        """ADX — Average Directional Index (force de la tendance)."""
        up_move   = high.diff()
        down_move = -low.diff()
        plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        atr_vals  = Indicators.atr(high, low, close, period)
        plus_di   = 100 * pd.Series(plus_dm,  index=close.index).ewm(com=period-1, adjust=False).mean() / atr_vals
        minus_di  = 100 * pd.Series(minus_dm, index=close.index).ewm(com=period-1, adjust=False).mean() / atr_vals
        dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        return dx.ewm(com=period-1, adjust=False).mean()

    @staticmethod
    def adr_pct(high: pd.Series, low: pd.Series, period: int = 20) -> float:
        """Average Daily Range en pourcentage (filtre screener)."""
        daily_range = (high - low) / low * 100
        return daily_range.tail(period).mean()

    @staticmethod
    def correlation(close_a: pd.Series, close_b: pd.Series, window: int = 60) -> float:
        """
        Corrélation des rendements quotidiens entre deux actifs sur les
        `window` dernières bougies communes. Utilisée pour éviter de cumuler
        du risque sur des actifs qui bougent ensemble (ex: NVDA/AMD/MU)
        même s'ils sont classés dans des "secteurs" différents.
        Retourne un float entre -1 et 1 (0.0 si données insuffisantes).
        """
        ret_a = close_a.pct_change().dropna()
        ret_b = close_b.pct_change().dropna()
        aligned = pd.concat([ret_a, ret_b], axis=1, join='inner').tail(window)
        if len(aligned) < 20:
            return 0.0
        corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
        return float(corr) if pd.notna(corr) else 0.0

    @staticmethod
    def relative_strength(close: pd.Series, benchmark: pd.Series,
                          period: int = 63) -> float:
        """
        Relative Strength vs indice de référence sur N jours.
        > 0 = surperformance, < 0 = sous-performance.
        """
        stock_perf = (close.iloc[-1] / close.iloc[-period] - 1) * 100
        bench_perf = (benchmark.iloc[-1] / benchmark.iloc[-period] - 1) * 100
        return stock_perf - bench_perf
