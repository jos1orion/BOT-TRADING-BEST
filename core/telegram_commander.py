"""
Pilotage du bot depuis Telegram (réception des commandes).

• Un thread d'arrière-plan interroge Telegram (long polling) et met les commandes
  dans une file. Il ne touche JAMAIS à MetaTrader 5 : c'est la boucle principale
  du bot qui exécute les commandes (la bibliothèque MT5 n'est pas faite pour
  être appelée depuis plusieurs threads).
• SÉCURITÉ : seules les commandes venant du chat privé dont l'identifiant est
  TELEGRAM_CHAT_ID sont acceptées. Tout le reste est ignoré, vérifié à chaque message.
• Au démarrage, les anciens messages en attente sont IGNORÉS (un vieux /toutfermer
  oublié ne doit jamais s'exécuter par surprise).
• Ne lancez pas en même temps un autre programme qui lit les messages du même bot
  Telegram (ex. telegram_control_bot.py) : Telegram n'autorise qu'un lecteur à la fois.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import List, NamedTuple, Optional
from urllib.parse import urlparse

from core.telegram_api import (
    get_updates, send_message, set_chat_menu_button, set_commands,
)

logger = logging.getLogger(__name__)

MENU = [
    ("statut", "État du bot et du compte"),
    ("positions", "Positions ouvertes"),
    ("trades", "Derniers trades clôturés"),
    ("bilan", "Résultat jour / semaine / total"),
    ("activite", "Dernières actions du bot"),
    ("symboles", "Symboles surveillés"),
    ("pause", "Mettre le bot en repos (plus de nouveaux trades)"),
    ("reprise", "Reprendre le trading"),
    ("fermer", "Fermer un trade : /fermer TICKET"),
    ("toutfermer", "Fermer tous les trades + repos"),
    ("exclure", "Ne plus trader un symbole"),
    ("inclure", "Retrader un symbole exclu"),
    ("stop", "Arrêter complètement le bot"),
    ("aide", "Liste des commandes"),
]

KEYBOARD = {
    "keyboard": [
        ["/statut", "/positions"],
        ["/bilan", "/trades"],
        ["/pause", "/reprise"],
        ["/toutfermer", "/aide"],
    ],
    "resize_keyboard": True,
}


class TelegramCommand(NamedTuple):
    text: str
    chat_id: str


class TelegramCommander:
    def __init__(self, bot_token: Optional[str], chat_id: Optional[str],
                 enabled: bool = False, webapp_url: str = "",
                 miniapp_user_ids: str = "", owner_ids: str = ""):
        self.bot_token = bot_token
        self.chat_id = str(chat_id).strip() if chat_id else ""
        self.enabled = bool(enabled and bot_token and self.chat_id)
        self.webapp_url = str(webapp_url or "").strip()
        self.owner_chat_ids = self._parse_chat_ids(owner_ids, self.chat_id)
        self.miniapp_chat_ids = list(dict.fromkeys(
            self.owner_chat_ids + self._parse_chat_ids(miniapp_user_ids)
        ))
        self._q: "queue.Queue[TelegramCommand]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offset: Optional[int] = None

    @classmethod
    def from_credentials(cls) -> "TelegramCommander":
        try:
            from broker_credentials import TELEGRAM_CONFIG
            owner_ids = str(TELEGRAM_CONFIG.get("owner_ids") or "")
            if any(not chat_id.isdigit() for chat_id in cls._parse_chat_ids(owner_ids)):
                raise ValueError("TELEGRAM_OWNER_IDS must contain numeric IDs")
            return cls(TELEGRAM_CONFIG.get("bot_token"), TELEGRAM_CONFIG.get("chat_id"),
                       TELEGRAM_CONFIG.get("enabled", True),
                       TELEGRAM_CONFIG.get("webapp_url", ""),
                       TELEGRAM_CONFIG.get("miniapp_user_ids", ""),
                       owner_ids)
        except (ImportError, ValueError) as exc:
            logger.error("Telegram commander configuration error: %s", exc)
            return cls(None, None, False)

    @staticmethod
    def _parse_chat_ids(value: str, primary: str = "") -> List[str]:
        return list(dict.fromkeys(
            ([str(primary).strip()] if str(primary or "").strip() else []) + [
                chat_id.strip() for chat_id in str(value or "").split(",")
                if chat_id.strip()
            ]
        ))

    # ── API Telegram ──────────────────────────────────────────────

    def reply(self, text: str, keyboard: bool = False,
              chat_id: Optional[str] = None) -> bool:
        """Send a response to the owner chat that issued the command."""
        if not self.enabled:
            return False
        target_chat_id = str(chat_id or self.chat_id)
        if target_chat_id not in self.owner_chat_ids:
            logger.warning("Telegram response target is not an authorized owner chat")
            return False
        markup = KEYBOARD if keyboard else None
        ok, err = send_message(
            token=self.bot_token,
            chat_id=target_chat_id,
            text=text,
            parse_mode=None,
            reply_markup=markup,
        )
        if not ok:
            logger.warning(f"Telegram reply erreur : {err}")
        return ok

    def reply_all(self, text: str, keyboard: bool = False) -> bool:
        """Send a shared announcement to each authorized owner chat."""
        all_sent = True
        for chat_id in self.owner_chat_ids:
            sent = self.reply(text, keyboard=keyboard, chat_id=chat_id)
            all_sent = sent and all_sent
        return all_sent

    def _register_menu(self):
        if not set_commands(self.bot_token, MENU):
            logger.warning("Telegram : impossible d'enregistrer le menu des commandes")

        if not self.webapp_url:
            return
        parsed = urlparse(self.webapp_url)
        if parsed.scheme != "https" or not parsed.netloc:
            logger.error("Mini App Telegram ignorée : TELEGRAM_WEBAPP_URL doit être une URL HTTPS valide")
            return
        for chat_id in self.miniapp_chat_ids:
            ok, err = set_chat_menu_button(self.bot_token, chat_id, self.webapp_url)
            if not ok:
                logger.warning(
                    "Telegram : configuration du bouton Mini App impossible pour le chat %s : %s",
                    chat_id, err,
                )

    # ── Réception ─────────────────────────────────────────────────
    def _is_authorized(self, update: dict) -> bool:
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        sender = msg.get("from") or {}
        chat_id = str(chat.get("id", "")).strip()
        sender_id = str(sender.get("id", "")).strip()
        return (
            chat.get("type") == "private"
            and chat_id in self.owner_chat_ids
            and sender_id in self.owner_chat_ids
            and chat_id == sender_id
        )

    def _fetch(self, timeout: int):
        return get_updates(self.bot_token, offset=self._offset, timeout=timeout)

    def _loop(self):
        # 1) on saute tout ce qui est arrivé avant le démarrage
        try:
            backlog = self._fetch(0)
            if backlog:
                self._offset = backlog[-1]["update_id"] + 1
            else:
                self._offset = 0
        except Exception as e:
            logger.warning(f"Telegram : lecture initiale impossible ({e})")
        # 2) boucle normale
        while not self._stop.is_set():
            try:
                for upd in self._fetch(25):
                    self._offset = upd["update_id"] + 1
                    if not self._is_authorized(upd):
                        logger.warning("Telegram : message d'un chat NON autorisé ignoré")
                        continue
                    text = ((upd.get("message") or {}).get("text") or "").strip()
                    if text:
                        chat_id = str(
                            (upd.get("message") or {}).get("chat", {}).get("id", "")
                        ).strip()
                        self._q.put(TelegramCommand(text, chat_id))
            except Exception as e:
                logger.warning(f"Telegram polling : {e}")
                self._stop.wait(5)

    def start(self) -> bool:
        if not self.enabled or self._thread:
            return self.enabled
        self._register_menu()
        self._thread = threading.Thread(target=self._loop, name="telegram-commander", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()

    def drain(self) -> List[TelegramCommand]:
        out = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out
