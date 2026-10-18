"""Local HTTP origin for a TLS reverse proxy serving the Telegram Mini App."""
from __future__ import annotations

import argparse
import logging
import os
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from core.telegram_api import set_chat_menu_button
from core.telegram_miniapp import make_miniapp_handler

logger = logging.getLogger(__name__)


def main():
    from broker_credentials import ACTIVE_BROKER, TELEGRAM_CONFIG

    parser = argparse.ArgumentParser(
        description="Serve the read-only Telegram Mini App behind an HTTPS proxy."
    )
    parser.add_argument(
        "--broker",
        default=os.environ.get("TRADING_BOT_ACTIVE_BROKER", ACTIVE_BROKER),
        choices=("deriv", "xm", "axiom"),
        help="Broker used by the running live bot (default: ACTIVE_BROKER).",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("TELEGRAM_MINIAPP_HOST", "127.0.0.1"),
        help="Bind address; keep localhost when using an HTTPS reverse proxy.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("TELEGRAM_MINIAPP_PORT", "8766")),
    )
    args = parser.parse_args()

    token = str(TELEGRAM_CONFIG.get("bot_token") or "")
    chat_id = str(TELEGRAM_CONFIG.get("chat_id") or "").strip()
    if not token or token == "VOTRE_BOT_TOKEN" or not chat_id.isdigit():
        parser.error("Configurez TELEGRAM_BOT_TOKEN et un TELEGRAM_CHAT_ID numérique.")
    allowed_ids = {chat_id}
    configured_owner_ids = str(TELEGRAM_CONFIG.get("owner_ids") or "")
    allowed_ids.update(
        user_id.strip() for user_id in configured_owner_ids.split(",")
        if user_id.strip()
    )
    configured_ids = str(TELEGRAM_CONFIG.get("miniapp_user_ids") or "")
    allowed_ids.update(
        user_id.strip() for user_id in configured_ids.split(",")
        if user_id.strip()
    )
    if any(not user_id.isdigit() for user_id in allowed_ids):
        parser.error("TELEGRAM_MINIAPP_USER_IDS doit contenir des ID numériques séparés par des virgules.")

    state_file = os.path.abspath(
        f"dashboard_live_{args.broker.lower()}.json"
    )
    journal_file = os.path.abspath(
        f"trading_journal_live_{args.broker.lower()}.csv"
    )
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "telegram_miniapp")
    pin_file = os.path.abspath(".telegram_miniapp_pin.json")
    webapp_url = str(TELEGRAM_CONFIG.get("webapp_url") or "").strip()
    if webapp_url:
        parsed_url = urlsplit(webapp_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            parser.error("TELEGRAM_WEBAPP_URL doit être une URL HTTPS valide.")
        for user_id in sorted(allowed_ids):
            ok, error = set_chat_menu_button(token, user_id, webapp_url)
            if not ok:
                logger.warning(
                    "Impossible de configurer le bouton Mini App pour un utilisateur autorisé : %s",
                    error,
                )
    handler = make_miniapp_handler(
        static_dir, state_file, token, ",".join(sorted(allowed_ids)),
        journal_file, pin_file,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True
    print(f"Mini App locale : http://{args.host}:{args.port}/")
    print(f"État du bot : {state_file}")
    print("Pour Telegram, placez un reverse proxy HTTPS devant cette adresse.")
    print("Ne publiez pas directement ce port sur Internet. Ctrl+C pour arrêter.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
