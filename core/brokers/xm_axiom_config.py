"""
Configuration spécifique XM Global + Axiom
"""

from dataclasses import dataclass, field
from typing import Dict, List

# ══════════════════════════════════════════════════════════════════
# XM GLOBAL — CONFIGURATION
# ══════════════════════════════════════════════════════════════════

XM_SERVERS = {
    "demo": [
        "XMGlobal-Demo 3",
        "XMGlobal-Demo 2",
        "XMGlobal-Demo",
    ],
    "real": [
        "XMGlobal-Real 11",
        "XMGlobal-Real 12",
        "XMGlobal-Real 14",
        # Votre serveur réel est visible dans MT5 :
        # Outils → Options → Serveur
    ]
}

XM_SYMBOLES = {
    # Forex majeurs
    "forex": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF",
              "AUDUSD", "USDCAD", "NZDUSD"],
    # Forex croisés
    "forex_crosses": ["GBPJPY", "EURJPY", "EURGBP",
                      "AUDJPY", "CADJPY"],
    # Indices
    "indices": [
        "DE40",    # DAX Allemagne
        "UK100",   # FTSE 100
        "US500",   # S&P 500
        "US100",   # Nasdaq 100
        "JP225",   # Nikkei 225
        "FR40",    # CAC 40
    ],
    # Métaux
    "metals": ["XAUUSD", "XAGUSD"],  # Or, Argent
    # Énergie
    "energy": ["USOIL", "UKOIL"],
    # Crypto
    "crypto": ["BTCUSD", "ETHUSD"],
}

XM_SPECIFICATIONS = {
    # symbol: {min_lot, max_lot, step, digits, spread_typique}
    "EURUSD":  {"min": 0.01, "max": 50.0, "step": 0.01, "digits": 5, "spread": 0.1},
    "GBPUSD":  {"min": 0.01, "max": 50.0, "step": 0.01, "digits": 5, "spread": 0.3},
    "XAUUSD":  {"min": 0.01, "max": 50.0, "step": 0.01, "digits": 2, "spread": 0.35},
    "DE40":    {"min": 0.01, "max": 50.0, "step": 0.01, "digits": 1, "spread": 0.8},
    "US500":   {"min": 0.01, "max": 50.0, "step": 0.01, "digits": 2, "spread": 0.4},
    "US100":   {"min": 0.01, "max": 50.0, "step": 0.01, "digits": 2, "spread": 1.0},
    "BTCUSD":  {"min": 0.01, "max": 2.0,  "step": 0.01, "digits": 2, "spread": 50.0},
}

# Conversion symboles yfinance → MT5 XM Global
YFINANCE_TO_XM = {
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "USDJPY=X": "USDJPY",
    "GBPJPY=X": "GBPJPY",
    "^GDAXI":   "DE40",
    "^GSPC":    "US500",
    "^NDX":     "US100",
    "GC=F":     "XAUUSD",
    "BTC-USD":  "BTCUSD",
}

# ══════════════════════════════════════════════════════════════════
# AXIOM — CONFIGURATION
# ══════════════════════════════════════════════════════════════════

AXIOM_SERVERS = {
    "demo": [
        "Axiom-Demo",
        "AxiomTrader-Demo",
    ],
    "real": [
        "Axiom-Real",
        "AxiomTrader-Real",
        # Vérifier dans votre espace client Axiom
    ]
}

# Symboles Axiom (similaires à XM, vérifier la nomenclature exacte)
AXIOM_SYMBOLES = {
    "forex":   ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"],
    "indices": ["DAX30", "SPX500", "NAS100", "FTSE100"],
    "metals":  ["GOLD", "SILVER"],
    "crypto":  ["BTCUSD", "ETHUSD"],
}


# ══════════════════════════════════════════════════════════════════
# GUIDE ÉTAPE PAR ÉTAPE
# ══════════════════════════════════════════════════════════════════

GUIDE_XM_SETUP = """
╔══════════════════════════════════════════════════════════════════╗
║  GUIDE D'INSTALLATION — XM Global + MetaTrader 5               ║
╚══════════════════════════════════════════════════════════════════╝

ÉTAPE 1 — Créer un compte DÉMO sur XM Global
─────────────────────────────────────────────
1. Aller sur https://www.xm.com
2. Cliquer "Ouvrir un compte" → Compte démo
3. Choisir MetaTrader 5
4. Remplir le formulaire → Vous recevez par email :
   • Numéro de compte (ex: 12345678)
   • Mot de passe
   • Nom du serveur (ex: XMGlobal-Demo 3)

ÉTAPE 2 — Installer MetaTrader 5
──────────────────────────────────
1. Télécharger MT5 : https://www.xm.com/mt5
2. Installer sur Windows (C:\\Program Files\\MetaTrader 5)
3. Ouvrir MT5 → Se connecter avec vos identifiants démo
4. ✅ Vérifier que le compte est connecté (barre verte en bas)

ÉTAPE 3 — Installer Python + bibliothèques
───────────────────────────────────────────
pip install MetaTrader5 pandas numpy yfinance

ÉTAPE 4 — Configurer le bot
─────────────────────────────
# Dans broker_config.py :
XM_DEMO_LOGIN    = 12345678    # Votre numéro de compte
XM_DEMO_PASSWORD = "motdepasse"
XM_DEMO_SERVER   = "XMGlobal-Demo 3"

ÉTAPE 5 — Premier test (DÉMO)
───────────────────────────────
python main.py --mode broker --broker xm --demo

ÉTAPE 6 — Valider AVANT de passer en réel
──────────────────────────────────────────
✅ Minimum 2 semaines de trading en démo
✅ Minimum 50 trades backtestés ET 20+ trades en démo live
✅ Win rate et profit factor satisfaisants
✅ Max drawdown acceptable pour votre profil
✅ Comprendre CHAQUE trade que le bot passe

╔══════════════════════════════════════════════════════════════════╗
║  ⚠️  NE JAMAIS passer en réel sans ces validations             ║
╚══════════════════════════════════════════════════════════════════╝
"""

GUIDE_AXIOM_SETUP = """
╔══════════════════════════════════════════════════════════════════╗
║  GUIDE D'INSTALLATION — Axiom + MetaTrader 5                   ║
╚══════════════════════════════════════════════════════════════════╝

ÉTAPE 1 — Créer un compte DÉMO sur Axiom
──────────────────────────────────────────
1. Aller sur le site Axiom
2. Ouvrir un compte démo MT5
3. Récupérer : login, password, server name

ÉTAPE 2 — Même procédure que XM
─────────────────────────────────
→ Voir GUIDE_XM_SETUP ci-dessus
→ Remplacer les valeurs de serveur par celles d'Axiom

NOTE : Si les symboles Axiom sont différents de XM
→ Modifier AXIOM_SYMBOLES dans ce fichier
→ Vérifier les noms exacts dans MT5 (clic droit → Symboles)
"""
