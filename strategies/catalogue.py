"""
╔══════════════════════════════════════════════════════════════════╗
║  LES 10 STRATÉGIES DE TRADING MANUEL                           ║
║  Source : Vidéo challenge 30 min                               ║
║                                                                  ║
║  Concept identifié → développé → backtesté → tradé             ║
╚══════════════════════════════════════════════════════════════════╝
"""

from typing import Dict, List

# ══════════════════════════════════════════════════════════════════
# 10 STRATÉGIES PRÉSENTÉES DANS LA VIDÉO
# ══════════════════════════════════════════════════════════════════

STRATEGIES_CATALOGUE: List[Dict] = [
    {
        "id":          1,
        "nom":         "Range Breakout",
        "concept":     "Le prix consolide dans une zone délimitée puis casse avec force. "
                       "On rentre dans la direction de la cassure après confirmation de la clôture.",
        "marche":      "Forex, Indices, Actions, Crypto",
        "timeframe":   "1h, 4h, Daily",
        "conditions_ideales": "Marché en range identifiable avec volumes décroissants pendant la consolidation",
        "entree":      "Clôture de la bougie de cassure (au-dessus/en-dessous du range)",
        "stop_loss":   "De l'autre côté du range (bas du range pour long, haut pour short)",
        "take_profit": "Minimum R/R 3:1 — hauteur du range projetée",
        "invalidation": "Clôture en re-intégrant le range",
        "gestion":     "Scale out à 50% à 2R, laisser courir le reste",
        "pieges": [
            "Faux breakout (cassure sans volume = piège)",
            "Range trop petit pour générer un R/R suffisant",
            "Entrer à l'intérieur du range par anticipation"
        ],
        "checklist": [
            "Range clairement défini (min. 5-10 bougies de consolidation)",
            "Volume décroissant pendant la consolidation",
            "Cassure nette avec clôture HORS du range",
            "Volume élevé sur la bougie de cassure",
            "R/R minimum 2:1",
        ],
        "est_implémentée": True,  # Breakout strategy déjà dans le bot
        "classe_python":   "BreakoutStrategy"
    },
    {
        "id":          2,
        "nom":         "Pullback sur Tendance",
        "concept":     "Le marché casse une zone de structure, fait un pullback sur la zone cassée, "
                       "on prend position au pullback. Tendance + retour sur niveau = confluence.",
        "marche":      "Forex, Indices, Actions",
        "timeframe":   "15min, 1h, 4h",
        "conditions_ideales": "Marché en tendance claire avec cassure structure récente",
        "entree":      "Bougie de confirmation sur le niveau retesté",
        "stop_loss":   "Sous le bas du pullback",
        "take_profit": "Prochain niveau de résistance / R/R 2:1 minimum",
        "invalidation": "Clôture sous le niveau de support retesté",
        "gestion":     "25% à R1, 25% à R2, 50% trailing",
        "pieges": [
            "Pullback trop profond = tendance inversée",
            "Rentrer trop tôt sans confirmation de rebond",
            "Tendance principale faible (ADX < 25)"
        ],
        "checklist": [
            "Tendance haussière confirmée (MA > prix)",
            "Cassure de structure identifiée",
            "Pullback vers la zone cassée",
            "Bougie de confirmation (englobante ou pin bar)",
            "Volume en baisse pendant le pullback"
        ],
        "est_implémentée": True,
        "classe_python":   "PullbackStrategy",
    },
    {
        "id":          3,
        "nom":         "Rebond Support / Résistance",
        "concept":     "Le marché bute à plusieurs reprises sur un niveau. "
                       "On prend position au rebond sur ce niveau avec confirmation.",
        "marche":      "Tous marchés",
        "timeframe":   "Tous timeframes",
        "conditions_ideales": "Niveau testé minimum 2-3 fois, marché clairement délimité",
        "entree":      "Bougie de confirmation sur le niveau (pin bar, englobante)",
        "stop_loss":   "De l'autre côté du niveau (violation = invalidation)",
        "take_profit": "Prochain niveau majeur",
        "invalidation": "Clôture au-delà du niveau avec volume",
        "gestion":     "Scale out progressif vers les objectifs",
        "pieges": [
            "Niveau touché trop de fois = risque de cassure",
            "Faux rebond sans volume",
            "Ignorer la tendance long terme"
        ],
        "checklist": [
            "Niveau testé minimum 2 fois",
            "Bougie de confirmation (corps, pas mèche)",
            "Volume de confirmation",
            "R/R minimum 1.5:1"
        ],
        "est_implémentée": False,
    },
    {
        "id":          4,
        "nom":         "Bull Flag (Drapeau Haussier)",
        "concept":     "Figure chartiste. Mouvement haussier (le mât), puis consolidation "
                       "descendante (le drapeau). À la cassure du drapeau, on prend position.",
        "marche":      "Actions, Indices, Crypto",
        "timeframe":   "Daily, Weekly (meilleurs résultats historiquement)",
        "conditions_ideales": "Marché en forte tendance haussière avec momentum",
        "entree":      "Cassure de la limite haute du drapeau avec volume",
        "stop_loss":   "Sous le bas du drapeau",
        "take_profit": "Hauteur du mât projetée depuis la cassure",
        "invalidation": "Clôture sous le bas du drapeau",
        "gestion":     "Hold jusqu'à objectif ou retour sur EMA",
        "pieges": [
            "Drapeau trop long (>30 bougies = perd son potentiel)",
            "Mât trop petit pour générer un objectif intéressant",
            "Entrer avant la cassure du drapeau"
        ],
        "checklist": [
            "Mât haussier net identifié",
            "Consolidation descendante avec canaux parallèles",
            "Volume décroissant pendant le drapeau",
            "Cassure avec regain de volume",
            "Marché général haussier"
        ],
        "est_implémentée": True,
        "classe_python":   "BullFlagStrategy",
    },
    {
        "id":          5,
        "nom":         "Double Bottom",
        "concept":     "Figure chartiste avec deux creux au même niveau. "
                       "La neckline se situe sur le haut entre les deux creux. "
                       "L'entrée se fait à la cassure de cette neckline.",
        "marche":      "Tous marchés",
        "timeframe":   "4h, Daily, Weekly",
        "conditions_ideales": "Après une tendance baissière prolongée, "
                               "les deux creux doivent être à ±2% l'un de l'autre",
        "entree":      "Cassure de la neckline (haut entre les deux creux) avec volume",
        "stop_loss":   "Sous le deuxième creux",
        "take_profit": "Hauteur du double bottom projetée depuis la neckline",
        "invalidation": "Clôture sous le deuxième creux",
        "gestion":     "Hold sur objectif projection",
        "pieges": [
            "Erreur de placement de la neckline (vidéo : la neckline est sur le HAUT, pas le milieu)",
            "Rentrer avant la cassure de la neckline",
            "Contexte marché baissier général"
        ],
        "checklist": [
            "Deux creux visibles à distance comparable",
            "Creux à moins de 3% l'un de l'autre",
            "Neckline identifiée sur le HAUT entre les deux creux",
            "Cassure de la neckline avec volume",
            "Pas de tendance baissière majeure"
        ],
        "est_implémentée": True,
        "classe_python":   "DoubleBottomStrategy",
        "note_video": "La vidéo souligne une erreur possible : "
                      "la neckline DOIT être sur le haut entre les deux creux."
    },
    {
        "id":          6,
        "nom":         "Inside Bar Breakout",
        "concept":     "Une bougie (inside bar) s'ouvre ET se ferme entièrement "
                       "dans la range de la bougie précédente (bougie mère). "
                       "On prend position à la cassure de l'inside bar.",
        "marche":      "Forex, Actions",
        "timeframe":   "4h, Daily",
        "conditions_ideales": "Après un mouvement directionnel fort, en compression",
        "entree":      "Cassure de la limite haute ou basse de la bougie mère",
        "stop_loss":   "Limite opposée de la bougie mère",
        "take_profit": "Selon contexte et R/R",
        "invalidation": "Clôture dans la bougie mère sans cassure",
        "gestion":     "Standard",
        "pieges": [
            "Inside bars dans un range = faux signal",
            "Très petite inside bar = manque de compression",
            "Trop d'inside bars consécutives affaiblissent le signal"
        ],
        "checklist": [
            "Inside bar clairement identifiée",
            "Bougie mère visible et significative",
            "Cassure nette avec clôture hors de la bougie mère",
        ],
        "est_implémentée": True,
        "classe_python":   "InsideBarStrategy",
    },
    {
        "id":          7,
        "nom":         "Opening Range Breakout (ORB)",
        "concept":     "Schématiser une consolidation par rapport à une session "
                       "(ouverture Londres, New York, Asie) et trader la cassure "
                       "de cette consolidation.",
        "marche":      "Forex, Indices",
        "timeframe":   "1min, 5min, 15min",
        "conditions_ideales": "Premières minutes de la session ciblée "
                               "(Londres 8h-9h Paris, NY 14h30-15h30 Paris)",
        "entree":      "Cassure du high ou low formé pendant la première heure",
        "stop_loss":   "Limite opposée du range de la session",
        "take_profit": "Extension du range, R/R 2:1 minimum",
        "invalidation": "Retour dans le range de session",
        "gestion":     "Scale out rapide (intraday)",
        "pieges": [
            "Faux breakout en début de session = très fréquent",
            "Ignorer les annonces économiques en début de session",
            "Range trop petit sur faible volatilité"
        ],
        "checklist": [
            "Session identifiée (Londres ou New York recommandé)",
            "Range de la première heure clairement défini",
            "Cassure nette avec volume",
            "Pas d'annonce économique majeure dans la session"
        ],
        "est_implémentée": True,
        "classe_python":   "OpeningRangeBreakoutStrategy",
    },
    {
        "id":          8,
        "nom":         "Rebond VWAP",
        "concept":     "Le VWAP (Volume Weighted Average Price) agit comme support/résistance dynamique. "
                       "On prend position au rebond ou à la cassure du VWAP avec confirmation.",
        "marche":      "Actions (intraday), Indices, Futures",
        "timeframe":   "1min, 5min, 15min",
        "conditions_ideales": "Intraday, après une cassure ou un retour sur le VWAP",
        "entree":      "Confirmation de rebond/rejet sur le VWAP",
        "stop_loss":   "De l'autre côté du VWAP",
        "take_profit": "Extension ATR, résistance suivante",
        "invalidation": "Clôture de l'autre côté du VWAP",
        "gestion":     "Sortie partielle rapide (scalp ou swing court)",
        "pieges": [
            "VWAP peu pertinent sur Forex",
            "Reset du VWAP chaque session = recalculer",
            "Marché volatile = VWAP perd sa pertinence"
        ],
        "checklist": [
            "Actif adapté au VWAP (actions, futures)",
            "VWAP testé minimum 2 fois dans la session",
            "Volume de confirmation sur le rebond",
        ],
        "est_implémentée": False,
        "note_video": "La vidéo mentionne : 'Ce n'est pas un indicateur que j'utilise, "
                      "je n'ai pas de data.' — À tester personnellement."
    },
    {
        "id":          9,
        "nom":         "Épaule-Tête-Épaule Inversée",
        "concept":     "Figure chartiste de retournement. "
                       "Trois creux (gauche-centre plus bas-droite), avec neckline au-dessus. "
                       "La cassure de la neckline déclenche le signal haussier.",
        "marche":      "Tous marchés",
        "timeframe":   "4h, Daily, Weekly",
        "conditions_ideales": "Après une tendance baissière prolongée, "
                               "figure bien formée avec les trois creux visibles",
        "entree":      "Cassure de la neckline avec volume",
        "stop_loss":   "Sous la tête (creux central)",
        "take_profit": "Hauteur de la figure projetée depuis la neckline",
        "invalidation": "Retour sous la neckline",
        "gestion":     "Hold sur projection théorique de la figure",
        "pieges": [
            "Figure imparfaite = signal non valide",
            "Neckline oblique = signal moins fiable",
            "Volume absent à la cassure"
        ],
        "checklist": [
            "Trois creux identifiables",
            "Épaule gauche ≈ épaule droite (symétrie)",
            "Tête (creux central) nettement plus bas",
            "Neckline tracée sur les hauts entre les creux",
            "Cassure de la neckline avec volume"
        ],
        "est_implémentée": False,
    },
    {
        "id":          10,
        "nom":         "Englobante Haussière",
        "concept":     "Une petite bougie baissière suivie d'une large bougie haussière "
                       "dont le corps ENGLOBE entièrement le corps de la précédente. "
                       "Signal de retournement à court terme. Plus le nombre de bougies "
                       "englobées est élevé, plus le signal est fort.",
        "marche":      "Tous marchés — idéalement actifs Long uniquement (vidéo)",
        "timeframe":   "Daily recommandé (vidéo), 4h, 1h",
        "conditions_ideales": "Long sur actif en tendance haussière structurelle, "
                               "avec filtres MA 50/100/150",
        "entree":      "3 options : clôture de l'englobante / 50% du corps / ouverture suivante",
        "stop_loss":   "Sous le plus bas de l'englobante",
        "take_profit": "Résistances suivantes, R/R minimum 2:1",
        "invalidation": "Clôture sous le stop loss / Retour sous l'englobante",
        "gestion":     "Scale out : 25% à TP1 + SL break even, 25% à TP2, 50% trailing EMA",
        "pieges": [
            "Englobante sans contexte (pas de confluence) = signal faible",
            "Entrer sur n'importe quelle englobante sans filtre tendance",
            "Ignorer les annonces économiques majeures (NFP, FOMC, CPI)",
            "Utiliser cette stratégie en marché baissier",
            "Win rate peut sembler bas → normal, les gros gagnants compensent"
        ],
        "checklist": [
            "Corps de la bougie verte ENGLOBE corps de la bougie précédente",
            "Bougie courante haussière (close > open)",
            "Bougie précédente baissière (close < open)",
            "Prix au-dessus MA (50 ou 100 ou 150)",
            "Pas d'annonce majeure imminente",
            "R/R minimum 2:1",
            "Volume idéalement supérieur à la moyenne"
        ],
        "est_implémentée": True,
        "classe_python":    "EnglobanteHaussiere"
    },
]

# ══════════════════════════════════════════════════════════════════
# RECOMMANDATIONS TIMEFRAMES ET ACTIFS (vidéo 2)
# ══════════════════════════════════════════════════════════════════

TIMEFRAMES_RECOMMANDES = {
    "scalping_ultra_court": {
        "timeframe": "1 minute",
        "pour":      "Scalp rapide, recherche d'entrée précise après signal",
        "contre":    "Beaucoup de bruit, spread impactant, stress élevé",
        "utilisation": "Affiner l'entrée après identification sur 5min ou plus"
    },
    "scalping_intraday": {
        "timeframe": "5 minutes",
        "pour":      "'Juste milieu entre qualité et quantité' (vidéo). "
                     "Recommandé pour le challenge 1h.",
        "contre":    "Nécessite une surveillance active",
        "utilisation": "Stratégie principale pour les sessions Forex"
    },
    "swing_court": {
        "timeframe": "15 minutes",
        "pour":      "Moins de bruit que le 5min, signaux plus fiables",
        "contre":    "Moins d'opportunités intraday",
        "utilisation": "Swing court sur indices, liquidité sweep"
    },
    "swing_moyen": {
        "timeframe": "1 heure",
        "pour":      "Signaux de qualité, gestion émotionnelle plus facile",
        "contre":    "Peu de trades par semaine",
        "utilisation": "Breakout et englobante haussière"
    },
    "position": {
        "timeframe": "Journalier (Daily)",
        "pour":      "Moins de temps de surveillance, signaux fiables",
        "contre":    "Lent, capital immobilisé longtemps",
        "utilisation": "Englobante haussière, CANSLIM, patterns chartistes"
    }
}

ACTIFS_RECOMMANDES_VIDEO = {
    "forex_ultra_liquide": {
        "actifs":    ["EUR/USD", "GBP/USD"],
        "pourquoi":  "Haute liquidité, spreads très bas, très tradés",
        "session":   "Londres + New York (8h-22h Paris)",
        "timeframe": "5min, 15min, 1h",
    },
    "forex_volatil": {
        "actifs":    ["GBP/JPY", "EUR/JPY", "USD/JPY"],
        "pourquoi":  "Forte volatilité, bonnes opportunités de sweep",
        "session":   "Asie + Londres",
        "timeframe": "5min, 15min",
    },
    "indices_europeens": {
        "actifs":    ["DAX (GER40)", "CAC40 (FRA40)"],
        "pourquoi":  "Forte volatilité à l'ouverture (8h-10h Paris), bougé recommandé vidéo",
        "session":   "Ouverture Londres",
        "timeframe": "1min, 5min, 15min",
    },
    "indices_us": {
        "actifs":    ["S&P 500 (SPX500)", "Nasdaq (NAS100)", "Dow Jones"],
        "pourquoi":  "Haute liquidité, tendances claires",
        "session":   "New York (14h30-21h Paris)",
        "timeframe": "5min, 15min, 1h",
    },
    "actions_long_terme": {
        "actifs":    ["Actions US (screener TradingView)", "ETF sectoriels"],
        "pourquoi":  "Tendances longues, idéaux pour englobante + CANSLIM",
        "session":   "NYSE + Nasdaq",
        "timeframe": "Daily, Weekly",
    }
}

# ══════════════════════════════════════════════════════════════════
# RÈGLES DU CHALLENGE (vidéo 1 et 2)
# ══════════════════════════════════════════════════════════════════

REGLES_CHALLENGE_V1 = {
    "titre":     "Challenge 30 minutes — Créer une stratégie de trading",
    "règles": [
        "Utiliser uniquement Claude pour créer la stratégie",
        "La stratégie doit être complète de A à Z",
        "Pas de statistiques inventées sans preuve",
        "La stratégie créée sera fournie gratuitement"
    ],
    "etapes": [
        "1. Trouver une idée de stratégie rentable",
        "2. Construire un plan qui respecte la méthode de A à Z",
        "3. Trader avec cette nouvelle stratégie"
    ],
    "avertissements_video": [
        "Les statistiques générées par une IA sont TOUJOURS à vérifier",
        "Win rates, fréquences, RR indicatifs = non vérifiés",
        "Backtestez TOUJOURS sur minimum 50 trades avant le réel",
        "Testez sur plusieurs actifs et timeframes différents",
        "L'IA est un générateur d'idées, pas une source de vérité"
    ]
}

REGLES_CHALLENGE_V2 = {
    "titre":     "Challenge 1 heure — Gagner 100€ avec 1 000€ de capital",
    "règles": [
        "Interdit d'utiliser des stratégies déjà connues",
        "Pas d'aide extérieure",
        "Tout ce fait sur le marché doit être confirmé par Claude",
        "Pas de décision sans validation de Claude"
    ],
    "prompt_structure": [
        "1. Objectifs — Définir clairement ce qu'on veut de Claude",
        "2. Format — Être hyper concis, listes à puces",
        "3. Attentes — Demander d'AMÉLIORER chaque réponse (key insight vidéo)"
    ],
    "avertissements_video": [
        "Pine Script généré par Claude peut avoir des bugs — toujours tester",
        "La génération de code est chronophage (2-3 min par itération)",
        "Les zones 'grises' = déjà liquidées = ne plus les trader",
        "Un trade intraday peut durer 2h — adapter au timeframe disponible",
        "Toujours vérifier les annonces économiques avant de trader"
    ]
}


def print_strategy_catalogue():
    """Affiche le catalogue des 10 stratégies."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  CATALOGUE — 10 STRATÉGIES DE TRADING MANUEL               ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")

    for s in STRATEGIES_CATALOGUE:
        impl = "✅ Implémentée" if s.get('est_implémentée') else "⏳ Disponible"
        print(f"  {s['id']:>2}. {s['nom']:<30} {impl}")
        print(f"      {s['concept'][:80]}...")
        print(f"      Timeframe: {s['timeframe']} | Marché: {s['marche'][:40]}")
        print()


def print_timeframes_recommandes():
    """Affiche les recommandations timeframes de la vidéo."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  TIMEFRAMES RECOMMANDÉS (vidéo)                             ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")
    for key, tf in TIMEFRAMES_RECOMMANDES.items():
        print(f"  {tf['timeframe']}")
        print(f"    ✅ Pour : {tf['pour'][:70]}")
        print(f"    ❌ Contre : {tf['contre'][:70]}")
        print()


def print_actifs_recommandes():
    """Affiche les actifs recommandés par la vidéo."""
    print("\n╔══════════════════════════════════════════════════════════════╗")
    print("║  ACTIFS RECOMMANDÉS (vidéo)                                 ║")
    print("╚══════════════════════════════════════════════════════════════╝\n")
    for key, a in ACTIFS_RECOMMANDES_VIDEO.items():
        print(f"  {', '.join(a['actifs'])}")
        print(f"    Pourquoi : {a['pourquoi'][:70]}")
        print(f"    Session  : {a['session']}")
        print(f"    TF       : {a['timeframe']}")
        print()
