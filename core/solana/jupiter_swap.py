"""
Exécution réelle d'achats/ventes de tokens Solana via Jupiter — le même
principe que Trojan, BonkBot, Maestro : quote → transaction de swap →
signature locale → envoi au réseau.

Flux (API Jupiter v6, "Metis") :
    1. GET  {base}/quote  -> meilleure route pour échanger inputMint -> outputMint
    2. POST {base}/swap   -> transaction sérialisée (base64) prête à signer
    3. Désérialiser en VersionedTransaction, signer avec le Keypair local
    4. Envoyer via `sendTransaction` au RPC configuré

⚠️ AVERTISSEMENTS IMPORTANTS :
- Ce module n'a pas pu être testé contre l'API Jupiter réelle ni contre
  un vrai RPC (pas d'accès réseau dans cet environnement de développement).
  Seules la construction des requêtes et le parsing des réponses ont pu
  être validés avec des réponses simulées (voir tests associés).
- Depuis 2026, Jupiter recommande une clé API (portal.jup.ag) pour un
  débit correct — vérifier `jupiter_api_key` dans .env avant usage intensif.
- Chaque swap coûte des frais réseau + un spread — ne jamais négliger ça
  dans le calcul de rentabilité, surtout sur de petits montants.
- Aucune protection MEV/anti-sandwich n'est implémentée ici (contrairement
  à Trojan/Banana Gun qui routent via Jito) — à ajouter avant un usage
  sérieux si le sniping devient compétitif sur des tokens très demandés.
"""

import base64
import logging
import time
from dataclasses import dataclass
from typing import Optional

import requests

from core.solana.config import SolanaConfig, WSOL_MINT

logger = logging.getLogger("solana.jupiter_swap")


@dataclass
class SwapResult:
    success: bool
    signature: Optional[str] = None
    error: Optional[str] = None
    in_amount: Optional[int] = None
    out_amount: Optional[int] = None


class JupiterSwapEngine:
    def __init__(self, config: SolanaConfig):
        self.config = config

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.config.jupiter_api_key:
            headers["x-api-key"] = self.config.jupiter_api_key
        return headers

    def get_quote(self, input_mint: str, output_mint: str, amount: int,
                  slippage_bps: Optional[int] = None) -> Optional[dict]:
        """
        amount est exprimé dans la plus petite unité du token d'entrée
        (ex: lamports pour SOL — 1 SOL = 1_000_000_000 lamports).
        Retourne None en cas d'erreur (jamais une quote partielle/fausse).
        """
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": slippage_bps or self.config.slippage_bps,
            "restrictIntermediateTokens": "true",
        }
        try:
            resp = requests.get(f"{self.config.jupiter_api_base}/quote",
                                 params=params, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error("Erreur get_quote: %s", e)
            return None

    def get_swap_transaction(self, quote: dict, user_pubkey: str) -> Optional[str]:
        """Retourne la transaction sérialisée en base64, prête à signer."""
        payload = {
            "quoteResponse": quote,
            "userPublicKey": user_pubkey,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True,
            "prioritizationFeeLamports": self.config.priority_fee_lamports,
        }
        try:
            resp = requests.post(f"{self.config.jupiter_api_base}/swap",
                                  json=payload, headers=self._headers(), timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return data.get("swapTransaction")
        except requests.RequestException as e:
            logger.error("Erreur get_swap_transaction: %s", e)
            return None

    def sign_and_send(self, swap_tx_base64: str, keypair) -> SwapResult:
        """
        Désérialise, signe et envoie la transaction. Import de `solders`
        différé (pas nécessaire en mode simulate/detection).

        ⚠️ Non testé en conditions réelles — le format exact attendu par
        `sendTransaction` (encoding base64 vs base58) doit être confirmé
        contre un vrai RPC avant usage.
        """
        try:
            from solders.transaction import VersionedTransaction
            from solders.keypair import Keypair
        except ImportError:
            return SwapResult(success=False,
                               error="Dépendance manquante: pip install solders")

        try:
            raw_tx = base64.b64decode(swap_tx_base64)
            tx = VersionedTransaction.from_bytes(raw_tx)
            signed_tx = VersionedTransaction(tx.message, [keypair])
            serialized = bytes(signed_tx)

            payload = {
                "jsonrpc": "2.0", "id": 1, "method": "sendTransaction",
                "params": [
                    base64.b64encode(serialized).decode("utf-8"),
                    {"encoding": "base64", "skipPreflight": False,
                     "maxRetries": 3},
                ],
            }
            resp = requests.post(self.config.rpc_http_url, json=payload, timeout=15)
            resp.raise_for_status()
            result = resp.json()

            if "error" in result:
                return SwapResult(success=False, error=str(result["error"]))
            return SwapResult(success=True, signature=result.get("result"))
        except Exception as e:
            logger.exception("Erreur sign_and_send")
            return SwapResult(success=False, error=str(e))

    # ── Raccourcis achat/vente ───────────────────────────────────
    def buy_with_sol(self, token_mint: str, sol_amount: float, keypair) -> SwapResult:
        """Achète `token_mint` en dépensant `sol_amount` SOL."""
        lamports = int(sol_amount * 1_000_000_000)
        quote = self.get_quote(WSOL_MINT, token_mint, lamports)
        if quote is None:
            return SwapResult(success=False, error="Impossible d'obtenir une quote")

        swap_tx = self.get_swap_transaction(quote, str(keypair.pubkey()))
        if swap_tx is None:
            return SwapResult(success=False, error="Impossible d'obtenir la transaction de swap")

        result = self.sign_and_send(swap_tx, keypair)
        result.in_amount = int(quote.get("inAmount", 0))
        result.out_amount = int(quote.get("outAmount", 0))
        return result

    def sell_to_sol(self, token_mint: str, token_amount_raw: int, keypair) -> SwapResult:
        """Vend `token_amount_raw` (unité brute, selon les décimales du
        token) de `token_mint` contre du SOL."""
        quote = self.get_quote(token_mint, WSOL_MINT, token_amount_raw)
        if quote is None:
            return SwapResult(success=False, error="Impossible d'obtenir une quote")

        swap_tx = self.get_swap_transaction(quote, str(keypair.pubkey()))
        if swap_tx is None:
            return SwapResult(success=False, error="Impossible d'obtenir la transaction de swap")

        result = self.sign_and_send(swap_tx, keypair)
        result.in_amount = int(quote.get("inAmount", 0))
        result.out_amount = int(quote.get("outAmount", 0))
        return result
