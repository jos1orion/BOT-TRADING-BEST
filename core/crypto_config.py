"""
Configuration dédiée aux cryptos, pour le backtest et le paper trading
Mean Reversion / Liquidity Sweep sur BingX.

Hérite de core.config.Config et ne change que ce qui doit différer pour
la crypto (watchlist, pas de filtre marché SPY/QQQ pertinent, etc.).
"""

from dataclasses import dataclass
from typing import List
from core.config import Config


@dataclass
class CryptoConfig(Config):
    # La crypto trade 24/7 — pas de "session" à filtrer, pas de NFP/FOMC
    # de la même façon que le forex (mais les annonces macro US influencent
    # quand même BTC — on peut réactiver avoid_news si souhaité).
    avoid_news: bool = False

    # Mean Reversion : RSI/Bollinger fonctionnent globalement pareil,
    # mais la crypto est plus volatile — bandes un peu plus larges.
    bb_std: float = 2.2

    # Utilisés uniquement pour les ordres MANUELS (ex: /buy via Telegram),
    # où il n'y a pas de stop-loss/TP calculé par une stratégie.
    manual_stop_loss_pct: float = 5.0
    manual_take_profit_pct: float = 10.0

    # Liquidity Sweep : la crypto a énormément de zones de liquidité
    # autour des nombres ronds (BTC 100k, ETH 4000...) — déjà géré par
    # use_round_numbers=True dans la stratégie.

    @property
    def watchlist(self) -> List[str]:
        # Tickers yfinance (pour le backtest avec données gratuites).
        # Équivalents BingX entre parenthèses pour le paper/live trading :
        return [
            'BTC-USD',   # BTC-USDT
            'ETH-USD',   # ETH-USDT
            'SOL-USD',   # SOL-USDT
            'BNB-USD',   # BNB-USDT
            'XRP-USD',   # XRP-USDT
            'ADA-USD',   # ADA-USDT
            'DOGE-USD',  # DOGE-USDT
            'AVAX-USD',  # AVAX-USDT
        ]

    @property
    def sector_map(self):
        # Pas de notion de "secteur" en crypto — tout dans une seule
        # catégorie pour ne pas casser le contrôle d'exposition existant.
        return {t: 'Crypto' for t in self.watchlist}
