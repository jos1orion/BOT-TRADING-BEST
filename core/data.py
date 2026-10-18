"""
Module de récupération des données de marché via yfinance.
Toutes les données sont gratuites et ne nécessitent pas de clé API.
"""

import time
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Optional, Dict, List


class DataFetcher:
    """Récupère et met en cache les données OHLCV depuis Yahoo Finance."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._cache: Dict[str, pd.DataFrame] = {}

    def get_ohlcv(self, ticker: str, period: str = '1y',
                  interval: str = '1d') -> Optional[pd.DataFrame]:
        """
        Retourne un DataFrame OHLCV pour un ticker donné.
        Colonnes: Open, High, Low, Close, Volume
        """
        cache_key = f"{ticker}_{period}_{interval}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            df = yf.download(ticker, period=period, interval=interval,
                             auto_adjust=True, progress=False)
            if df.empty:
                return None

            # Nettoyage
            df.index = pd.to_datetime(df.index)
            df = df.dropna()
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

            self._cache[cache_key] = df
            if self.verbose:
                print(f"  ✓ {ticker}: {len(df)} jours chargés")
            return df

        except Exception as e:
            if self.verbose:
                print(f"  ✗ {ticker}: erreur — {e}")
            return None

    def get_fundamentals(self, ticker: str) -> Dict:
        """Retourne les données fondamentales (P/E, EPS, Market Cap, etc.)."""
        try:
            info = yf.Ticker(ticker).info
            return {
                'market_cap':        info.get('marketCap', 0),
                'pe_ratio':          info.get('trailingPE', None),
                'forward_pe':        info.get('forwardPE', None),
                'eps_ttm':           info.get('trailingEps', None),
                'eps_growth_yoy':    info.get('earningsQuarterlyGrowth', 0) * 100 if info.get('earningsQuarterlyGrowth') else None,
                'revenue_growth':    info.get('revenueGrowth', 0) * 100 if info.get('revenueGrowth') else None,
                'profit_margin':     info.get('profitMargins', 0) * 100 if info.get('profitMargins') else None,
                'return_on_equity':  info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else None,
                'debt_to_equity':    info.get('debtToEquity', None),
                'sector':            info.get('sector', 'N/A'),
                'industry':          info.get('industry', 'N/A'),
                'short_name':        info.get('shortName', ticker),
                'avg_volume':        info.get('averageVolume', 0),
                'float_shares':      info.get('floatShares', 0),
            }
        except Exception:
            return {}

    def get_multiple(self, tickers: List[str], period: str = '1y') -> Dict[str, pd.DataFrame]:
        """Télécharge plusieurs tickers en batch (plus rapide)."""
        results = {}
        try:
            raw = yf.download(tickers, period=period, auto_adjust=True,
                              progress=False, group_by='ticker')
            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        df = raw.copy()
                    else:
                        df = raw[ticker].copy()
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                    df = df.dropna()
                    if not df.empty:
                        results[ticker] = df
                except Exception:
                    pass
        except Exception:
            # Fallback: télécharger un par un
            for ticker in tickers:
                df = self.get_ohlcv(ticker, period=period)
                if df is not None:
                    results[ticker] = df
                time.sleep(0.1)
        return results
