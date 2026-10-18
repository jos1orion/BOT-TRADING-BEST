"""
Filtres de sécurité anti-rug / anti-honeypot.

Objectif : rejeter le plus tôt possible les tokens qui présentent des
signaux classiques d'arnaque, AVANT d'envoyer la moindre transaction
d'achat. En mode "strict", on préfère rater des opportunités plutôt que
de risquer le capital sur un token suspect.

⚠️ Ces filtres réduisent le risque mais ne l'éliminent jamais. Un token
peut passer tous les checks et être quand même un rug (ex: rug via
retrait de liquidité par un wallet tiers non détecté, ou exploit de
contrat). Aucun filtre automatique ne remplace une vérification humaine
pour des montants significatifs.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from core.solana.config import SolanaConfig
from core.solana.spl_utils import get_mint_info

logger = logging.getLogger("solana.filters")


@dataclass
class TokenSafetyReport:
    mint: str
    passed: bool
    liquidity_usd: float
    holder_count: int
    top10_holder_pct: float
    mint_authority_revoked: bool
    freeze_authority_revoked: bool
    buy_tax_pct: float
    sell_tax_pct: float
    reasons_rejected: list


class TokenSafetyChecker:
    """
    Interroge le RPC (getAccountInfo, getTokenLargestAccounts, etc.) et/ou
    une API tierce (ex: RugCheck, Birdeye, Helius DAS) pour évaluer un
    token candidat. Les appels concrets dépendent du fournisseur RPC
    choisi — voir les TODO ci-dessous.
    """

    def __init__(self, config: SolanaConfig, rugcheck_api_url: Optional[str] = None):
        self.config = config
        # RugCheck.xyz propose une API publique de scoring de risque —
        # à confirmer/adapter selon leur documentation au moment de l'usage.
        self.rugcheck_api_url = rugcheck_api_url or "https://api.rugcheck.xyz/v1/tokens/{mint}/report"

    def check(self, mint: str) -> TokenSafetyReport:
        reasons = []

        liquidity_usd = self._get_liquidity_usd(mint)
        holder_count = self._get_holder_count(mint)
        top10_pct = self._get_top10_holder_pct(mint)
        mint_revoked = self._is_mint_authority_revoked(mint)
        freeze_revoked = self._is_freeze_authority_revoked(mint)
        buy_tax, sell_tax = self._get_buy_sell_tax(mint)

        if liquidity_usd < self.config.min_liquidity_usd:
            reasons.append(f"Liquidité trop faible: ${liquidity_usd:,.0f} "
                            f"< ${self.config.min_liquidity_usd:,.0f}")

        if holder_count < self.config.min_holders:
            reasons.append(f"Trop peu de holders: {holder_count} "
                            f"< {self.config.min_holders}")

        if top10_pct > self.config.max_top10_holder_pct:
            reasons.append(f"Concentration top 10 trop élevée: {top10_pct:.1f}% "
                            f"> {self.config.max_top10_holder_pct:.1f}%")

        if self.config.require_mint_authority_revoked and not mint_revoked:
            reasons.append("Mint authority non révoquée (le créateur peut "
                            "émettre des tokens supplémentaires à volonté)")

        if self.config.require_freeze_authority_revoked and not freeze_revoked:
            reasons.append("Freeze authority non révoquée (le créateur peut "
                            "geler ton wallet / bloquer les ventes)")

        if buy_tax > self.config.max_buy_sell_tax_pct or sell_tax > self.config.max_buy_sell_tax_pct:
            reasons.append(f"Taxe buy/sell suspecte: {buy_tax:.1f}%/{sell_tax:.1f}%")

        return TokenSafetyReport(
            mint=mint,
            passed=(len(reasons) == 0),
            liquidity_usd=liquidity_usd,
            holder_count=holder_count,
            top10_holder_pct=top10_pct,
            mint_authority_revoked=mint_revoked,
            freeze_authority_revoked=freeze_revoked,
            buy_tax_pct=buy_tax,
            sell_tax_pct=sell_tax,
            reasons_rejected=reasons,
        )

    # ── Les méthodes suivantes sont des points d'intégration à
    # brancher sur un vrai fournisseur de données (Helius DAS API,
    # Birdeye, RugCheck...) selon celui que tu choisis. Retournent des
    # valeurs "sûres par défaut" (rejetantes) tant que non implémentées,
    # pour ne jamais autoriser un trade par erreur silencieuse.

    def _get_liquidity_usd(self, mint: str) -> float:
        # TODO: brancher sur l'API du RPC choisi (ex: Birdeye /defi/token_overview,
        # ou décoder directement le compte de pool Raydium).
        logger.warning("_get_liquidity_usd non implémenté — retourne 0 (rejet par défaut)")
        return 0.0

    def _get_holder_count(self, mint: str) -> int:
        # TODO: getTokenLargestAccounts + getProgramAccounts filtré, ou API tierce.
        logger.warning("_get_holder_count non implémenté — retourne 0 (rejet par défaut)")
        return 0

    def _get_top10_holder_pct(self, mint: str) -> float:
        # TODO: calculer à partir de getTokenLargestAccounts / supply total.
        logger.warning("_get_top10_holder_pct non implémenté — retourne 100 (rejet par défaut)")
        return 100.0

    def _is_mint_authority_revoked(self, mint: str) -> bool:
        info = get_mint_info(self.config.rpc_http_url, mint)
        if info is None:
            return False  # RPC injoignable/erreur -> rejet par sécurité
        return info.mint_authority_revoked

    def _is_freeze_authority_revoked(self, mint: str) -> bool:
        info = get_mint_info(self.config.rpc_http_url, mint)
        if info is None:
            return False
        return info.freeze_authority_revoked

    def _get_buy_sell_tax(self, mint: str) -> tuple:
        # TODO: simulation d'un swap aller-retour minime via Jupiter Quote API
        # pour mesurer l'écart réel (méthode la plus fiable pour détecter
        # une taxe cachée dans le contrat).
        return (100.0, 100.0)  # rejet par défaut tant que non implémenté
