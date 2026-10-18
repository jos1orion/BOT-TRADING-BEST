"""
Wallet tracking / copy trading.

Surveille des wallets Solana spécifiques (adresses publiques données par
l'utilisateur — jamais de clé privée ici) et détecte leurs achats/ventes
récents, pour éventuellement les répliquer.

⚠️ Le copy trading a ses propres risques : le wallet suivi peut être plus
rapide que toi (donc tu achètes après lui, à un prix déjà monté), peut
lui-même se faire piéger, ou peut être un wallet "leurre" utilisé pour
attirer des copieurs avant un rug.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

import requests

from core.solana.config import SolanaConfig

logger = logging.getLogger("solana.wallet_tracker")


@dataclass
class WalletTrade:
    wallet: str
    signature: str
    mint: str
    side: str          # "BUY" ou "SELL"
    amount_sol: float
    timestamp: int


class WalletTracker:
    def __init__(self, config: SolanaConfig):
        self.config = config
        self._last_signature_seen = {}  # wallet -> dernière signature traitée

    def get_recent_trades(self, wallet: str, limit: int = 20) -> List[WalletTrade]:
        """
        Récupère les transactions récentes d'un wallet et essaie d'en
        extraire les swaps (achats/ventes de tokens).

        TODO: implémenter via getSignaturesForAddress + getTransaction
        sur le RPC configuré, ou via une API enrichie (Helius "Enhanced
        Transactions API" qui parse déjà les swaps pour toi — bien plus
        simple qu'un décodage manuel des instructions Raydium/Jupiter).
        """
        logger.warning("get_recent_trades non implémenté — retourne liste vide")
        return []

    def poll_all_tracked_wallets(self) -> List[WalletTrade]:
        """À appeler en boucle (ex: toutes les 2-5s) pour détecter les
        nouveaux trades de tous les wallets suivis dans la config."""
        new_trades = []
        for wallet in self.config.tracked_wallets:
            trades = self.get_recent_trades(wallet)
            for t in trades:
                if t.signature != self._last_signature_seen.get(wallet):
                    new_trades.append(t)
            if trades:
                self._last_signature_seen[wallet] = trades[0].signature
        return new_trades
