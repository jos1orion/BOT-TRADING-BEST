"""
Point d'entrée — Bot de sniping Solana (mode simulate / live).

Usage :
    python main_solana.py                  # mode simulate (aucune tx réelle)
    python main_solana.py --report         # affiche le résumé du journal

⚠️ Il n'y a volontairement AUCUN mode --live tant qu'un wallet et une
gestion sécurisée de clé privée ne sont pas explicitement configurés
(voir core/solana/config.py et .env.example). Ce fichier ne fait que de
la détection + filtrage + journalisation.
"""

import argparse
import asyncio
import logging
import os

from core.solana.config import SolanaConfig
from core.solana.token_scanner import SolanaTokenScanner
from core.solana.filters import TokenSafetyChecker
from core.solana.simulator import SnipeSimulator
from core.solana.wallet_tracker import WalletTracker
from core.solana.jupiter_swap import JupiterSwapEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("solana.main")


async def run_bot(config: SolanaConfig, live: bool):
    scanner = SolanaTokenScanner(config)
    checker = TokenSafetyChecker(config)
    simulator = SnipeSimulator()

    engine = None
    keypair = None
    if live:
        from core.solana.wallet import load_keypair
        engine = JupiterSwapEngine(config)
        keypair = load_keypair()  # lève une exception claire si mal configuré
        logger.warning("🔴 MODE LIVE — des transactions réelles seront envoyées.")
    else:
        logger.info("Démarrage en mode SIMULATE — aucune transaction ne sera envoyée.")

    logger.info("RPC websocket: %s", config.rpc_ws_url)

    async for event in scanner.stream_new_pools():
        logger.info("Nouvelle pool détectée (signature=%s)", event.signature)

        # TODO: extraire le vrai mint depuis event.raw_logs / la transaction
        # complète (getTransaction). Placeholder tant que le RPC n'est pas
        # branché avec un vrai fournisseur.
        mint_placeholder = "MINT_A_EXTRAIRE_DE_LA_TRANSACTION"

        report = checker.check(mint_placeholder)
        simulator.log_candidate(mint_placeholder, event.signature, report)

        if not report.passed:
            continue  # rejeté par les filtres, jamais d'achat

        if live:
            result = engine.buy_with_sol(mint_placeholder, config.max_snipe_usd / _sol_price_usd_placeholder(), keypair)
            if result.success:
                logger.info("✅ Achat exécuté: signature=%s", result.signature)
            else:
                logger.error("❌ Échec de l'achat: %s", result.error)
        else:
            logger.info("✅ [SIMULATE] Aurait acheté %s (achat réel désactivé)", mint_placeholder)


def _sol_price_usd_placeholder() -> float:
    # TODO: récupérer le vrai prix SOL/USD (ex: via Jupiter Price API)
    # pour convertir max_snipe_usd en montant de SOL à dépenser.
    # Valeur figée en attendant — NE PAS utiliser telle quelle en réel.
    logger.warning("Prix SOL/USD non récupéré dynamiquement — vérifier avant usage réel")
    return 150.0


def main():
    parser = argparse.ArgumentParser(description="Bot de sniping Solana")
    parser.add_argument("--report", action="store_true",
                         help="Affiche le résumé du journal de simulation")
    parser.add_argument("--live", action="store_true",
                         help="Active l'exécution réelle des achats (nécessite un wallet configuré)")
    args = parser.parse_args()

    config = SolanaConfig()

    if args.report:
        simulator = SnipeSimulator()
        print(simulator.summary())
        return

    live = args.live or os.getenv("SOLANA_MODE", "simulate") == "live"
    if live:
        confirm = input(
            "⚠️  MODE LIVE SOLANA — de l'argent réel sera engagé sur des tokens "
            "nouvellement créés (risque élevé de perte totale). "
            "Tape EXACTEMENT 'JE COMPRENDS LE RISQUE' pour continuer: "
        )
        if confirm.strip() != "JE COMPRENDS LE RISQUE":
            print("Annulé.")
            return

    asyncio.run(run_bot(config, live=live))


if __name__ == "__main__":
    main()
