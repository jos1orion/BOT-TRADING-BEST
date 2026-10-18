"""
Filtre de marché adapté par classe d'actif.

Le filtre "SPY/QQQ au-dessus des EMA" (issu du PDF) est pertinent
pour les actions US, mais n'a pas de sens pour le Forex ou les
indices européens : on utilise un indice de référence différent
selon la classe d'actif, et à défaut on retombe sur la tendance
propre de l'instrument (EMA 8/21/50 sur lui-même).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import pandas as pd

from core.indicators import Indicators as I


ASSET_CLASSES = ("us_equity", "forex", "eu_index", "us_index", "commodity", "crypto", "synthetic")

# Benchmarks utilisés pour juger le "contexte de marché" selon la classe d'actif.
# Ce sont des tickers yfinance (utilisés par core/data.py).
DEFAULT_BENCHMARKS: Dict[str, List[str]] = {
    "us_equity": ["SPY", "QQQ"],
    "us_index":  ["SPY", "QQQ"],
    "eu_index":  ["^GDAXI", "^FCHI"],       # DAX, CAC40
    "forex":     ["DX-Y.NYB"],               # Indice dollar (DXY) comme proxy de régime
    "commodity": ["DX-Y.NYB"],
    "crypto":    ["BTC-USD"],
}

FOREX_SUFFIXES = ("=X",)
EU_INDEX_TICKERS = {"^GDAXI", "^FCHI", "^FTSE", "DE40", "FR40", "UK100"}
US_INDEX_TICKERS = {"^GSPC", "^NDX", "^DJI", "US500", "US100", "SPY", "QQQ",
                    "US SP 500", "US TECH 100", "WALL STREET 30"}
CRYPTO_TICKERS_HINTS = ("BTC", "ETH")


def guess_asset_class(symbol: str) -> str:
    """Devine la classe d'actif à partir du symbole (best effort)."""
    s = symbol.upper()
    # Indices synthétiques Deriv (Volatility, Boom, Crash, Step, Jump) :
    # aucun benchmark externe pertinent → tendance propre de l'instrument.
    if any(h in s for h in ("VOLATILITY", "BOOM", "CRASH", "STEP INDEX", "JUMP")):
        return "synthetic"
    if s in EU_INDEX_TICKERS or s in ("GERMANY 40", "FRANCE 40", "UK 100"):
        return "eu_index"
    if s in US_INDEX_TICKERS:
        return "us_index"
    if any(s.endswith(suf) for suf in FOREX_SUFFIXES) or (len(s) == 6 and s.isalpha()):
        return "forex"
    if any(h in s for h in CRYPTO_TICKERS_HINTS):
        return "crypto"
    if s in ("XAUUSD", "XAGUSD", "GC=F", "SI=F", "USOIL", "UKOIL", "CL=F"):
        return "commodity"
    return "us_equity"


@dataclass
class MarketFilter:
    """
    Évalue la condition de marché ('BULL' | 'BEAR' | 'NEUTRAL')
    adaptée à la classe d'actif du symbole analysé.
    """
    data_fetcher: object                     # instance de DataFetcher (duck-typed pour éviter import circulaire)
    ema_short: int = 8
    ema_mid: int = 21
    ema_long: int = 50
    _cache: Dict[str, str] = field(default_factory=dict)

    def get_condition(self, symbol: str, df_self: Optional[pd.DataFrame] = None,
                       asset_class: Optional[str] = None) -> str:
        """
        Retourne 'BULL' | 'BEAR' | 'NEUTRAL' pour le symbole donné.

        1. Tente d'utiliser le(s) benchmark(s) approprié(s) à la classe d'actif.
        2. Si les benchmarks sont indisponibles, retombe sur la tendance propre
           de l'instrument (EMA 8/21/50 sur df_self) — utile pour le Forex/CFD
           où les indices actions ne sont pas pertinents.
        """
        asset_class = asset_class or guess_asset_class(symbol)
        cache_key = asset_class
        if cache_key in self._cache:
            return self._cache[cache_key]

        benchmarks = DEFAULT_BENCHMARKS.get(asset_class, [])
        condition = self._condition_from_benchmarks(benchmarks)

        if condition is None:
            condition = self._condition_from_self(df_self) if df_self is not None else "NEUTRAL"

        self._cache[cache_key] = condition
        return condition

    def _condition_from_benchmarks(self, benchmarks: List[str]) -> Optional[str]:
        if not benchmarks:
            return None
        bull_count = 0
        bear_count = 0
        valid = 0

        for idx in benchmarks:
            df = self.data_fetcher.get_ohlcv(idx, period='6mo')
            if df is None or len(df) < self.ema_long + 5:
                continue
            valid += 1
            close = df['Close']
            e8  = I.ema(close, self.ema_short)
            e21 = I.ema(close, self.ema_mid)
            e50 = I.ema(close, self.ema_long)
            price = close.iloc[-1]
            if price > e8.iloc[-1] and price > e21.iloc[-1] and price > e50.iloc[-1]:
                bull_count += 1
            elif price < e8.iloc[-1] and price < e21.iloc[-1]:
                bear_count += 1

        if valid == 0:
            return None
        if bull_count == valid:
            return 'BULL'
        elif bear_count >= 1:
            return 'BEAR'
        return 'NEUTRAL'

    def _condition_from_self(self, df: pd.DataFrame) -> str:
        """Fallback : juge la tendance de l'instrument lui-même."""
        if df is None or len(df) < self.ema_long + 5:
            return 'NEUTRAL'
        close = df['Close']
        e8  = I.ema(close, self.ema_short).iloc[-1]
        e21 = I.ema(close, self.ema_mid).iloc[-1]
        e50 = I.ema(close, self.ema_long).iloc[-1]
        price = close.iloc[-1]
        if price > e8 and price > e21 and price > e50:
            return 'BULL'
        elif price < e8 and price < e21:
            return 'BEAR'
        return 'NEUTRAL'

    def clear_cache(self):
        self._cache.clear()
