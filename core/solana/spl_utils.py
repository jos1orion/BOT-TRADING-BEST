"""
Décodage du compte SPL Token "Mint" — vérification réelle (pas un stub)
du mint authority / freeze authority.

Fonctionne avec n'importe quel RPC Solana standard (même public, gratuit)
via un simple appel JSON-RPC `getAccountInfo` — pas besoin d'API tierce
payante pour CETTE vérification précise.

Layout du compte Mint (SPL Token Program, classique, 82 octets) :
    offset  0 : mintAuthorityOption   (u32 LE)  0=None, 1=Some
    offset  4 : mintAuthority         (32 octets, pubkey)
    offset 36 : supply                (u64 LE)
    offset 44 : decimals              (u8)
    offset 45 : isInitialized         (u8, bool)
    offset 46 : freezeAuthorityOption (u32 LE)  0=None, 1=Some
    offset 50 : freezeAuthority       (32 octets, pubkey)

Référence : spl-token program, struct `Mint` (stable depuis le lancement,
ne change pas). Les tokens Token-2022 (avec extensions) ont un layout
étendu au-delà de 82 octets — cette fonction se limite au cœur commun
aux deux, donc reste valide pour les deux programmes.
"""

import base64
import logging
import struct
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger("solana.spl_utils")

MINT_LAYOUT_SIZE = 82


@dataclass
class MintInfo:
    mint: str
    mint_authority_revoked: bool
    freeze_authority_revoked: bool
    decimals: int
    supply: int


def _rpc_call(rpc_http_url: str, method: str, params: list, timeout: int = 10) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        resp = requests.post(rpc_http_url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"error": str(e)}


def decode_mint_account_data(raw_bytes: bytes) -> MintInfo:
    """Décode les octets bruts d'un compte Mint SPL Token. Pure fonction,
    testable sans réseau (voir tests)."""
    if len(raw_bytes) < MINT_LAYOUT_SIZE:
        raise ValueError(f"Compte trop court pour être un Mint SPL Token "
                          f"({len(raw_bytes)} < {MINT_LAYOUT_SIZE} octets)")

    mint_authority_option = struct.unpack_from("<I", raw_bytes, 0)[0]
    supply = struct.unpack_from("<Q", raw_bytes, 36)[0]
    decimals = raw_bytes[44]
    freeze_authority_option = struct.unpack_from("<I", raw_bytes, 46)[0]

    return MintInfo(
        mint="",  # renseigné par l'appelant
        mint_authority_revoked=(mint_authority_option == 0),
        freeze_authority_revoked=(freeze_authority_option == 0),
        decimals=decimals,
        supply=supply,
    )


def get_mint_info(rpc_http_url: str, mint_address: str) -> Optional[MintInfo]:
    """Appel RPC réel : récupère et décode le compte Mint d'un token."""
    result = _rpc_call(rpc_http_url, "getAccountInfo", [
        mint_address, {"encoding": "base64"},
    ])

    if "error" in result:
        logger.error("Erreur RPC getAccountInfo(%s): %s", mint_address, result["error"])
        return None

    value = result.get("result", {}).get("value")
    if not value:
        logger.warning("Compte introuvable pour le mint %s", mint_address)
        return None

    try:
        raw_b64 = value["data"][0]
        raw_bytes = base64.b64decode(raw_b64)
        info = decode_mint_account_data(raw_bytes)
        info.mint = mint_address
        return info
    except Exception as e:
        logger.error("Erreur de décodage du compte mint %s: %s", mint_address, e)
        return None
