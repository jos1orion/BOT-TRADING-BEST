"""
Sélection de paires "façon Bobby" — principes tirés de la vidéo sur le
robot forex "Bobby" (chaîne Leo Trading-Algo), PAS son edge (jamais
révélé) mais sa philosophie de choix d'instrument :

  - éviter les paires trop directionnelles (ex. USD/JPY dans la
    vidéo) qui "font les montagnes russes" ;
  - préférer une paire qui "respire régulièrement", qui respecte des
    niveaux de support/résistance plutôt que de tendre en ligne
    droite ;
  - une volatilité modérée (ni trop plate, ni trop erratique) pour
    que le sizing en % de risque reste cohérent d'un trade à l'autre.

Ce module note chaque symbole de la watchlist sur ces critères pour
aider à choisir où concentrer les stratégies de range/mean-reversion
du bot (ex. MeanReversionStrategy, filtre ADX < 25 déjà utilisé dans
core/market_filter.py) — ce n'est pas une nouvelle stratégie de
signal, seulement un filtre de sélection d'instrument en amont.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from core.indicators import Indicators as I


@dataclass
class RangeAffinity:
    ticker: str
    adx_avg: float          # force de tendance moyenne (bas = range)
    autocorr_lag1: float    # autocorrélation des rendements (négatif = mean-reversion)
    adr_pct: float          # amplitude journalière moyenne en %
    score: float            # 0-100, plus haut = plus "façon Bobby"
    verdict: str            # étiquette lisible

    def __str__(self):
        return (f"{self.ticker:<10} score={self.score:5.1f}  "
                f"ADX moy={self.adx_avg:5.1f}  autocorr={self.autocorr_lag1:+.2f}  "
                f"ADR={self.adr_pct:4.2f}%  → {self.verdict}")


def _score_from_adx(adx_avg: float) -> float:
    """ADX bas = marché qui range = meilleur score. ADX > 35 pénalisé fort."""
    if np.isnan(adx_avg):
        return 50.0
    if adx_avg <= 15:
        return 100.0
    if adx_avg >= 40:
        return 0.0
    return round(100.0 - ((adx_avg - 15) / (40 - 15)) * 100.0, 1)


def _score_from_autocorr(autocorr: float) -> float:
    """Autocorrélation négative des rendements = tendance à revenir
    vers un niveau (respect de S/R) = meilleur score."""
    if np.isnan(autocorr):
        return 50.0
    clipped = max(-0.3, min(0.3, autocorr))
    return round(((-clipped + 0.3) / 0.6) * 100.0, 1)


def _score_from_adr(adr_pct: float) -> float:
    """Volatilité modérée préférée : trop plat (< 0.3%) ou trop erratique
    (> 2%) pénalisé — zone confortable pour un sizing % de risque stable."""
    if np.isnan(adr_pct):
        return 50.0
    if 0.4 <= adr_pct <= 1.2:
        return 100.0
    if adr_pct < 0.4:
        return round((adr_pct / 0.4) * 100.0, 1)
    return round(max(0.0, 100.0 - (adr_pct - 1.2) * 60.0), 1)


def score_range_affinity(ticker: str, df: pd.DataFrame, adx_period: int = 14) -> RangeAffinity:
    """Calcule le score "façon Bobby" d'un symbole à partir de son
    historique OHLC (df avec colonnes High/Low/Close, index temporel)."""
    high, low, close = df['High'], df['Low'], df['Close']

    adx_series = I.adx(high, low, close, adx_period)
    adx_avg = float(adx_series.tail(90).mean()) if len(adx_series) else float('nan')

    returns = close.pct_change().dropna()
    if len(returns) > 20:
        autocorr = float(returns.autocorr(lag=1))
    else:
        autocorr = float('nan')

    adr = float(I.adr_pct(high, low, 20))

    s_adx = _score_from_adx(adx_avg)
    s_auto = _score_from_autocorr(autocorr)
    s_adr = _score_from_adr(adr)
    score = round(s_adx * 0.45 + s_auto * 0.35 + s_adr * 0.20, 1)

    if score >= 70:
        verdict = "Respecte bien ses ranges — adapté au style Bobby"
    elif score >= 45:
        verdict = "Mixte — surveiller les phases de tendance"
    else:
        verdict = "Trop directionnel — mieux pour du trend-following"

    return RangeAffinity(ticker=ticker, adx_avg=round(adx_avg, 1) if not np.isnan(adx_avg) else float('nan'),
                          autocorr_lag1=round(autocorr, 3) if not np.isnan(autocorr) else float('nan'),
                          adr_pct=round(adr, 2), score=score, verdict=verdict)


def rank_symbols(symbol_dfs: Dict[str, pd.DataFrame]) -> List[RangeAffinity]:
    """Classe une liste de symboles du meilleur au moins adapté au style
    'range respecté / drawdown maîtrisé' décrit dans la vidéo."""
    results = [score_range_affinity(sym, df) for sym, df in symbol_dfs.items() if df is not None and len(df) > 90]
    return sorted(results, key=lambda r: r.score, reverse=True)


def print_ranking(symbol_dfs: Dict[str, pd.DataFrame]) -> None:
    ranking = rank_symbols(symbol_dfs)
    if not ranking:
        print("Pas assez de données pour classer les symboles (90 bougies minimum).")
        return
    print("\n📐 CLASSEMENT 'AFFINITÉ RANGE' (façon Bobby — support/résistance, pas de tendance forcenée)")
    for r in ranking:
        print(f"  {r}")
