"""
Chargement du wallet Solana pour la signature de transactions.

⚠️ RÈGLES DE SÉCURITÉ NON NÉGOCIABLES :
- La clé privée ne vient QUE d'une variable d'environnement
  (SOLANA_WALLET_PRIVATE_KEY), jamais d'un argument en ligne de commande
  (visible dans l'historique shell / ps aux) ni codée en dur.
- Ne JAMAIS logger, print(), ou envoyer la clé privée où que ce soit.
- Utiliser un wallet dédié au bot, séparé de tout wallet personnel.
"""

import logging
import os

logger = logging.getLogger("solana.wallet")


def load_keypair():
    """
    Charge un Keypair Solana depuis SOLANA_WALLET_PRIVATE_KEY (format
    base58, comme exporté par Phantom/Solflare).

    Import de `solders` différé : cette fonction n'est appelée qu'au
    moment de basculer en mode live, pas nécessaire pour la détection/
    simulation.

    ⚠️ Non testé dans cet environnement (pas de réseau, pas de `solders`
    installé) — à valider avec une clé de test avant tout usage réel.
    """
    private_key_b58 = os.getenv("SOLANA_WALLET_PRIVATE_KEY", "").strip()
    if not private_key_b58:
        raise RuntimeError(
            "SOLANA_WALLET_PRIVATE_KEY absente de l'environnement. "
            "Définis-la dans ton .env local — jamais en dur dans le code."
        )

    try:
        from solders.keypair import Keypair
        import base58
    except ImportError as e:
        raise RuntimeError(
            "Dépendances manquantes: pip install solders base58"
        ) from e

    try:
        raw = base58.b58decode(private_key_b58)
        keypair = Keypair.from_bytes(raw)
    except Exception as e:
        raise RuntimeError(f"Impossible de décoder la clé privée: {e}") from e

    logger.info("Wallet chargé: %s (clé jamais affichée)", keypair.pubkey())
    return keypair
