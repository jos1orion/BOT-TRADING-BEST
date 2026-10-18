"""
Gestionnaire de risque.
Calcule la taille de position, vérifie les limites d'exposition,
et gère le portfolio en temps réel (paper trading).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
import pandas as pd
from core.config import Config
from strategies.strategies import Signal


@dataclass
class Position:
    ticker:        str
    strategy:      str
    direction:     str
    entry_price:   float
    shares:        int
    stop_loss:     float
    tp1:           float
    tp2:           float
    entry_date:    datetime = field(default_factory=datetime.now)
    current_price: float    = 0.0
    status:        str      = 'OPEN'       # OPEN | CLOSED
    exit_price:    float    = 0.0
    exit_date:     Optional[datetime] = None
    exit_reason:   str      = ''
    partial_exits: List[Dict] = field(default_factory=list)
    # Scale Out tracking
    shares_sold_tp1: int = 0
    shares_sold_tp2: int = 0
    stop_moved_to_be: bool = False

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.shares

    @property
    def unrealized_pnl(self) -> float:
        if self.status == 'OPEN':
            return (self.current_price - self.entry_price) * self.shares
        return 0.0

    @property
    def realized_pnl(self) -> float:
        total = 0.0
        for ex in self.partial_exits:
            total += (ex['price'] - self.entry_price) * ex['shares']
        if self.status == 'CLOSED':
            remaining = self.shares - sum(e['shares'] for e in self.partial_exits)
            total += (self.exit_price - self.entry_price) * remaining
        return total

    @property
    def total_pnl(self) -> float:
        return self.unrealized_pnl + self.realized_pnl

    @property
    def pnl_pct(self) -> float:
        return (self.current_price / self.entry_price - 1) * 100 if self.entry_price > 0 else 0


class RiskManager:
    """
    Gère le risque par trade et au niveau du portfolio.
    """

    def __init__(self, config: Config):
        self.c = config

    def estimate_fill_price(self, intended_price: float, direction: str = 'LONG') -> float:
        """
        Estime le prix d'exécution réel en tenant compte du slippage.
        Un achat (LONG) s'exécute typiquement un peu plus cher que le prix
        visé, une vente à découvert (SHORT) un peu moins cher.
        """
        slip = intended_price * (self.c.slippage_pct / 100)
        return intended_price + slip if direction == 'LONG' else intended_price - slip

    def calculate_position_size(self, signal: Signal,
                                 available_capital: float) -> int:
        """
        Calcule le nombre d'actions à acheter selon le risque défini.

        Formule : shares = (capital × risk%) / (entry_reel - stop_loss)
        où entry_reel intègre le slippage estimé, pour ne jamais sous-estimer
        le risque réel pris sur un marché qui bouge vite (ex: indices CFD).
        Ne jamais risquer plus de risk_per_trade% du capital par trade.
        """
        if signal.entry <= 0 or signal.stop_loss <= 0:
            return 0

        entry_reel = self.estimate_fill_price(signal.entry, signal.direction or 'LONG')

        risk_amount = available_capital * self.c.risk_per_trade
        risk_per_share = abs(entry_reel - signal.stop_loss)

        if risk_per_share <= 0:
            return 0

        shares = int(risk_amount / risk_per_share)

        # Plafonner à 20% du capital par position (au prix réel estimé)
        max_position_value = available_capital * 0.20
        max_shares_by_capital = int(max_position_value / entry_reel) if entry_reel > 0 else 0
        shares = min(shares, max_shares_by_capital)

        return max(shares, 0)

    def can_open_position(self, signal: Signal,
                           open_positions: List[Position],
                           available_capital: float,
                           sector_map: Dict[str, str],
                           avg_daily_volume: Optional[float] = None,
                           correlation_fn: Optional[callable] = None) -> tuple[bool, str]:
        """
        Vérifie si on peut ouvrir une nouvelle position.
        Retourne (can_open: bool, reason: str).

        Args:
            avg_daily_volume : volume moyen (20j) de l'actif, pour le contrôle
                                de liquidité (évite le slippage sur les petites caps).
            correlation_fn   : fonction optionnelle (ticker_a, ticker_b) -> float
                                retournant la corrélation des rendements. Si fournie,
                                plafonne le nombre de positions ouvertes simultanément
                                sur des actifs fortement corrélés.
        """
        # 1. Trop de positions
        open_count = sum(1 for p in open_positions if p.status == 'OPEN')
        if open_count >= self.c.max_positions:
            return False, f"Limite de {self.c.max_positions} positions atteinte"

        # 2. Déjà en position sur ce ticker
        for p in open_positions:
            if p.ticker == signal.ticker and p.status == 'OPEN':
                return False, f"Position déjà ouverte sur {signal.ticker}"

        # 3. Exposition sectorielle max
        sector = sector_map.get(signal.ticker, 'Unknown')
        sector_value = sum(
            p.current_price * p.shares
            for p in open_positions
            if p.status == 'OPEN' and sector_map.get(p.ticker) == sector
        )
        portfolio_value = available_capital + sum(
            p.current_price * p.shares for p in open_positions if p.status == 'OPEN'
        )
        if portfolio_value > 0:
            sector_pct = sector_value / portfolio_value
            if sector_pct >= self.c.max_sector_exposure:
                return False, f"Exposition secteur '{sector}' déjà à {sector_pct:.0%}"

        # 4. Corrélation avec les positions déjà ouvertes
        # (deux actifs peuvent être dans des "secteurs" différents mais bouger
        # ensemble — ex: NVDA/AMD/MU — d'où ce second garde-fou indépendant.)
        if correlation_fn is not None:
            correlated_count = 0
            for p in open_positions:
                if p.status != 'OPEN' or p.ticker == signal.ticker:
                    continue
                try:
                    corr = correlation_fn(signal.ticker, p.ticker)
                except Exception:
                    corr = 0.0
                if corr is not None and abs(corr) >= self.c.correlation_threshold:
                    correlated_count += 1
            if correlated_count >= self.c.max_correlated_positions:
                return False, (
                    f"Déjà {correlated_count} position(s) fortement corrélée(s) "
                    f"(≥{self.c.correlation_threshold:.0%}) avec {signal.ticker}"
                )

        # 5. Capital suffisant
        shares = self.calculate_position_size(signal, available_capital)
        if shares == 0:
            return False, "Capital insuffisant ou risque trop élevé"
        entry_reel = self.estimate_fill_price(signal.entry, signal.direction or 'LONG')
        cost = shares * entry_reel
        if cost > available_capital:
            return False, f"Capital insuffisant (besoin {cost:.0f}$, disponible {available_capital:.0f}$)"

        # 6. Liquidité : ne jamais représenter plus de max_volume_participation_pct
        # du volume moyen (évite un slippage important sur les faibles capitalisations)
        if avg_daily_volume and avg_daily_volume > 0:
            participation_pct = shares / avg_daily_volume * 100
            if participation_pct > self.c.max_volume_participation_pct:
                max_shares_liquidity = int(avg_daily_volume * self.c.max_volume_participation_pct / 100)
                if max_shares_liquidity < 1:
                    return False, (
                        f"Liquidité insuffisante : volume moyen {avg_daily_volume:,.0f}, "
                        f"taille visée {shares} actions ({participation_pct:.1f}% du volume)"
                    )
                # On ne bloque pas totalement : le sizing sera réduit par l'appelant si besoin.

        return True, "OK"

    def cap_shares_by_liquidity(self, shares: int, avg_daily_volume: Optional[float]) -> int:
        """Réduit (si besoin) le nombre d'actions pour respecter max_volume_participation_pct."""
        if not avg_daily_volume or avg_daily_volume <= 0:
            return shares
        max_shares = int(avg_daily_volume * self.c.max_volume_participation_pct / 100)
        return min(shares, max_shares) if max_shares > 0 else shares

    def check_exits(self, position: Position,
                     current_price: float) -> Optional[str]:
        """
        Vérifie si une position doit être fermée ou partiellement réduite.
        Retourne: 'STOP' | 'TP1' | 'TP2' | 'TRAIL_EMA8' | None
        """
        position.current_price = current_price

        if position.direction == 'LONG':
            # Stop Loss touché
            if current_price <= position.stop_loss:
                return 'STOP'

            # TP1 atteint (vendre 25%)
            if current_price >= position.tp1 and position.shares_sold_tp1 == 0:
                return 'TP1'

            # TP2 atteint (vendre 25% de plus)
            if current_price >= position.tp2 and position.shares_sold_tp2 == 0:
                return 'TP2'

        return None

    def update_trailing_stop(self, position: Position,
                              ema8: float, ema21: float) -> None:
        """
        Met à jour le stop loss suiveur basé sur les EMA (après TP1).
        """
        if position.status != 'OPEN' or position.shares_sold_tp1 == 0:
            return

        if not position.stop_moved_to_be:
            # Déplacer le SL au prix d'entrée après TP1 (break even)
            if position.current_price >= position.tp1:
                position.stop_loss = position.entry_price
                position.stop_moved_to_be = True
        else:
            # Trailing stop sur EMA 8 puis EMA 21
            new_stop = max(ema8 * 0.995, position.stop_loss)
            if new_stop > position.stop_loss:
                position.stop_loss = new_stop
