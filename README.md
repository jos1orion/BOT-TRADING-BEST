# 🤖 Trading Bot — Multi-Stratégie

Bot de trading automatisé basé sur 4 stratégies professionnelles reconnues.

> ⚠️ **AVERTISSEMENT IMPORTANT**  
> Ce bot fonctionne **uniquement en Paper Trading** (simulation).  
> Il est fourni **à but éducatif uniquement** et ne constitue pas un conseil  
> en investissement. N'utilisez jamais de l'argent réel sans :
> - Des backtests rigoureux sur vos propres données
> - Une validation par un professionnel financier agréé
> - Une gestion du risque personnalisée à votre situation

---

## 📦 Installation

```bash
# 1. Cloner / télécharger le projet
cd trading_bot

# 2. Installer les dépendances (Python 3.10+)
pip install -r requirements.txt

# 3. Lancer le premier scan
python main.py --mode scan
```

---

## 🚀 Utilisation

### Scanner les opportunités
```bash
# Scan toutes les stratégies
python main.py --mode scan

# Scan uniquement la stratégie Breakout
python main.py --mode scan --strategy breakout

# Scan en mode verbose (détail de chaque indicateur)
python main.py --mode scan --verbose
```

### Backtest sur données historiques
```bash
# Backtest sur 1 an (252 jours)
python main.py --mode backtest --days 252

# Backtest sur 2 ans avec capital 25 000$
python main.py --mode backtest --days 504 --capital 25000
```

### Paper Trading live
```bash
# Démarrer le paper trading (scan toutes les heures)
python main.py --mode paper --capital 10000

# Avec capital personnalisé et Mean Reversion uniquement
python main.py --mode paper --strategy mean_reversion --capital 5000
```

### Rapport de performance
```bash
python main.py --mode report
```

### Backtest walk-forward (robustesse multi-régime)
```bash
python main.py --mode backtest-wf --folds 4 --fold-days 126
```
Découpe l'historique en fenêtres indépendantes (capital réinitialisé à
chaque fenêtre) pour vérifier que l'edge est cohérent sur plusieurs
régimes de marché plutôt que le fruit d'une seule période chanceuse.

### Journal de trading (export Excel/CSV)
```bash
python main.py --mode journal
```
Chaque trade (ouverture, clôture, sortie partielle) est automatiquement
loggé dans `trading_journal.csv` au fil de l'eau. Ce mode affiche la
synthèse (win rate, profit factor, drawdown) et exporte un rapport
`.xlsx` complet (feuille "Trades" + feuille "Synthèse"). Sans `openpyxl`
installé, un résumé `.csv` est produit à la place.

---

## 🔒 Configuration des secrets (variables d'environnement)

Tous les identifiants sensibles (`broker_credentials.py`) se lisent en
priorité depuis des variables d'environnement, avec des valeurs de
secours pour un usage local rapide :
```bash
cp .env.example .env
# Éditez .env avec vos vraies valeurs (jamais commité — voir .gitignore)
```
`python-dotenv` charge automatiquement `.env` s'il est présent. Sur un
serveur, définissez plutôt de vraies variables d'environnement système.

### Bot autonome crypto (`live_crypto_bot.py`)
Boucle continue : scan → signal (Mean Reversion / Liquidity Sweep) →
sizing selon `risk_per_trade` → drawdown guard → ouverture/suivi de
position → journal + Telegram. Mode `paper` par défaut (`BINGX_MODE`
dans `.env`).

```bash
python live_crypto_bot.py --interval 300 --risk 2.5
```

⚠️ Avant tout mode `live` (argent réel) :
1. Avoir des résultats de backtest (`backtest_crypto.py`) qui montrent un edge réel
2. Faire tourner en `paper` plusieurs jours et vérifier `crypto_trading_journal.csv`
3. Vérifier `_klines_to_dataframe()` contre une vraie réponse BingX (le
   format exact n'a pas pu être validé sans accès réseau en développement)
4. Passer `BINGX_MODE=live` dans `.env` — une confirmation explicite est
   demandée au lancement, le bot ne bascule jamais en réel silencieusement

⚠️ L'état (positions ouvertes, cash) est sauvegardé dans
`crypto_bot_state.json` après chaque cycle, mais ce n'est pas une vraie
base transactionnelle — vérifier périodiquement qu'il correspond bien à
la réalité de ton compte BingX.

---

## 🪙 Crypto — BingX & Sniping Solana (nouveau)

### BingX (`core/brokers/bingx_connector.py`)
Connecteur REST pour trader du spot crypto sur BingX. Démarre toujours
en `mode="paper"` (aucune requête d'écriture envoyée, ordres simulés
localement). Documentation officielle : https://bingx-api.github.io/docs/

```python
from core.brokers.bingx_connector import BingXConnector, BingXOrder

bot = BingXConnector(api_key="...", api_secret="...", mode="paper")
bot.get_ticker_24h("BTC-USDT")
bot.place_order(BingXOrder(symbol="BTC-USDT", side="BUY",
                            order_type="MARKET", quantity=0.001))
```
⚠️ Ce connecteur n'a pas pu être testé contre l'API réelle (pas d'accès
réseau en développement) — valider chaque endpoint avec de petits
montants avant tout usage sérieux.

### Sniping Solana (`core/solana/`, `main_solana.py`)
Détection de nouveaux tokens/pools créés sur Solana (Raydium, Pump.fun),
filtrage anti-rug/anti-honeypot, et journalisation en mode simulation —
**aucune transaction réelle envoyée par défaut**.

```bash
python main_solana.py            # mode simulate, tourne en continu
python main_solana.py --report   # résumé du journal de simulation
```

Composants :
- `core/solana/config.py` — RPC, programmes surveillés, seuils de filtre
- `core/solana/token_scanner.py` — détection temps réel via websocket RPC
- `core/solana/filters.py` — checks anti-rug (liquidité, holders,
  mint/freeze authority, taxes buy/sell) — **plusieurs méthodes sont des
  TODO à brancher sur un vrai fournisseur de données** (Helius DAS,
  Birdeye, RugCheck...)
- `core/solana/wallet_tracker.py` — suivi de wallets pour copy trading
  (adresses publiques uniquement — **jamais de clé privée**)
- `core/solana/simulator.py` — journal CSV des candidats (acceptés/rejetés)

**Prérequis avant tout passage en réel :**
1. Un RPC Solana dédié et payé (Helius/QuickNode/Triton) — le RPC public
   est trop lent et rate-limité pour du sniping.
2. `filters.py` : le check mint/freeze authority est maintenant **réel**
   (`core/solana/spl_utils.py`, décode le compte SPL Token directement).
   Liquidité, holders et taxe buy/sell restent des TODO à brancher.
3. Un wallet Solana **dédié au bot**, séparé de tout wallet personnel,
   configuré via `SOLANA_WALLET_PRIVATE_KEY` dans `.env` — jamais en dur.
4. Plusieurs jours de mode `simulate` pour juger la qualité réelle des
   filtres avant de brancher un wallet.

### Exécution réelle (`core/solana/jupiter_swap.py`)
Même principe que Trojan/BonkBot : quote Jupiter → transaction de swap →
signature locale → envoi au réseau. Requêtes/réponses validées contre le
format officiel documenté par Jupiter (pas contre l'API réelle — pas de
réseau en développement).

```bash
python main_solana.py                # mode simulate (défaut, sûr)
python main_solana.py --live         # exécution réelle — confirmation demandée
```

⚠️ Avant `--live` :
- `pip install solders base58`
- Vérifier `_sol_price_usd_placeholder()` dans `main_solana.py` (prix SOL
  figé à corriger avec un vrai appel API)
- Aucune protection MEV/anti-sandwich (contrairement à Trojan/Banana Gun
  qui routent via Jito) — le bot peut se faire front-runner sur des
  tokens très demandés
- Une clé API Jupiter (https://portal.jup.ag) est recommandée pour un
  débit correct en usage intensif

⚠️ Le sniping de tokens neufs sur Solana reste structurellement à haut
risque même avec de bons filtres : une grande partie des tokens créés
chaque jour sont des rugs ou honeypots, et le bot est en concurrence
avec des acteurs professionnels ayant une infrastructure bien plus
rapide (RPC colocalisés, accès mempool privilégié).

---

## 📱 Contrôle complet depuis Telegram (`telegram_control_bot.py`)

Pilote les DEUX bots (BingX + sniper Solana) depuis Telegram, comme
Trojan/BonkBot : `/status`, `/positions`, `/balance`, `/pnl`,
`/pause_crypto`, `/resume_crypto`, `/pause_solana`, `/resume_solana`,
`/solana_report`, `/buy TICKER`, `/sell TICKER`.

```bash
pip install python-telegram-bot solders base58
python telegram_control_bot.py
```

⚠️ **Sécurité critique** : seul le `chat_id` configuré dans
`broker_credentials.py` (`TELEGRAM_CONFIG`) peut envoyer des commandes —
vérifié à CHAQUE message, sans exception. Sans ce chat_id configuré,
toutes les commandes sont refusées par défaut (sécurité par défaut, pas
un bug). Configure d'abord ton bot via @BotFather (voir `core/notifier.py`
pour les instructions), récupère ton chat_id, puis remplis
`TELEGRAM_CONFIG` avant de lancer.
Ne mets jamais l'identifiant numérique du bot (@BotFather / getMe) dans
`TELEGRAM_CHAT_ID`, `TELEGRAM_OWNER_IDS` ou `TELEGRAM_MINIAPP_USER_IDS` :
Telegram interdit à un bot de s'envoyer des messages à lui-même. Au
démarrage, le bot détecte cet identifiant et le retire des destinataires;
remplace-le par l'identifiant d'un compte humain pour rétablir cet accès.

⚠️ Ce module n'a pas pu être testé contre l'API Telegram réelle (pas de
réseau en développement) — seules la logique d'autorisation et les
commandes `/buy`/`/sell` ont été validées avec des objets simulés.
Teste d'abord `/status` et `/help` chez toi pour confirmer que la
connexion Telegram fonctionne avant de faire confiance à `/buy`/`/sell`.

---

## 🆕 Fonctionnalités ajoutées

### 📅 Filtre d'actualités économiques (NFP, FOMC, CPI)
`core/news_filter.py` télécharge un calendrier économique réel et
bloque automatiquement l'ouverture de nouvelles positions **30 minutes
avant et après** une annonce à fort impact (configurable via
`news_buffer_minutes`). En cas de coupure réseau, il retombe sur le
cache local puis sur une estimation de secours (NFP = 1er vendredi du
mois, CPI ≈ le 12) — le bot ne trade jamais "à l'aveugle" silencieusement.
Activé par défaut (`avoid_news = True` dans `Config` / `broker_credentials.py`).

### 📲 Notifications Telegram en temps réel
`core/notifier.py` envoie une alerte Telegram instantanée à chaque
signal détecté, trade ouvert/fermé, mise en pause du bot (drawdown,
news) ou erreur critique — utile quand le bot tourne à 3h du matin.
Configuration dans `broker_credentials.py` :
```python
TELEGRAM_CONFIG = {
    "enabled": True,
    "bot_token": "...",   # via @BotFather
    "chat_id": "...",     # via api.telegram.org/bot<TOKEN>/getUpdates
}
```

### 📓 Journal de trading automatique
`core/journal.py` enregistre chaque trade dans `trading_journal.csv`
(ouverture, clôture, raison de sortie, PnL, R-multiple) et peut
exporter un rapport Excel complet avec la synthèse des performances.

### 🛡️ Protection contre le drawdown excessif (kill-switch)
`core/drawdown_guard.py` met le bot en pause automatiquement si :
- Le drawdown dépasse `drawdown_daily_limit_pct` (3% par défaut) sur la journée,
- ou `drawdown_weekly_limit_pct` (6% par défaut) sur la semaine,
- ou après `max_consecutive_losses` pertes d'affilée (5 par défaut).

La pause se lève automatiquement au jour/semaine suivant (sauf pour
les pertes consécutives, qui nécessitent une revue puis une confirmation
`/reset_garde` sur Telegram). Les références
jour/semaine, la pause et le compteur de pertes sont sauvegardés dans un
fichier local ignoré par Git, propre au broker, au compte et au mode démo/réel.
Si ce fichier est illisible ou impossible à sauvegarder, le bot signale une
erreur au lieu de poursuivre en supposant que les protections sont actives.

Le risque cumulé au stop-loss des positions ouvertes est plafonné à 3% de
l'equity par défaut (`MAX_TOTAL_OPEN_RISK_PCT`). Une position sans stop-loss
ou dont le risque ne peut pas être évalué bloque les nouvelles entrées. Le
risque est recalculé après chaque exécution avant d'autoriser un autre ordre.

### 🌍 Filtre de marché adapté par classe d'actif
`core/market_filter.py` : le filtre "SPY/QQQ au-dessus des EMA" n'a de
sens que pour les actions US. Pour le Forex, les indices européens
(DAX/CAC) et les indices US, un benchmark adapté est utilisé
automatiquement (`guess_asset_class()` détecte la classe depuis le
symbole) ; à défaut, le filtre retombe sur la tendance propre de
l'instrument (EMA 8/21/50).

### 💧 Slippage estimé dans le sizing
`core/brokers/mt5_connector.py` ajoute une marge de slippage estimée
(`slippage_pct`, 0.05% par défaut) à la distance de risque avant de calculer
les lots. Le volume est arrondi vers le bas; si le lot minimum du broker
dépasse le risque cible, l'ordre est refusé plutôt que de dépasser le budget.
Cette estimation ne remplace pas les coûts et glissements réels du broker.

### 🧩 5 stratégies supplémentaires (catalogue des 10)
Implémentées dans `strategies/patterns.py` :
- **Pullback sur Tendance** — cassure de structure + retour + confirmation
- **Bull Flag** — mât haussier + drapeau + cassure
- **Double Bottom** — deux creux comparables + cassure de neckline
- **Inside Bar Breakout** — compression + cassure de la bougie mère
- **Opening Range Breakout (ORB)** — cassure du range de la première heure de session

⚠️ Ce sont des implémentations raisonnables des concepts décrits —
backtestez-les (minimum 50 trades, méthode dans `strategies/catalogue.py`)
avant tout usage réel, en particulier l'ORB qui nécessite des données intraday.

### 🔗 Corrélation entre positions
Deux actifs peuvent être dans des "secteurs" différents mais bouger
ensemble (ex: NVDA/AMD/MU). `can_open_position()` calcule désormais la
corrélation des rendements (60 jours) avec les positions déjà ouvertes
et plafonne le nombre de positions simultanément corrélées
(`correlation_threshold` = 70%, `max_correlated_positions` = 2 par défaut).

### 💧 Liquidité vs taille d'ordre
La taille de position est plafonnée à `max_volume_participation_pct`
(2% par défaut) du volume moyen 20 jours, pour éviter un slippage
important sur les petites capitalisations. Si même 1 action représente
trop du volume, l'ouverture est bloquée entièrement.

### 📊 Backtest walk-forward
`backtest_walk_forward()` découpe l'historique en fenêtres indépendantes
et rapporte une synthèse de robustesse (rendement moyen/médian, % de
fenêtres profitables) — pour distinguer un edge réel d'une performance
qui ne tient que sur une période chanceuse.

### 📅 Dates FOMC réelles en secours
Le fallback du calendrier économique (`core/news_filter.py`) utilise
désormais les 8 vraies dates de réunion FOMC 2026 (vérifiées sur
federalreserve.gov) plutôt qu'une estimation par calcul, en plus de
l'estimation NFP/CPI.

### 📈 Tracking réel des clôtures MT5
`live_trading.py` interroge désormais `mt5.history_deals_get()`
(`get_recent_closed_deals()`) pour récupérer le PnL exact des positions
fermées côté broker (SL/TP touché) plutôt que de simplement constater
leur disparition — le journal et le drawdown guard reçoivent ainsi de
vrais résultats en conditions live, pas des estimations.

---

## 📐 Architecture

```
trading_bot/
├── main.py                    # Point d'entrée CLI
├── requirements.txt
├── core/
│   ├── config.py              # Configuration (watchlist, paramètres)
│   ├── data.py                # Données via yfinance
│   ├── indicators.py          # Indicateurs techniques (EMA, RSI, BB, ATR...)
│   ├── risk.py                # Gestion du risque & position sizing
│   └── engine.py              # Moteur principal (scan/backtest/paper)
└── strategies/
    └── strategies.py          # 4 stratégies de trading
```

---

## 📊 Les 4 Stratégies

### 1. Breakout Momentum (ton document PDF)
- Filtre marché : SPY/QQQ au-dessus EMA 8/21/50
- Action au-dessus EMA 21/50, ADR > 3%
- Consolidation + compression des prix (volume décroissant)
- Cassure de résistance avec volume ≥ 1.5× la moyenne
- Stop Loss : plus bas de la bougie de breakout
- Scale Out : 25% → 25% → 50% avec trailing stop EMA 8/21

### 2. CANSLIM (William O'Neil)
- C : EPS growth > 25% QoQ
- A : Annual earnings trend positif
- N : Nouveau plus haut 52 semaines
- S : Volume institutionnel croissant
- L : Surperformance vs S&P 500
- I : Volume moyen en hausse
- M : Marché en uptrend

### 3. Trend Following — Turtle Traders
- Entrée S1 : Cassure du plus haut des 20 jours
- Entrée S2 : Cassure du plus haut des 55 jours
- Sortie S1 : Plus bas des 10 jours
- Sortie S2 : Plus bas des 20 jours
- Position sizing basé sur l'ATR (N)
- Pyramidage : jusqu'à 4 unités par marché

### 4. Mean Reversion (Bollinger + RSI)
- Signal Long : prix < bande inférieure (-2σ) ET RSI < 30
- Signal Short : prix > bande supérieure (+2σ) ET RSI > 70
- Target : retour à la SMA 20 (bande centrale)
- Filtre : ADX < 25 (marché en range uniquement)
- Stop : 1.5× ATR sous l'entrée

---

## ⚙️ Configuration (`core/config.py`)

Modifier les paramètres clés :

```python
risk_per_trade   = 0.01    # 1% du capital risqué par trade
max_positions    = 8       # Maximum de positions simultanées
min_adr_pct      = 3.0    # ADR minimum 3%
tp1_pct          = 0.10   # TP1 à +10%
tp2_pct          = 0.20   # TP2 à +20%
```

Ajouter/modifier la watchlist :
```python
@property
def watchlist(self):
    return ['NVDA', 'AMD', 'MSFT', ...]  # Ajouter vos tickers
```

---

## 🛡️ Gestion du Risque

| Paramètre | Valeur | Description |
|---|---|---|
| Risque/trade | 1% | Maximum risqué par position |
| Max positions | 8 | Limite de diversification |
| Max secteur | 30% | Exposition max par secteur |
| Stop Loss | Candle low | Plus bas de la bougie breakout |
| TP1 | +10% | Vendre 25% → SL au break even |
| TP2 | +20% | Vendre 25% supplémentaires |
| Trailing | EMA 8/21 | Pour les 50% restants |
| Drawdown journalier | -3% | Pause automatique jusqu'au lendemain |
| Drawdown hebdomadaire | -6% | Pause automatique jusqu'à la semaine prochaine |
| Pertes consécutives | 5 | Pause manuelle requise après revue |
| Slippage supposé | 0.05% | Réduit la taille de position calculée |
| Filtre news | ±30 min | Bloque l'ouverture autour des NFP/FOMC/CPI |

---

## 📝 Dépendances

- **yfinance** : Données de marché gratuites (Yahoo Finance)
- **pandas** : Traitement des données
- **numpy** : Calculs numériques

Pas de clé API nécessaire.

---

## 🟦 Trading MT5 avec Deriv

1. Créez un compte DÉMO MT5 sur deriv.com (Trader's Hub → CFDs → Deriv MT5) et notez login, mot de passe MT5 et serveur.
2. Copiez `.env.example` en `.env` et remplissez `DERIV_DEMO_*`.
3. Installez MT5 (Windows), connectez-vous une fois manuellement, puis : `pip install MetaTrader5 -r requirements.txt`
4. Diagnostic sans aucun ordre : `python live_trading.py --broker deriv --demo --check`
5. Lancement démo : `python live_trading.py --broker deriv --demo`

Les noms de symboles Deriv (ex. DE40 → « Germany 40 ») sont résolus automatiquement ;
les symboles absents de votre compte sont ignorés avec un avertissement.
Indices synthétiques disponibles (V75, BOOM1000, CRASH1000, STEP…) : voir `core/brokers/deriv_config.py`
(ajoutez-les dans `LIVE_TRADING_CONFIG["symboles"]` ; mettez `trading_hours` à `None` pour le 24/7).

### Backtest sur l'historique réel du broker (MT5 ouvert et connecté)
```
python backtest_mt5.py --broker deriv --symbols V75 V100 V50 --timeframe H1 --bars 5000 --step 2
```
Produit `backtest_report_deriv.html` (à ouvrir dans Chrome) et `backtest_trades_deriv.csv`.
`--step 2` accélère (un signal évalué toutes les 2 bougies). Le nombre de bougies disponibles dépend de
MT5 : Outils → Options → Graphiques → « Nombre max de barres dans l'historique ».

### Suivi live dans Chrome
Le bot réécrit `dashboard_live_deriv.html` à chaque cycle (rechargement auto 15 s).

### Mini App Telegram (lecture seule)
Le bot écrit aussi `dashboard_live_<broker>.json`, ignoré par Git. La Mini App
affiche le solde, l'équité, les positions et les derniers trades. L'API vérifie
la signature `initData` de Telegram, limite l'accès à `TELEGRAM_CHAT_ID` et aux
identifiants supplémentaires de `TELEGRAM_OWNER_IDS` et
`TELEGRAM_MINIAPP_USER_IDS`, puis demande un PIN numérique à 6 chiffres.
Le premier propriétaire autorisé le crée dans la Mini App ; le PIN peut ensuite
être changé depuis le tableau après saisie du PIN actuel. Seul son hash salé est
conservé dans `.telegram_miniapp_pin.json`, qui est ignoré par Git. Après cinq
erreurs de PIN, les essais sont bloqués 15 minutes pour ce compte Telegram.
Cette autorisation supplémentaire ne donne pas accès aux commandes du bot.
La Mini App ne permet pas de passer ou fermer des ordres.
L'aperçu local sur `http://127.0.0.1:8766` montre les données en lecture seule ;
sur l'URL publique, l'API continue d'exiger une signature Telegram valide.
L'aperçu local demande lui aussi le PIN.
L'interface inclut le PnL du jour, une courbe cumulée filtrable, les niveaux
des positions, les limites de risque et un avertissement quand les données
deviennent anciennes.
Elle propose aussi les filtres de trades (symbole, résultat, période, recherche),
le détail des clôtures, l'export CSV des trades filtrés, l'état bot/MT5/API,
les jauges des limites de risque et le journal d'activité. Les jauges de risque
utilisent les nouveaux champs de l'instantané et nécessitent donc le redémarrage
du bot en mode démo. Le serveur Mini App relit le journal CSV pour fournir les
détails des clôtures même avec un instantané plus ancien ; redémarrez-le après
une mise à jour du code. Les informations manquantes restent signalées comme
indisponibles au lieu d'être estimées.

Pour un lancement local en une fois sous Windows, double-cliquez sur
`lancer_miniapp_demo.bat`. Il ouvre le bot Deriv en mode démo et le serveur
local dans deux fenêtres séparées.

Pour essayer l'application depuis Telegram sans VPS, installez le client
Cloudflare Tunnel gratuit (`winget install --id Cloudflare.cloudflared -e`),
puis double-cliquez sur `lancer_cloudflare_demo.bat`. Le tunnel Quick Tunnel
fournit une URL HTTPS temporaire `trycloudflare.com`, sans domaine acheté.
Copiez l'URL affichée dans `.env` sous `TELEGRAM_WEBAPP_URL=...`, puis lancez
le bot avec `python live_trading.py --broker deriv --demo`. Le bot configure
le bouton Telegram au démarrage. Laissez ouvertes les fenêtres du serveur,
du tunnel et du bot ; l'URL temporaire change au prochain tunnel et le bot
devra être redémarré avec la nouvelle URL.

Le tunnel relaie les requêtes HTTPS via Cloudflare ; l'opérateur peut donc
observer des métadonnées de connexion et le trafic transite par son
infrastructure. Pour autoriser une deuxième personne comme copropriétaire,
ajoutez son ID Telegram numérique à `TELEGRAM_OWNER_IDS` dans `.env`.
Exemple de configuration locale (remplacez l'ID entre chevrons) :
```env
TELEGRAM_OWNER_IDS=<ID_TELEGRAM_DE_LA_DEUXIEME_PERSONNE>
```
Le PIN se crée dans l'écran d'accès de la Mini App et peut se changer après
déverrouillage depuis le tableau. `TELEGRAM_OWNER_IDS` ajoute un copropriétaire
aux commandes Telegram et à la Mini App. Les commandes des deux comptes sont
traitées par une seule boucle,
agissent sur le même bot et reçoivent leurs réponses dans le chat qui les a
envoyées ; les alertes du bot sont envoyées aux deux propriétaires. La personne
doit d'abord ouvrir le bot et appuyer sur `/start`.
Redémarrez le bot pour appliquer la liste des copropriétaires et actualiser le
bouton ; redémarrez aussi le serveur Mini App après sa configuration. Les
identifiants mis seulement dans `TELEGRAM_MINIAPP_USER_IDS` restent limités à
la Mini App en lecture seule. N'ajoutez jamais `.env` au dépôt et ne publiez
pas directement le port local `8766`.
Si `cloudflared` signale des délais d'attente QUIC (« no recent network
activity »), le lanceur force HTTP/2 sur TCP avec `--protocol http2`, ce qui
peut fonctionner sur les réseaux qui bloquent QUIC/UDP.

Pour préparer le serveur local :

1. Configurez `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans `.env`.
2. Lancez le bot live ; il génère le fichier JSON à chaque cycle.
3. Dans une autre fenêtre, lancez `python serve_telegram_miniapp.py --broker deriv`.
   Le serveur écoute uniquement sur `127.0.0.1:8766` par défaut.
4. Pour ouvrir l'application dans Telegram, il faut un nom de domaine public
   avec HTTPS et un reverse proxy sécurisé vers le serveur local. Ne publiez
   pas directement le port HTTP sur Internet et ne transmettez pas le port du
   PC sur un réseau public.
5. Une fois l'URL HTTPS disponible, ajoutez `TELEGRAM_WEBAPP_URL=https://...`
   dans `.env`, puis redémarrez le bot. Il configurera le bouton « Tableau de
   bord » dans le menu Telegram privé autorisé.

Sans adresse HTTPS publique, le code peut être préparé et le serveur local
lancé, mais Telegram ne peut pas ouvrir la Mini App. Le serveur et le bot
doivent tous deux fonctionner pour afficher les données en direct.

### Voir le dashboard sur un téléphone (même Wi-Fi)
Dans une 2e fenêtre noire : `python serve_dashboard.py` puis ouvrez l'adresse affichée dans Chrome sur le téléphone.
Seule la page du dashboard est partagée (jamais le `.env`), protégée par une clé.

### Pilotage complet depuis Telegram
Avec `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID` dans le `.env`, le bot répond à vos commandes :
`/statut /positions /trades /bilan /activite /symboles /pause /reprise /fermer TICKET /toutfermer /exclure SYMBOLE /inclure SYMBOLE /stop /aide`.
Seul votre chat privé est autorisé. Les anciens messages en attente au démarrage sont ignorés.
Ne lancez pas `telegram_control_bot.py` en même temps avec le même bot Telegram.
#   B O T - T R A D I N G - B E S T  
 #   B O T - T R A D I N G - B E S T  
 