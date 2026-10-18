"""
Notifications Telegram en temps réel.

Envoie une alerte instantanée sur le téléphone quand :
- Un nouveau signal actionnable est détecté
- Un trade est ouvert / fermé (SL, TP1, TP2)
- Le bot est mis en pause (drawdown, news bloquante)
- Une erreur critique survient

Configuration (dans broker_credentials.py) :
    TELEGRAM_CONFIG = {
        "enabled": True,
        "bot_token": "123456:ABC-DEF...",
        "chat_id": "123456789",
    }

Comment créer un bot Telegram :
1. Parler à @BotFather sur Telegram -> /newbot -> suivre les instructions -> récupérer le token
2. Envoyer un message à votre bot puis ouvrir :
   https://api.telegram.org/bot<TOKEN>/getUpdates pour récupérer votre chat_id
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from core.telegram_api import get_me, send_message

logger = logging.getLogger(__name__)


class TelegramNotifier:

    def __init__(self, bot_token: Optional[str] = None,
                 chat_id: Optional[str] = None,
                 enabled: bool = False,
                 owner_ids: str = ""):
        self.bot_token = bot_token
        self.chat_id = str(chat_id).strip() if chat_id else ""
        self.enabled = bool(enabled and bot_token and self.chat_id)
        self.chat_ids = list(dict.fromkeys(
            ([self.chat_id] if self.chat_id else []) + [
                owner_id.strip() for owner_id in str(owner_ids or "").split(",")
                if owner_id.strip()
            ]
        ))

    @classmethod
    def from_credentials(cls) -> "TelegramNotifier":
        """Construit le notifier depuis broker_credentials.py (best effort)."""
        try:
            from broker_credentials import TELEGRAM_CONFIG
            return cls(
                bot_token=TELEGRAM_CONFIG.get("bot_token"),
                chat_id=TELEGRAM_CONFIG.get("chat_id"),
                enabled=TELEGRAM_CONFIG.get("enabled", True),
                owner_ids=TELEGRAM_CONFIG.get("owner_ids", ""),
            )
        except Exception:
            return cls(enabled=False)

    def verify_connection(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Vérifie la validité du token, identifie le bot et valide le chat_id.
        Retourne (est_valide, message_diagnostic, infos_bot).
        """
        if not self.bot_token:
            return False, "Token Telegram manquant (TELEGRAM_BOT_TOKEN non renseigné)", {}

        ok, bot_info, err = get_me(self.bot_token)
        if not ok:
            return False, f"Impossible de joindre le bot Telegram : {err}", {}

        bot_id = str(bot_info.get("id", ""))
        bot_username = bot_info.get("username", "Inconnu")

        if not self.chat_id:
            return False, f"Chat ID non configuré pour @{bot_username}", bot_info

        if self.chat_id == bot_id:
            return False, (
                f"Le chat_id renseigné ({self.chat_id}) est l'identifiant du bot @{bot_username} lui-même. "
                f"Un bot Telegram ne peut pas s'envoyer des messages à lui-même."
            ), bot_info

        # Tester l'envoi d'un message d'initialisation
        test_ok, test_err = send_message(
            self.bot_token,
            self.chat_id,
            "🔗 *Vérification du canal Telegram réussie !*",
            parse_mode="Markdown",
            disable_notification=True,
        )
        if not test_ok:
            return False, f"Échec d'envoi vers chat_id {self.chat_id} : {test_err}", bot_info

        return True, f"Connecté à @{bot_username} (chat_id: {self.chat_id})", bot_info

    def send(self, message: str, parse_mode: Optional[str] = "Markdown", silent: bool = False) -> bool:
        """Envoie les alertes à tous les propriétaires configurés."""
        if not self.enabled or not self.bot_token or not self.chat_id:
            return False
        all_sent = True
        for chat_id in self.chat_ids:
            ok, err = send_message(
                token=self.bot_token,
                chat_id=chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_notification=silent,
            )
            if not ok:
                all_sent = False
                logger.warning("Telegram notification delivery failed: %s", err)
        return all_sent

    # ── Messages formatés pré-construits ──────────────────────────

    def notify_signal(self, ticker: str, strategy: str, direction: str,
                       entry: float, sl: float, tp1: float, strength: float):
        msg = (
            f"🟢 *SIGNAL {direction}*\n"
            f"`{ticker}` — {strategy}\n"
            f"Force: {strength:.0f}/100\n"
            f"Entrée: `{entry:.5f}` | SL: `{sl:.5f}` | TP1: `{tp1:.5f}`"
        )
        self.send(msg)

    def notify_trade_opened(self, ticker: str, strategy: str, direction: str,
                             size, entry: float, sl: float, tp1: float):
        msg = (
            f"🟢 *TRADE OUVERT* — {direction}\n"
            f"`{ticker}` ({strategy})\n"
            f"Taille: {size} | Entrée: `{entry:.5f}`\n"
            f"SL: `{sl:.5f}` | TP1: `{tp1:.5f}`"
        )
        self.send(msg)

    def notify_trade_closed(self, ticker: str, pnl: float, pnl_pct: float, reason: str):
        icon = "✅" if pnl >= 0 else "❌"
        msg = (
            f"{icon} *TRADE FERMÉ* — `{ticker}`\n"
            f"PnL: `{pnl:+,.2f}` ({pnl_pct:+.1f}%)\n"
            f"Raison: {reason}"
        )
        self.send(msg)

    def notify_pause(self, reason: str):
        self.send(f"⛔ *BOT EN PAUSE*\n{reason}")

    def notify_resume(self, reason: str = ""):
        self.send(f"▶️ *BOT REPREND LE TRADING*\n{reason}")

    def notify_error(self, context: str, error: str):
        self.send(f"⚠️ *ERREUR* — {context}\n`{error[:300]}`")

    def notify_news_block(self, symbol: str, event_title: str, event_time: str):
        self.send(
            f"📅 *TRADING BLOQUÉ — NEWS*\n"
            f"`{symbol}` — {event_title}\n"
            f"Heure: {event_time}"
        )
