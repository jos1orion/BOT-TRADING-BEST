"""
Configuration du module Solana (sniping, filtres, wallet tracking).
"""

from dataclasses import dataclass, field
from typing import List


# Program IDs connus (vérifiés publiquement, stables) — pas besoin de clé
RAYDIUM_AMM_V4_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RAYDIUM_CPMM_PROGRAM_ID = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
OPENBOOK_MARKET_PROGRAM_ID = "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX"
PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

# Adresse SOL (mint natif "wrapped") — sert de quote token de référence
WSOL_MINT = "So11111111111111111111111111111111111111112"


@dataclass
class SolanaConfig:
    # ── Connexion RPC ────────────────────────────────────────────
    # Un RPC public gratuit (ex: https://api.mainnet-beta.solana.com) est
    # fortement rate-limité et NE PERMET PAS un sniping fiable.
    # Fournisseurs dédiés recommandés : Helius, QuickNode, Triton.
    rpc_http_url: str = "https://api.mainnet-beta.solana.com"
    rpc_ws_url: str = "wss://api.mainnet-beta.solana.com"

    # ── Programmes à surveiller pour la détection de nouveaux tokens
    watched_programs: List[str] = field(default_factory=lambda: [
        RAYDIUM_AMM_V4_PROGRAM_ID,
        PUMP_FUN_PROGRAM_ID,
    ])

    # ── Filtres anti-rug / anti-honeypot (mode "strict") ───────────
    min_liquidity_usd: float = 5_000.0      # liquidité minimum dans la pool
    min_holders: int = 30                    # nombre minimum de détenteurs
    max_top10_holder_pct: float = 60.0       # top 10 wallets ne doivent pas
                                              # détenir plus de X% du supply
    require_mint_authority_revoked: bool = True    # mint authority = None
    require_freeze_authority_revoked: bool = True  # freeze authority = None
    max_buy_sell_tax_pct: float = 5.0        # taxe buy/sell max tolérée
    min_pool_age_seconds: int = 30           # laisser passer les tout 1ers
                                              # instants (souvent honeypot bot)
    max_pool_age_seconds: int = 300          # au-delà, ce n'est plus du sniping

    # ── Sizing / risque ─────────────────────────────────────────
    max_snipe_usd: float = 20.0              # capital max par snipe (à
                                              # ajuster selon ton budget réel)
    max_concurrent_positions: int = 3
    take_profit_pct: float = 100.0           # x2 -> vente partielle
    stop_loss_pct: float = 40.0

    # ── Wallet tracking (copy trading) ──────────────────────────
    tracked_wallets: List[str] = field(default_factory=list)  # adresses publiques
    copy_trade_max_usd: float = 20.0

    # ── Mode ─────────────────────────────────────────────────────
    # "simulate" = détection + filtres + log, aucune transaction envoyée
    # "live"     = envoie de vraies transactions (nécessite wallet configuré)
    mode: str = "simulate"

    # ── Jupiter (exécution réelle des swaps) ─────────────────────
    # Depuis 2026, Jupiter recommande une clé API via https://portal.jup.ag
    # (l'ancien endpoint public reste utilisable mais avec des limites de
    # débit plus basses). À vérifier/ajuster au moment de l'usage réel.
    jupiter_api_base: str = "https://quote-api.jup.ag/v6"
    jupiter_api_key: str = ""       # optionnelle, via portal.jup.ag
    slippage_bps: int = 100         # 100 = 1% de slippage toléré
    priority_fee_lamports: int = 100_000  # frais de priorité (vitesse d'inclusion)
