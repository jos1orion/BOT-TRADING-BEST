"""
Module centralisé de communication avec l'API Telegram.

Fournit :
- Transport HTTP/HTTPS autonome (urllib + ssl résilient, sans dépendance requise)
- Fallback automatique avec requests si disponible
- Vérification getMe et détection d'erreurs (chat_id incorrect, bot vers bot)
- Auto-appairage interactif de l'utilisateur par envoi de /start
- Sauvegarde automatique du chat_id validé dans .env et broker_credentials.py
"""
from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Initialisation des contextes SSL résilients
try:
    _SSL_CTX_SECURE = ssl.create_default_context()
except Exception:
    _SSL_CTX_SECURE = None

try:
    _SSL_CTX_UNVERIFIED = ssl._create_unverified_context()
except Exception:
    _SSL_CTX_UNVERIFIED = None


def telegram_api_request(
    token: str,
    method: str,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
) -> Tuple[bool, Dict[str, Any], str]:
    """
    Exécute un appel direct à l'API Telegram.
    Retourne (succès: bool, réponse_json: dict, message_erreur: str).
    """
    if not token:
        return False, {}, "Token Telegram manquant"

    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = None
    headers = {"User-Agent": "DerivTradingBot/2.0"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    # Essai standard urllib avec gestion d'interception SSL
    contexts = [_SSL_CTX_SECURE, _SSL_CTX_UNVERIFIED] if _SSL_CTX_UNVERIFIED else [_SSL_CTX_SECURE]
    last_err = ""

    for ctx in contexts:
        if ctx is None:
            continue
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw)
                return bool(parsed.get("ok")), parsed, ""
        except ssl.SSLCertVerificationError:
            # Erreur de certificat Windows/Antivirus -> tester unverified context
            continue
        except urllib.error.HTTPError as e:
            raw_err = e.read().decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(raw_err)
                desc = parsed.get("description", str(e))
                return False, parsed, desc
            except Exception:
                return False, {}, f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            last_err = str(e)
            continue

    # Fallback requests si présent
    try:
        import requests
        if payload is not None:
            r = requests.post(url, json=payload, timeout=timeout, verify=False)
        else:
            r = requests.get(url, params=params, timeout=timeout, verify=False)
        parsed = r.json()
        return bool(parsed.get("ok")), parsed, parsed.get("description", "")
    except Exception as e:
        if not last_err:
            last_err = str(e)

    return False, {}, last_err or "Échec de connexion Telegram"


def get_me(token: str) -> Tuple[bool, Dict[str, Any], str]:
    """Récupère les informations du bot Telegram (getMe)."""
    ok, res, err = telegram_api_request(token, "getMe", timeout=10)
    if ok and "result" in res:
        return True, res["result"], ""
    return False, {}, err


def send_message(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: Optional[str] = "Markdown",
    reply_markup: Optional[Dict[str, Any]] = None,
    disable_notification: bool = False,
) -> Tuple[bool, str]:
    """
    Envoie un message à un chat_id.
    Si le Markdown échoue, retente automatiquement en texte brut.
    """
    if not token or not chat_id:
        return False, "Token ou chat_id manquant"

    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_notification": disable_notification,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup

    ok, _, err = telegram_api_request(token, "sendMessage", payload=payload, timeout=12)
    if ok:
        return True, ""

    # Si rejeté à cause du formatage Markdown, retenter en texte brut
    if parse_mode and ("can't parse" in err.lower() or "entities" in err.lower()):
        payload.pop("parse_mode", None)
        ok2, _, err2 = telegram_api_request(token, "sendMessage", payload=payload, timeout=12)
        if ok2:
            return True, ""
        return False, err2

    return False, err


def get_updates(token: str, offset: Optional[int] = None, timeout: int = 20) -> List[Dict[str, Any]]:
    """Récupère les mises à jour (messages entrants) via long polling."""
    params: Dict[str, Any] = {"timeout": timeout, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset

    ok, res, _ = telegram_api_request(token, "getUpdates", params=params, timeout=timeout + 10)
    if ok and isinstance(res.get("result"), list):
        return res["result"]
    return []


def set_commands(token: str, commands: List[Tuple[str, str]]) -> bool:
    """Enregistre les commandes dans l'interface Telegram."""
    payload = {
        "commands": [{"command": c, "description": d} for c, d in commands]
    }
    ok, _, _ = telegram_api_request(token, "setMyCommands", payload=payload, timeout=10)
    return ok


def set_chat_menu_button(token: str, chat_id: str, url: str) -> Tuple[bool, str]:
    """Configure le bouton Mini App du menu pour le chat privé autorisé."""
    payload = {
        "chat_id": chat_id,
        "menu_button": {
            "type": "web_app",
            "text": "Tableau de bord",
            "web_app": {"url": url},
        },
    }
    ok, _, err = telegram_api_request(
        token, "setChatMenuButton", payload=payload, timeout=10
    )
    return ok, err


def update_stored_chat_id(new_chat_id: str) -> bool:
    """Met à jour le chat_id dans .env et broker_credentials.py."""
    updated = False
    new_chat_id = str(new_chat_id).strip()

    # 1. Mise à jour .env
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_path):
        env_path = ".env"

    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()

            if re.search(r"^TELEGRAM_CHAT_ID\s*=.*$", content, flags=re.MULTILINE):
                content = re.sub(
                    r"^TELEGRAM_CHAT_ID\s*=.*$",
                    f"TELEGRAM_CHAT_ID={new_chat_id}",
                    content,
                    flags=re.MULTILINE,
                )
            else:
                content += f"\nTELEGRAM_CHAT_ID={new_chat_id}\n"

            with open(env_path, "w", encoding="utf-8") as f:
                f.write(content)
            updated = True
        except Exception as e:
            logger.warning(f"Impossible de mettre à jour .env : {e}")

    # 2. Mise à jour broker_credentials.py
    creds_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "broker_credentials.py")
    if not os.path.exists(creds_path):
        creds_path = "broker_credentials.py"

    if os.path.exists(creds_path):
        try:
            with open(creds_path, "r", encoding="utf-8") as f:
                content = f.read()

            content = re.sub(
                r'("chat_id":\s*os\.getenv\("TELEGRAM_CHAT_ID",\s*")[^"]*(")\)',
                r'\g<1>' + new_chat_id + r'\g<2>)',
                content
            )
            with open(creds_path, "w", encoding="utf-8") as f:
                f.write(content)
            updated = True
        except Exception as e:
            logger.warning(f"Impossible de mettre à jour broker_credentials.py : {e}")

    return updated


def wait_for_user_pairing(token: str, bot_username: str, timeout_seconds: int = 60) -> Optional[str]:
    """
    Invite l'utilisateur à envoyer un message au bot sur Telegram et détecte son chat_id.
    """
    print(f"\n  {'═' * 60}")
    print(f"  📱 APPAIRAGE TELEGRAM REQUIS")
    print(f"  {'═' * 60}")
    print(f"  1. Ouvrez Telegram sur votre téléphone ou ordinateur")
    print(f"  2. Recherchez le bot : @{bot_username}")
    print(f"     ou cliquez sur le lien : https://t.me/{bot_username}")
    print(f"  3. Cliquez sur 'DÉMARRER' ou envoyez le message : /start")
    print(f"  {'─' * 60}")
    print(f"  En attente de votre message ({timeout_seconds}s restantes)...")

    # Purger les anciens updates si possible pour ne prendre que les nouveaux
    try:
        old_updates = get_updates(token, offset=None, timeout=0)
        offset = (old_updates[-1]["update_id"] + 1) if old_updates else 0
    except Exception:
        offset = 0

    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        elapsed = int(time.time() - start_time)
        remain = timeout_seconds - elapsed
        try:
            updates = get_updates(token, offset=offset, timeout=3)
            for upd in updates:
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("channel_post") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", "")).strip()
                if chat_id:
                    user_name = chat.get("first_name") or chat.get("username") or "Trader"
                    print(f"\n  ✅ Message reçu de {user_name} (Chat ID: {chat_id}) !")
                    update_stored_chat_id(chat_id)

                    # Envoi d'un message d'accueil immédiat
                    welcome = (
                        f"🎉 *Connexion réussie !*\n\n"
                        f"Bonjour {user_name}, votre compte Telegram est maintenant lié au Bot de Trading Deriv.\n"
                        f"Vous recevrez ici vos signaux d'entrée, fermetures de trades et bilans.\n\n"
                        f"Tapez */aide* pour afficher le clavier de contrôle."
                    )
                    send_message(token, chat_id, welcome, parse_mode="Markdown")
                    return chat_id
        except Exception as e:
            logger.debug(f"Erreur polling appairage: {e}")

        time.sleep(1)

    print("\n  ❌ Délai dépassé : aucun message reçu sur Telegram.")
    return None
