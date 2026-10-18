"""
╔══════════════════════════════════════════════════════════════════╗
║  IDENTIFIANTS BROKER — À REMPLIR                               ║
║                                                                  ║
║  ⚠️  NE JAMAIS partager ce fichier                             ║
║  ⚠️  NE PAS committer sur GitHub/cloud                         ║
║  ⚠️  Commencez TOUJOURS avec DEMO = True                       ║
╚══════════════════════════════════════════════════════════════════╝

🔒 SÉCURITÉ DES SECRETS
Tous les identifiants sensibles (mots de passe, tokens) sont lus en
priorité depuis des VARIABLES D'ENVIRONNEMENT, avec les valeurs
ci-dessous comme simple fallback pour un usage local rapide.

Recommandé : créez un fichier `.env` (jamais commité — voir .gitignore)
à partir de `.env.example`, et laissez python-dotenv le charger
automatiquement. Sur un serveur / VPS, définissez plutôt de vraies
variables d'environnement systeme.

Ne JAMAIS committer ce fichier avec de vrais secrets écrits en dur.
"""

import os

# Charge automatiquement un fichier .env s'il existe (optionnel).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv non installé : les variables d'env système suffisent


def _env(key: str, default):
    """Lit une variable d'environnement, avec fallback sur `default`."""
    val = os.environ.get(key)
    return val if val not in (None, "") else default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _env_float(key: str, default: float) -> float:
    val = os.environ.get(key)
    try:
        return float(val) if val not in (None, "") else default
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key)
    try:
        return int(val) if val not in (None, "") else default
    except ValueError:
        return default


# ══════════════════════════════════════════════════════════════════
# CHOISIR LE BROKER ACTIF
# ══════════════════════════════════════════════════════════════════
ACTIVE_BROKER = _env("TRADING_BOT_ACTIVE_BROKER", "DERIV")     # "DERIV" | "XM" | "AXIOM"
DEMO_MODE     = _env_bool("TRADING_BOT_DEMO_MODE", True)       # ← TOUJOURS True au début !

# ══════════════════════════════════════════════════════════════════
# XM GLOBAL — via variables d'environnement (recommandé) ou fallback ci-dessous
# ══════════════════════════════════════════════════════════════════
XM_CONFIG = {
    "demo": {
        "login":    _env_int("XM_DEMO_LOGIN", 0),                          # XM_DEMO_LOGIN
        "password": _env("XM_DEMO_PASSWORD", "VOTRE_MOT_DE_PASSE"),        # XM_DEMO_PASSWORD
        "server":   _env("XM_DEMO_SERVER", "XMGlobal-Demo 3"),             # XM_DEMO_SERVER
    },
    "real": {
        "login":    _env_int("XM_REAL_LOGIN", 0),                          # XM_REAL_LOGIN
        "password": _env("XM_REAL_PASSWORD", "VOTRE_MOT_DE_PASSE_REEL"),   # XM_REAL_PASSWORD
        "server":   _env("XM_REAL_SERVER", "XMGlobal-Real 11"),            # XM_REAL_SERVER
    }
}

# ══════════════════════════════════════════════════════════════════
# AXIOM — via variables d'environnement (recommandé) ou fallback ci-dessous
# ══════════════════════════════════════════════════════════════════
AXIOM_CONFIG = {
    "demo": {
        "login":    _env_int("AXIOM_DEMO_LOGIN", 0),
        "password": _env("AXIOM_DEMO_PASSWORD", "VOTRE_MOT_DE_PASSE_DEMO"),
        "server":   _env("AXIOM_DEMO_SERVER", "Axiom-Demo"),
    },
    "real": {
        "login":    _env_int("AXIOM_REAL_LOGIN", 0),
        "password": _env("AXIOM_REAL_PASSWORD", "VOTRE_MOT_DE_PASSE_REEL"),
        "server":   _env("AXIOM_REAL_SERVER", "Axiom-Real"),
    }
}

# ══════════════════════════════════════════════════════════════════
# DERIV — MT5 (variables d'environnement recommandées)
# Mot de passe = celui du compte MT5 Deriv (≠ mot de passe du compte Deriv.com)
# Serveur = visible dans votre espace Deriv (Trader's Hub → MT5 → Info)
# ══════════════════════════════════════════════════════════════════
DERIV_CONFIG = {
    "demo": {
        "login":    _env_int("DERIV_DEMO_LOGIN", 0),
        "password": _env("DERIV_DEMO_PASSWORD", "VOTRE_MOT_DE_PASSE_DEMO"),
        "server":   _env("DERIV_DEMO_SERVER", "Deriv-Demo"),
    },
    "real": {
        "login":    _env_int("DERIV_REAL_LOGIN", 0),
        "password": _env("DERIV_REAL_PASSWORD", "VOTRE_MOT_DE_PASSE_REEL"),
        "server":   _env("DERIV_REAL_SERVER", "Deriv-Server"),
    }
}

# ══════════════════════════════════════════════════════════════════
# CHEMIN MT5 (optionnel — seulement si MT5 n'est pas au chemin défaut)
# ══════════════════════════════════════════════════════════════════
MT5_PATH = _env("MT5_PATH", None)
# Exemple si MT5 n'est pas trouvé automatiquement (ou via variable d'env MT5_PATH) :
# MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# ══════════════════════════════════════════════════════════════════
# TELEGRAM — Notifications en temps réel
# ══════════════════════════════════════════════════════════════════
# 1. Parlez à @BotFather sur Telegram -> /newbot -> récupérez le token
# 2. Envoyez un message à votre bot, puis ouvrez dans un navigateur :
#    https://api.telegram.org/bot<VOTRE_TOKEN>/getUpdates
#    -> récupérez "chat":{"id": ...} = votre chat_id
# 3. Définissez TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID (variables d'env ou .env)
TELEGRAM_CONFIG = {
    "enabled":   _env_bool("TELEGRAM_ENABLED", True),                 # ← Actif par défaut (obligatoire pour le pilotage)
    "bot_token": _env("TELEGRAM_BOT_TOKEN", "VOTRE_BOT_TOKEN"),
    "chat_id":   _env("TELEGRAM_CHAT_ID", "VOTRE_CHAT_ID"),
    "webapp_url": _env("TELEGRAM_WEBAPP_URL", ""),
    "owner_ids": _env("TELEGRAM_OWNER_IDS", ""),
    "miniapp_user_ids": _env("TELEGRAM_MINIAPP_USER_IDS", ""),
}

# ══════════════════════════════════════════════════════════════════
# PROTECTION DRAWDOWN — Kill-switch automatique
# ══════════════════════════════════════════════════════════════════
DRAWDOWN_CONFIG = {
    "daily_limit_pct":        _env_float("DRAWDOWN_DAILY_LIMIT_PCT", 3.0),   # Pause si -3% sur la journée
    "weekly_limit_pct":       _env_float("DRAWDOWN_WEEKLY_LIMIT_PCT", 6.0),  # Pause si -6% sur la semaine
    "max_consecutive_losses": _env_int("DRAWDOWN_MAX_CONSECUTIVE_LOSSES", 5),  # Pause après 5 pertes d'affilée
}

# ══════════════════════════════════════════════════════════════════
# PARAMÈTRES DE TRADING EN DIRECT
# ══════════════════════════════════════════════════════════════════
LIVE_TRADING_CONFIG = {
    # Symboles à trader
    "symboles": [
        # Forex
        "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "GBPJPY", "EURJPY",
        # Métaux
        "XAUUSD", "XAGUSD",
        # Énergie
        "USOIL", "UKOIL",
        # Indices
        "DE40", "UK100", "US500", "US100",
        # Crypto (24/7)
        "BTCUSD", "ETHUSD",
        # Volatility Index
        "V10", "V25", "V50", "V75", "V100", "V75_1S", "V100_1S",
        # Boom / Crash / Step / Jump
        "BOOM1000", "CRASH1000", "BOOM500", "CRASH500", "STEP", "JUMP25", "JUMP75",
    ],   # un symbole absent de votre compte est simplement ignoré au démarrage

    # Timeframe principal
    "timeframe": "H1",          # M5, M15, H1, H4, D1

    # Risque par trade
    "risk_per_trade_pct": 0.5,  # 0.5% en live (conservateur)
                                 # Augmenter seulement après validation

    # Nombre max de positions simultanées en live
    "max_positions": 3,
    # Risque monétaire total des positions ouvertes, au niveau de leur stop-loss
    "max_total_open_risk_pct": _env_float("MAX_TOTAL_OPEN_RISK_PCT", 3.0),

    # Intervalle de scan (secondes)
    "scan_interval_seconds": 300,  # 5 minutes

    # Heure d'arrêt (évite les trades en dehors des heures liquides)
    "trading_hours": None,      # None = 24h/24, 7j/7 (indices synthétiques Deriv)

    # Éviter les trades avant/après les news majeures
    "avoid_news": True,
    "news_buffer_minutes": 30,  # 30 min avant et après chaque news
}
