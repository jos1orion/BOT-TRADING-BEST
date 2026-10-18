"""
Configuration spécifique Deriv (MetaTrader 5).

Deriv propose MT5 avec :
  • des Forex / métaux / indices CFD classiques (EURUSD, XAUUSD…)
  • des indices synthétiques (Volatility, Boom, Crash, Step, Jump…) cotés 24/7

Les NOMS de symboles et de serveurs peuvent varier selon l'entité Deriv
(SVG, BVI, Vanuatu…) et le type de compte (Standard, Financial STP, Zero Spread…).
Le bot résout donc automatiquement les noms au démarrage (voir
MT5Connector.resolve_symbol) à partir des alias ci-dessous : si un symbole
n'existe pas chez vous, il est simplement ignoré avec un avertissement.

Pour voir vos noms exacts : MT5 → Vue → Symboles (Ctrl+U).
"""

# ══════════════════════════════════════════════════════════════════
# SERVEURS (le vôtre apparaît dans MT5 → Fichier → Ouvrir un compte,
# ou dans votre espace Deriv → onglet MT5 → "Info" du compte)
# ══════════════════════════════════════════════════════════════════
DERIV_SERVERS = {
    "demo": [
        "Deriv-Demo",
        "DerivSVG-Demo",
    ],
    "real": [
        "Deriv-Server",
        "Deriv-Server-02",
        "DerivSVG-Server",
        "DerivSVG-Server-02",
        "DerivBVI-Server",
    ],
}

# ══════════════════════════════════════════════════════════════════
# ALIAS DE SYMBOLES : nom "canonique" du bot → noms possibles chez Deriv
# (comparaison insensible à la casse, espaces et ponctuation ignorés)
# ══════════════════════════════════════════════════════════════════
DERIV_SYMBOL_ALIASES = {
    # Forex
    "EURUSD": ["EURUSD"],
    "GBPUSD": ["GBPUSD"],
    "USDJPY": ["USDJPY"],
    "USDCHF": ["USDCHF"],
    "AUDUSD": ["AUDUSD"],
    "USDCAD": ["USDCAD"],
    "GBPJPY": ["GBPJPY"],
    "EURJPY": ["EURJPY"],
    # Métaux
    "XAUUSD": ["XAUUSD", "GOLD"],
    "XAGUSD": ["XAGUSD", "SILVER"],
    # Énergie (noms affichés dans MT5 Deriv)
    "USOIL":  ["US Oil", "USOIL"],
    "UKOIL":  ["UK Brent Oil", "UKOIL"],
    # Indices (noms Deriv ≠ noms XM)
    "DE40":   ["Germany 40", "Germany40", "DE40", "GER40", "DAX40", "DE30"],
    "UK100":  ["UK 100", "UK100", "FTSE100"],
    "FR40":   ["France 40", "FR40", "CAC40"],
    "US500":  ["US SP 500", "US500", "SPX500", "SP500", "S&P 500"],
    "US100":  ["US Tech 100", "US100", "NAS100", "USTEC"],
    "US30":   ["Wall Street 30", "US30", "DJ30"],
    "JP225":  ["Japan 225", "JP225", "JPN225"],
    # Crypto (disponible sur Deriv MT5 Financial / Standard)
    "BTCUSD": ["BTCUSD", "BTC/USD", "Bitcoin", "BTCUSD.cash", "CryBTCUSD", "BTC", "BTCUSD+", "BTCUSDT", "BTC-USD"],
    "ETHUSD": ["ETHUSD", "ETH/USD", "Ethereum", "ETHUSD.cash", "CryETHUSD", "ETH", "ETHUSD+", "ETHUSDT", "ETH-USD"],
    # Indices synthétiques Deriv (24/7)
    "V10":    ["Volatility 10 Index"],
    "V25":    ["Volatility 25 Index"],
    "V50":    ["Volatility 50 Index"],
    "V75":    ["Volatility 75 Index"],
    "V100":   ["Volatility 100 Index"],
    "V75_1S": ["Volatility 75 (1s) Index"],
    "V100_1S": ["Volatility 100 (1s) Index"],
    "BOOM1000":  ["Boom 1000 Index"],
    "CRASH1000": ["Crash 1000 Index"],
    "BOOM500":   ["Boom 500 Index"],
    "CRASH500":  ["Crash 500 Index"],
    "STEP":   ["Step Index"],
    "JUMP25": ["Jump 25 Index"],
    "JUMP75": ["Jump 75 Index"],
}

# Symboles synthétiques : cotés 24/7, insensibles aux news économiques
DERIV_SYNTHETIC = {
    "V10", "V25", "V50", "V75", "V100", "V75_1S", "V100_1S",
    "BOOM1000", "CRASH1000", "BOOM500", "CRASH500", "STEP", "JUMP25", "JUMP75",
}

# Fragments de nom (en majuscules) qui identifient un indice synthétique
# une fois le symbole résolu côté broker.
SYNTHETIC_NAME_HINTS = ("VOLATILITY", "BOOM", "CRASH", "STEP INDEX", "JUMP", "RANGE BREAK", "DEX ")


def is_synthetic(symbol: str) -> bool:
    """True si le symbole (canonique ou nom broker) est un indice synthétique Deriv."""
    s = symbol.upper().strip()
    return s in DERIV_SYNTHETIC or any(h in s for h in SYNTHETIC_NAME_HINTS)


GUIDE_DERIV_SETUP = """
GUIDE — Deriv + MetaTrader 5
────────────────────────────
1. Créez un compte sur https://deriv.com puis ouvrez un compte DÉMO MT5
   (Trader's Hub → CFDs → Deriv MT5 → Démo). Choisissez "Standard" ou
   "Financial" pour Forex/Or/Indices, "Standard" pour les synthétiques.
2. Notez : numéro de compte MT5 (login), mot de passe MT5 (≠ mot de passe Deriv),
   nom du serveur (ex. Deriv-Demo).
3. Installez MetaTrader 5 (Windows) et connectez-vous une première fois
   avec ces identifiants pour vérifier que tout fonctionne.
4. Dans le fichier .env (ou broker_credentials.py) :
       TRADING_BOT_ACTIVE_BROKER=DERIV
       DERIV_DEMO_LOGIN=12345678
       DERIV_DEMO_PASSWORD=...
       DERIV_DEMO_SERVER=Deriv-Demo
5. Lancez :  python live_trading.py --broker deriv --demo
6. Pour tester la connexion et les symboles sans passer d'ordre :
       python live_trading.py --broker deriv --demo --check
"""
