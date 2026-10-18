"""
Détection de nouveaux tokens/pools Solana en temps réel.

Principe :
- On ouvre une connexion websocket JSON-RPC vers le nœud Solana
  (rpc_ws_url) et on s'abonne aux logs mentionnant les programmes DEX
  surveillés (Raydium AMM V4, Pump.fun...) via `logsSubscribe`.
- Quand un log contient l'instruction de création de pool
  ("initialize2" pour Raydium AMM V4), on récupère la transaction
  complète pour en extraire les mints des deux côtés de la pool.
- On ne fait AUCUNE hypothèse sur la fiabilité du token à ce stade —
  c'est le rôle de `filters.py`.

⚠️ Ce module n'a pas pu être testé en conditions réelles (pas d'accès
réseau dans cet environnement de développement). Avant usage :
1. Tester avec `python -m core.solana.token_scanner` sur un RPC gratuit
   pour valider que les logs arrivent bien.
2. Passer sur un RPC payé (Helius/QuickNode/Triton) pour la vitesse réelle
   nécessaire au sniping — le RPC public est trop lent/rate-limité.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from core.solana.config import SolanaConfig

logger = logging.getLogger("solana.scanner")


@dataclass
class NewPoolEvent:
    signature: str
    program_id: str
    raw_logs: list


class SolanaTokenScanner:
    def __init__(self, config: SolanaConfig):
        self.config = config

    async def stream_new_pools(self) -> AsyncGenerator[NewPoolEvent, None]:
        """
        Se connecte au RPC websocket et yield un NewPoolEvent à chaque
        transaction qui ressemble à une création de pool/token.
        Reconnexion automatique en cas de coupure.
        """
        backoff = 1
        import websockets  # import différé : pas nécessaire pour parser/tester
        while True:
            try:
                async with websockets.connect(self.config.rpc_ws_url,
                                               ping_interval=20) as ws:
                    await self._subscribe_all(ws)
                    backoff = 1  # reset après connexion réussie
                    async for raw in ws:
                        event = self._parse_message(raw)
                        if event:
                            yield event
            except (websockets.exceptions.ConnectionClosed,
                    OSError, asyncio.TimeoutError) as e:
                logger.warning("Connexion websocket perdue (%s), retry dans %ss", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _subscribe_all(self, ws):
        for i, program_id in enumerate(self.config.watched_programs):
            req = {
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "logsSubscribe",
                "params": [
                    {"mentions": [program_id]},
                    {"commitment": "confirmed"},
                ],
            }
            await ws.send(json.dumps(req))
            logger.info("Abonné aux logs du programme %s", program_id)

    def _parse_message(self, raw: str) -> Optional[NewPoolEvent]:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return None

        params = msg.get("params")
        if not params:
            return None  # réponse de confirmation d'abonnement, pas un log

        result = params.get("result", {})
        value = result.get("value", {})
        logs = value.get("logs", [])
        signature = value.get("signature")

        # Heuristique de détection de création de pool (Raydium: "initialize2",
        # Pump.fun: "Instruction: Create" / "Instruction: InitializeMint2")
        creation_markers = ("initialize2", "InitializeMint2",
                             "Instruction: Create")
        if any(marker in line for line in logs for marker in creation_markers):
            return NewPoolEvent(
                signature=signature,
                program_id=self.config.watched_programs[0],
                raw_logs=logs,
            )
        return None


async def _demo():
    """Lance le scanner en mode démo (affiche les events, ne trade rien)."""
    logging.basicConfig(level=logging.INFO)
    config = SolanaConfig()
    scanner = SolanaTokenScanner(config)
    print(f"Connexion à {config.rpc_ws_url} ... (Ctrl+C pour arrêter)")
    async for event in scanner.stream_new_pools():
        print(f"[NOUVELLE POOL DÉTECTÉE] signature={event.signature}")


if __name__ == "__main__":
    asyncio.run(_demo())
