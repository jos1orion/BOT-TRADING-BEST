"""
╔══════════════════════════════════════════════════════════════════╗
║  CONNECTEUR METATRADER 5                                        ║
║  Compatible : XM Global, Axiom, et tous brokers MT5            ║
║                                                                  ║
║  ⚠️  AVERTISSEMENTS CRITIQUES                                   ║
║  ────────────────────────────────────────────────────────────   ║
║  1. Commencez OBLIGATOIREMENT sur un compte DÉMO               ║
║  2. Un bug dans le code peut entraîner des pertes réelles       ║
║  3. Validez 50+ trades en démo avant de passer au réel         ║
║  4. Ne jamais risquer plus que ce que vous pouvez perdre       ║
║  5. Le trading automatisé ne garantit aucun résultat           ║
╚══════════════════════════════════════════════════════════════════╝

PRÉREQUIS :
───────────
1. Installer MetaTrader 5 sur votre PC (Windows uniquement pour le trading live)
   → https://www.xm.com/mt5  (XM Global)
   → https://www.axiom.com   (Axiom)

2. Ouvrir un compte DÉMO sur le broker choisi

3. Installer la bibliothèque Python :
   pip install MetaTrader5 pandas

4. MT5 doit être ouvert et connecté quand le bot tourne

NOTE SUR LA COMPATIBILITÉ :
────────────────────────────
- MetaTrader5 Python ne fonctionne que sur Windows
- Sur Mac/Linux : utiliser Wine ou une VM Windows
- Alternative cross-platform : voir la section Docker à la fin
"""

import math
import time
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# ── Import MT5 avec gestion d'erreur ──────────────────────────────
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("⚠️  MetaTrader5 non installé. Lancez : pip install MetaTrader5")
    print("   Mode simulation activé automatiquement.\n")


class OrderType(Enum):
    BUY        = "BUY"
    SELL       = "SELL"
    BUY_LIMIT  = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"
    BUY_STOP   = "BUY_STOP"
    SELL_STOP  = "SELL_STOP"


class AccountMode(Enum):
    DEMO = "DEMO"    # ← Toujours commencer ici
    REAL = "REAL"    # ← Uniquement après validation complète


@dataclass
class MT5Order:
    """Représente un ordre envoyé à MT5."""
    symbol:        str
    order_type:    OrderType
    volume:        float          # En lots (0.01 = micro lot)
    price:         float          # 0 = prix marché
    stop_loss:     float = 0.0
    take_profit:   float = 0.0
    deviation:     int   = 20     # Slippage max en points
    magic:         int   = 234000 # ID unique du bot
    comment:       str   = "TradingBot"
    ticket:        int   = 0      # Rempli après exécution
    position_id:   int   = 0      # Identifiant de la position ouverte (sert au suivi des clôtures)
    filled_price:  float = 0.0
    status:        str   = "PENDING"
    error:         str   = ""


@dataclass
class MT5Position:
    """Position ouverte sur MT5."""
    ticket:        int
    symbol:        str
    type:          str
    volume:        float
    open_price:    float
    current_price: float
    stop_loss:     float
    take_profit:   float
    profit:        float
    open_time:     datetime
    comment:       str = ""


# ══════════════════════════════════════════════════════════════════
# CONNECTEUR PRINCIPAL
# ══════════════════════════════════════════════════════════════════

class MT5Connector:
    """
    Connecteur universel MetaTrader 5.
    Fonctionne avec XM Global, Axiom, et tous les brokers MT5.
    """

    def __init__(self, account_mode: AccountMode = AccountMode.DEMO,
                 simulation: bool = False):
        """
        Args:
            account_mode : DEMO (recommandé) ou REAL
            simulation   : True = aucun ordre réel envoyé (test du code)
        """
        self.mode        = account_mode
        self.simulation  = simulation
        self.connected   = False
        self.account_info: Dict = {}
        self._symbol_cache: Dict[str, Optional[str]] = {}

        if account_mode == AccountMode.REAL and not simulation:
            self._print_real_warning()

    def _print_real_warning(self):
        print("\n" + "═" * 65)
        print("  ⚠️  COMPTE RÉEL DÉTECTÉ — LISEZ ATTENTIVEMENT")
        print("═" * 65)
        print("  Vous êtes sur le point de connecter le bot à un compte RÉEL.")
        print("  Le bot va exécuter de vrais ordres avec de l'argent réel.")
        print()
        print("  AVANT DE CONTINUER, CONFIRMEZ :")
        print("  ✅ Backtesté sur 50+ trades en démo")
        print("  ✅ Paper tradé en live pendant minimum 2 semaines")
        print("  ✅ Compris et accepté le risque de perte totale")
        print("  ✅ Capital alloué = argent que vous POUVEZ PERDRE")
        print()
        confirmation = input("  Tapez 'JE COMPRENDS LE RISQUE' pour continuer : ")
        if confirmation.strip() != "JE COMPRENDS LE RISQUE":
            raise RuntimeError("Connexion annulée. Utilisez le mode DEMO.")
        print("═" * 65 + "\n")

    # ────────────────────────────────────────────────────────────
    # CONNEXION
    # ────────────────────────────────────────────────────────────

    def connect(self, login: int, password: str, server: str,
                mt5_path: Optional[str] = None) -> bool:
        """
        Se connecte à MetaTrader 5.

        Args:
            login    : Numéro de compte MT5 (ex: 12345678)
            password : Mot de passe du compte
            server   : Nom du serveur broker (voir tableau ci-dessous)
            mt5_path : Chemin vers terminal64.exe (optionnel)

        SERVEURS COURANTS :
        ───────────────────
        XM Global Demo  : "XMGlobal-Demo 3"
        XM Global Real  : "XMGlobal-Real 11" (varie selon région)
        Axiom Demo      : "Axiom-Demo"
        Axiom Real      : "Axiom-Real"

        TROUVER VOTRE SERVEUR :
        ───────────────────────
        MT5 → Fichier → Ouvrir un compte → chercher votre broker
        ou regarder dans MT5 : Outils → Options → Serveur
        """
        if self.simulation:
            print(f"  [SIMULATION] Connexion simulée — login {login} sur {server}")
            self.connected = True
            self.account_info = {
                'login':    login,
                'server':   server,
                'balance':  10000.0,
                'equity':   10000.0,
                'margin':   0.0,
                'currency': 'USD',
                'name':     'Simulation Account',
                'mode':     self.mode.value,
            }
            return True

        if not MT5_AVAILABLE:
            logger.error("MetaTrader5 non installé. pip install MetaTrader5")
            return False

        try:
            # Initialiser MT5
            init_kwargs = {}
            if mt5_path:
                init_kwargs['path'] = mt5_path

            if not mt5.initialize(**init_kwargs):
                logger.error(f"Échec initialisation MT5 : {mt5.last_error()}")
                return False

            # Se connecter au compte
            authorized = mt5.login(login, password=password, server=server)
            if not authorized:
                err = mt5.last_error()
                logger.error(f"Échec connexion MT5 compte {login} : {err}")
                mt5.shutdown()
                return False

            # Récupérer les infos du compte
            info = mt5.account_info()
            if info is None:
                logger.error("Impossible de récupérer les infos du compte")
                return False

            self.connected = True
            self.account_info = {
                'login':    info.login,
                'server':   info.server,
                'balance':  info.balance,
                'equity':   info.equity,
                'margin':   info.margin,
                'currency': info.currency,
                'name':     info.name,
                'leverage': info.leverage,
                'mode':     'DEMO' if info.trade_mode == 0 else 'REAL',
            }

            self._print_connection_success()
            return True

        except Exception as e:
            logger.error(f"Erreur de connexion MT5 : {e}")
            return False

    def _print_connection_success(self):
        info = self.account_info
        print(f"\n  ✅ Connecté à MetaTrader 5")
        print(f"  {'─' * 45}")
        print(f"  Compte    : {info['login']}")
        print(f"  Nom       : {info.get('name', 'N/A')}")
        print(f"  Serveur   : {info['server']}")
        print(f"  Balance   : {info['balance']:,.2f} {info['currency']}")
        print(f"  Equity    : {info['equity']:,.2f} {info['currency']}")
        print(f"  Mode      : {'🟡 DÉMO' if info['mode'] == 'DEMO' else '🔴 RÉEL'}")
        if 'leverage' in info:
            print(f"  Levier    : 1:{info['leverage']}")
        print()

    def disconnect(self):
        """Ferme la connexion MT5."""
        if MT5_AVAILABLE and self.connected and not self.simulation:
            mt5.shutdown()
        self.connected = False
        logger.info("Déconnecté de MT5")

    # ────────────────────────────────────────────────────────────
    # RÉSOLUTION DES SYMBOLES + PARAMÈTRES D'EXÉCUTION (multi-brokers)
    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _norm(name: str) -> str:
        return "".join(ch for ch in name.lower() if ch.isalnum())

    def resolve_symbol(self, wanted: str, aliases: Optional[List[str]] = None) -> Optional[str]:
        """
        Trouve le nom EXACT d'un symbole chez le broker connecté.

        Les brokers nomment parfois différemment (DE40 / Germany 40 / GER40),
        ou ajoutent un suffixe (EURUSDm, EURUSD.r). On teste dans l'ordre :
        le nom demandé, ses alias, puis une correspondance "commence par".
        Retourne None si rien ne correspond.
        """
        if wanted in self._symbol_cache:
            return self._symbol_cache[wanted]

        if self.simulation:
            return wanted
        if not MT5_AVAILABLE or not self.connected:
            return None

        candidates = [wanted] + [a for a in (aliases or []) if a != wanted]
        found = None
        try:
            all_symbols = mt5.symbols_get() or []
            by_norm = {self._norm(sy.name): sy.name for sy in all_symbols}
            # 1) correspondance exacte (normalisée)
            for c in candidates:
                if self._norm(c) in by_norm:
                    found = by_norm[self._norm(c)]
                    break
            # 2) suffixe/préfixe broker (EURUSDm, EURUSD.r…) — le plus court gagne
            if found is None:
                for c in candidates:
                    nc = self._norm(c)
                    if len(nc) < 4:
                        continue
                    matches = [n for k, n in by_norm.items() if k.startswith(nc)]
                    if matches:
                        found = min(matches, key=len)
                        break
            if found is not None:
                mt5.symbol_select(found, True)   # l'ajoute au Market Watch
        except Exception as e:
            logger.error(f"Erreur resolve_symbol {wanted} : {e}")

        self._symbol_cache[wanted] = found
        return found

    @staticmethod
    def _filling_mode(symbol: str):
        """
        Mode de remplissage accepté par le symbole. Beaucoup de brokers
        (Deriv inclus) rejettent IOC sur certains instruments
        ("Unsupported filling mode", retcode 10030) → on lit ce que le
        symbole autorise réellement : bit 1 = FOK, bit 2 = IOC, sinon RETURN.
        """
        info = mt5.symbol_info(symbol)
        mask = getattr(info, "filling_mode", 0) if info else 0
        if mask & 2:
            return mt5.ORDER_FILLING_IOC
        if mask & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    @staticmethod
    def _round_volume(volume: float, info) -> float:
        """Arrondit un volume au pas du symbole (0.01, 0.001, 0.1…) et le borne."""
        step = info.volume_step or 0.01
        vmin, vmax = info.volume_min, info.volume_max
        volume = max(vmin, min(volume, vmax))
        volume = round(volume / step) * step
        decimals = max(0, len(f"{step:.8f}".rstrip("0").split(".")[1])) if "." in f"{step:.8f}" else 0
        return round(max(vmin, min(volume, vmax)), decimals)

    @staticmethod
    def _enforce_stops_level(symbol: str, is_buy: bool, price: float,
                             sl: float, tp: float):
        """
        Respecte la distance minimale SL/TP imposée par le broker
        (trade_stops_level) pour éviter le rejet "Invalid stops" (10016).
        """
        info = mt5.symbol_info(symbol)
        if info is None:
            return sl, tp
        min_dist = (info.trade_stops_level + 1) * info.point
        digits = info.digits
        if is_buy:
            if sl and price - sl < min_dist:
                sl = price - min_dist
            if tp and tp - price < min_dist:
                tp = price + min_dist
        else:
            if sl and sl - price < min_dist:
                sl = price + min_dist
            if tp and price - tp < min_dist:
                tp = price - min_dist
        return (round(sl, digits) if sl else 0.0), (round(tp, digits) if tp else 0.0)

    def is_symbol_tradable(self, symbol: str) -> bool:
        """False si le broker n'autorise pas le trading du symbole (marché fermé / désactivé)."""
        if self.simulation:
            return True
        if not MT5_AVAILABLE or not self.connected:
            return False
        try:
            info = mt5.symbol_info(symbol)
            if info is None or info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
                return False
            tick = mt5.symbol_info_tick(symbol)
            return tick is not None and tick.bid > 0 and tick.ask > 0
        except Exception:
            return False

    # ────────────────────────────────────────────────────────────
    # DONNÉES DE MARCHÉ
    # ────────────────────────────────────────────────────────────

    def get_price(self, symbol: str) -> Optional[Dict]:
        """
        Récupère le prix actuel bid/ask d'un symbole.

        Symboles courants XM/Axiom :
        - Forex  : EURUSD, GBPUSD, USDJPY, GBPJPY
        - Indices: DE40 (DAX), US500 (S&P500), US100 (Nasdaq)
        - Metaux : XAUUSD (Or), XAGUSD (Argent)
        - Crypto : BTCUSD, ETHUSD
        """
        if self.simulation:
            import random
            base = 1.1000 if 'USD' in symbol else 100.0
            spread = base * 0.0002
            bid = base + random.uniform(-0.005, 0.005)
            return {
                'symbol': symbol,
                'bid':    round(bid, 5),
                'ask':    round(bid + spread, 5),
                'spread': round(spread * 10000, 1),
                'time':   datetime.now(),
            }

        if not MT5_AVAILABLE or not self.connected:
            return None

        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                # Essayer d'activer le symbole
                mt5.symbol_select(symbol, True)
                time.sleep(0.1)
                tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
            info = mt5.symbol_info(symbol)
            point = info.point if info and info.point else 0.0001
            return {
                'symbol': symbol,
                'bid':    tick.bid,
                'ask':    tick.ask,
                'spread': round((tick.ask - tick.bid) / point, 1),   # en points
                'time':   datetime.fromtimestamp(tick.time),
            }
        except Exception as e:
            logger.error(f"Erreur get_price {symbol} : {e}")
            return None

    def get_ohlcv_mt5(self, symbol: str, timeframe_str: str = 'H1',
                       count: int = 500) -> Optional[object]:
        """
        Récupère les données OHLCV directement depuis MT5.

        Timeframes disponibles :
        M1, M5, M15, M30 (minutes)
        H1, H4             (heures)
        D1, W1, MN         (day/week/month)
        """
        TIMEFRAME_MAP = {
            'M1': 1,   'M5': 5,   'M15': 15, 'M30': 30,
            'H1': 16385, 'H4': 16388,
            'D1': 16408, 'W1': 32769, 'MN': 49153
        }

        if self.simulation:
            return None  # Utiliser yfinance en simulation

        if not MT5_AVAILABLE or not self.connected:
            return None

        try:
            import pandas as pd
            tf = TIMEFRAME_MAP.get(timeframe_str.upper(), 16385)
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
            if rates is None or len(rates) == 0:
                return None

            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            df = df.rename(columns={
                'time': 'Date', 'open': 'Open', 'high': 'High',
                'low': 'Low', 'close': 'Close',
                'tick_volume': 'Volume'
            })
            df = df.set_index('Date')
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        except Exception as e:
            logger.error(f"Erreur get_ohlcv_mt5 {symbol} : {e}")
            return None

    # ────────────────────────────────────────────────────────────
    # CALCUL DU VOLUME (POSITION SIZING)
    # ────────────────────────────────────────────────────────────

    def calculate_lots(self, symbol: str, entry: float,
                        stop_loss: float,
                        risk_pct: float = 0.01,
                        slippage_pct: float = 0.05) -> float:
        """
        Calcule la taille de position en lots selon le risque défini.

        Formule :
        lots = (balance × risk%) / (stop_distance_pips × valeur_pip)

        Exemple XM Gold (XAUUSD) :
        Balance = 10 000$, risk = 1%, SL = 10$
        → lots = 100 / (10 × 10) = 1.0 lot

        Le slippage estimé est ajouté à la distance de stop afin de
        réduire le volume calculé. Le volume est arrondi vers le bas.

        Retourne 0 si le volume minimum du broker dépasserait le risque cible.
        """
        # Rafraîchir le solde et la marge libre MT5 en direct si disponible
        balance = self.account_info.get('balance', 10000)
        free_margin = self.account_info.get('free_margin', balance)
        if MT5_AVAILABLE and self.connected and not self.simulation:
            try:
                acc = mt5.account_info()
                if acc is None:
                    logger.error(f"{symbol}: Solde MT5 indisponible — ordre ignoré")
                    return 0.0
                balance = acc.balance
                free_margin = acc.margin_free
            except Exception as e:
                logger.error(f"{symbol}: Erreur de lecture du compte MT5: {e}")
                return 0.0

        if (
            balance <= 0 or risk_pct <= 0 or slippage_pct < 0
            or not all(math.isfinite(value) for value in (balance, risk_pct, slippage_pct, entry, stop_loss))
        ):
            logger.error(f"{symbol}: Solde, entrée, stop-loss ou risque invalide pour calculer le volume")
            return 0.0

        risk_amount = balance * risk_pct
        raw_stop_distance = abs(entry - stop_loss)

        if raw_stop_distance == 0 or entry <= 0:
            logger.warning(f"{symbol}: Distance de stop ou prix d'entrée invalide — ordre ignoré")
            return 0.0

        # Une distance de risque plus large réduit le volume et tient compte
        # d'un prix d'exécution potentiellement moins favorable.
        slippage_buffer = entry * (slippage_pct / 100)
        stop_distance = raw_stop_distance + slippage_buffer

        if self.simulation:
            # Calcul simplifié en simulation
            lot_risk  = stop_distance * 100000
            if lot_risk <= 0:
                return 0.0
            lots = risk_amount / lot_risk
            lots = math.floor(min(lots, 10.0) * 100) / 100
            return lots if lots >= 0.01 else 0.0

        if not MT5_AVAILABLE:
            logger.error(f"{symbol}: MetaTrader5 indisponible — aucun volume calculé")
            return 0.0

        try:
            sym_info = mt5.symbol_info(symbol)
            if sym_info is None:
                logger.error(f"{symbol}: Informations symbole MT5 indisponibles — ordre ignoré")
                return 0.0

            tick_value = sym_info.trade_tick_value
            tick_size  = sym_info.trade_tick_size

            if not tick_size or tick_size <= 0 or not tick_value or tick_value <= 0:
                logger.error(f"{symbol}: Valeur de tick MT5 invalide — ordre ignoré")
                return 0.0

            monetary_risk_per_lot = (stop_distance / tick_size) * tick_value
            if monetary_risk_per_lot <= 0:
                logger.error(f"{symbol}: Risque monétaire par lot invalide — ordre ignoré")
                return 0.0

            theoretical_lots = risk_amount / monetary_risk_per_lot

            # Respecter les limites du broker
            lot_min  = sym_info.volume_min
            lot_max  = sym_info.volume_max
            lot_step = sym_info.volume_step

            if lot_min <= 0 or lot_step <= 0 or lot_max < lot_min:
                logger.error(f"{symbol}: Limites de volume MT5 invalides — ordre ignoré")
                return 0.0

            action = mt5.ORDER_TYPE_BUY if entry >= stop_loss else mt5.ORDER_TYPE_SELL

            if theoretical_lots < lot_min:
                logger.warning(
                    f"{symbol}: Le lot minimum ({lot_min}) dépasserait le risque cible "
                    f"({risk_pct * 100:.2f}%) — ordre ignoré"
                )
                return 0.0

            lots = min(lot_max, math.floor(theoretical_lots / lot_step) * lot_step)
            decimals = max(
                0,
                len(f"{lot_step:.8f}".rstrip("0").split(".")[1])
                if "." in f"{lot_step:.8f}" else 0,
            )
            lots = round(lots, decimals)
            if lots < lot_min:
                logger.warning(
                    f"{symbol}: Le volume ajusté au pas minimum dépasserait le risque cible — ordre ignoré"
                )
                return 0.0

            # Vérifier la marge pour le volume calculé
            try:
                req_margin = mt5.order_calc_margin(action, symbol, lots, entry)
                if req_margin is not None and free_margin > 0 and req_margin > free_margin * 0.75:
                    req_margin_min = mt5.order_calc_margin(action, symbol, lot_min, entry)
                    if req_margin_min is not None and req_margin_min <= free_margin * 0.70:
                        logger.info(f"{symbol}: Marge serrée pour {lots} lots -> ajusté à {lot_min}")
                        return lot_min
                    else:
                        logger.warning(f"{symbol}: Marge insuffisante ({free_margin:.2f}$) pour ouvrir {lots} lots")
                        return 0.0
                elif req_margin is None:
                    logger.warning(f"{symbol}: Vérification de marge MT5 indisponible")
            except Exception as e:
                logger.warning(f"{symbol}: Échec de la vérification de marge MT5: {e}")

            return lots

        except Exception as e:
            logger.error(f"Erreur calcul lots {symbol} : {e}")
            return 0.0

    def calculate_position_risk(self, symbol: str, volume: float, entry: float,
                                stop_loss: float, slippage_pct: float = 0.05) -> Optional[float]:
        """Estime la perte monétaire au stop, slippage inclus; None si inconnue."""
        if (
            self.simulation or not MT5_AVAILABLE or not self.connected
            or volume <= 0 or entry <= 0 or stop_loss <= 0
            or slippage_pct < 0
            or not all(math.isfinite(value) for value in (volume, entry, stop_loss, slippage_pct))
        ):
            return None

        try:
            sym_info = mt5.symbol_info(symbol)
            if sym_info is None:
                logger.error(f"{symbol}: Informations symbole indisponibles pour estimer le risque ouvert")
                return None

            tick_value = sym_info.trade_tick_value
            tick_size = sym_info.trade_tick_size
            if not tick_value or tick_value <= 0 or not tick_size or tick_size <= 0:
                logger.error(f"{symbol}: Valeur de tick invalide pour estimer le risque ouvert")
                return None

            stop_distance = abs(entry - stop_loss) + entry * (slippage_pct / 100)
            risk_per_lot = (stop_distance / tick_size) * tick_value
            risk = volume * risk_per_lot
            return risk if math.isfinite(risk) else None
        except Exception as e:
            logger.error(f"Erreur estimation risque ouvert {symbol}: {e}")
            return None

    # ────────────────────────────────────────────────────────────
    # PASSAGE D'ORDRES
    # ────────────────────────────────────────────────────────────

    def send_market_order(self, symbol: str, order_type: OrderType,
                           volume: float, stop_loss: float = 0.0,
                           take_profit: float = 0.0,
                           comment: str = "TradingBot") -> MT5Order:
        """
        Envoie un ordre au marché.

        ⚠️  VÉRIFIER AVANT D'APPELER CETTE FONCTION :
        - Vous êtes en mode DÉMO si c'est votre premier test
        - Le signal est validé par votre stratégie
        - Le risk management est respecté
        """
        order = MT5Order(
            symbol=symbol, order_type=order_type,
            volume=volume, price=0,
            stop_loss=stop_loss, take_profit=take_profit,
            comment=comment
        )

        if self.simulation:
            price_info = self.get_price(symbol)
            order.filled_price = price_info['ask'] if order_type == OrderType.BUY \
                                  else price_info['bid']
            order.ticket = int(time.time())
            order.status = "FILLED (SIMULATION)"
            print(f"  [SIM] {order_type.value} {volume} {symbol} "
                  f"@ {order.filled_price:.5f} | SL {stop_loss:.5f} | TP {take_profit:.5f}")
            return order

        if not MT5_AVAILABLE or not self.connected:
            order.status = "ERROR"
            order.error  = "Non connecté à MT5"
            return order

        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                order.status = "ERROR"
                order.error  = f"Symbole {symbol} non disponible"
                return order

            if order_type == OrderType.BUY:
                mt5_order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask
            else:
                mt5_order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid

            sym_info = mt5.symbol_info(symbol)
            if sym_info is not None:
                volume = self._round_volume(volume, sym_info)
            stop_loss, take_profit = self._enforce_stops_level(
                symbol, order_type == OrderType.BUY, price, stop_loss, take_profit)

            request = {
                "action":   mt5.TRADE_ACTION_DEAL,
                "symbol":   symbol,
                "volume":   float(volume),
                "type":     mt5_order_type,
                "price":    price,
                "sl":       float(stop_loss),
                "tp":       float(take_profit),
                "deviation": order.deviation,
                "magic":    order.magic,
                "comment":  comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._filling_mode(symbol),
            }

            result = mt5.order_send(request)

            if result is None:
                order.status = "ERROR"
                order.error  = str(mt5.last_error())
            elif result.retcode == mt5.TRADE_RETCODE_DONE:
                order.ticket       = result.order
                order.position_id  = self._position_id_from_result(result)
                order.filled_price = result.price
                order.status       = "FILLED"
                print(f"  ✅ Ordre exécuté : {order_type.value} {volume} {symbol} "
                      f"@ {result.price:.5f} | Ticket #{result.order}")
            else:
                order.status = "ERROR"
                order.error  = f"Code {result.retcode} : {result.comment}"
                print(f"  ❌ Erreur ordre : {order.error}")

        except Exception as e:
            order.status = "ERROR"
            order.error  = str(e)
            logger.error(f"Erreur send_market_order : {e}")

        return order

    @staticmethod
    def _position_id_from_result(result) -> int:
        """Identifiant de la position créée par un ordre (≠ ticket d'ordre sur certains comptes)."""
        try:
            deal = getattr(result, "deal", 0)
            if deal:
                deals = mt5.history_deals_get(ticket=deal)
                if deals:
                    return int(deals[0].position_id)
        except Exception:
            pass
        return int(result.order)

    def get_closed_deal_for_position(self, position_id: int) -> Optional[Dict]:
        """
        Deal de clôture d'une position précise (PnL réel = profit + commission + swap),
        quelle que soit l'ancienneté de la clôture — plus fiable qu'une fenêtre de temps.
        """
        if self.simulation or not MT5_AVAILABLE or not self.connected:
            return None
        REASONS = {4: "SL", 5: "TP", 6: "Stop out", 0: "Manuel", 1: "Mobile", 2: "Web", 3: "Bot"}
        try:
            deals = mt5.history_deals_get(position=position_id)
            for d in (deals or []):
                if getattr(d, "entry", None) == 1:      # DEAL_ENTRY_OUT
                    return {
                        'ticket': d.ticket, 'position_id': d.position_id, 'symbol': d.symbol,
                        'volume': d.volume, 'price': d.price,
                        'profit': d.profit + getattr(d, "commission", 0.0) + getattr(d, "swap", 0.0),
                        'time': datetime.fromtimestamp(d.time), 'comment': d.comment,
                        'reason': REASONS.get(getattr(d, "reason", -1), "Broker"),
                    }
        except Exception as e:
            logger.error(f"Erreur get_closed_deal_for_position #{position_id} : {e}")
        return None

    def close_position(self, ticket: int,
                        symbol: str, volume: float,
                        order_type: str) -> bool:
        """Ferme une position ouverte par son ticket."""
        if self.simulation:
            print(f"  [SIM] Clôture position #{ticket} — {volume} {symbol}")
            return True

        if not MT5_AVAILABLE or not self.connected:
            return False

        try:
            # La direction de clôture est inverse à l'ouverture
            if order_type == 'buy':
                close_type = mt5.ORDER_TYPE_SELL
                price      = mt5.symbol_info_tick(symbol).bid
            else:
                close_type = mt5.ORDER_TYPE_BUY
                price      = mt5.symbol_info_tick(symbol).ask

            request = {
                "action":   mt5.TRADE_ACTION_DEAL,
                "symbol":   symbol,
                "volume":   float(volume),
                "type":     close_type,
                "position": ticket,
                "price":    price,
                "deviation": 20,
                "magic":    234000,
                "comment":  "TradingBot Close",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._filling_mode(symbol),
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"  ✅ Position #{ticket} clôturée @ {result.price:.5f}")
                return True
            else:
                error = result.comment if result else str(mt5.last_error())
                print(f"  ❌ Échec clôture #{ticket} : {error}")
                return False

        except Exception as e:
            logger.error(f"Erreur close_position #{ticket} : {e}")
            return False

    def modify_sl_tp(self, ticket: int, new_sl: float,
                      new_tp: float = 0.0) -> bool:
        """Modifie le Stop Loss et/ou Take Profit d'une position."""
        if self.simulation:
            print(f"  [SIM] Modif SL/TP position #{ticket} → SL {new_sl:.5f}")
            return True

        if not MT5_AVAILABLE or not self.connected:
            return False

        try:
            request = {
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl":       float(new_sl),
                "tp":       float(new_tp),
            }
            result = mt5.order_send(request)
            return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE
        except Exception as e:
            logger.error(f"Erreur modify_sl_tp #{ticket} : {e}")
            return False

    def get_recent_closed_deals(self, minutes_back: int = 15) -> List[Dict]:
        """
        Récupère les deals de clôture récents depuis l'historique MT5
        (mt5.history_deals_get), avec le PnL réel — nécessaire pour
        journaliser précisément les trades fermés côté broker (SL/TP
        touchés automatiquement) et alimenter le drawdown guard avec
        de vrais résultats plutôt qu'une estimation.

        Retourne une liste de dicts :
        [{'ticket', 'position_id', 'symbol', 'volume', 'price', 'profit',
          'time', 'comment'}, ...]
        """
        if self.simulation:
            return []

        if not MT5_AVAILABLE or not self.connected:
            return []

        try:
            date_from = datetime.now().timestamp() - minutes_back * 60
            date_to = datetime.now().timestamp() + 60
            deals = mt5.history_deals_get(datetime.fromtimestamp(date_from), datetime.fromtimestamp(date_to))
            if deals is None:
                return []

            result = []
            for d in deals:
                # entry == 1 signifie une sortie de position (DEAL_ENTRY_OUT)
                if getattr(d, 'entry', None) == 1:
                    result.append({
                        'ticket':      d.ticket,
                        'position_id': d.position_id,
                        'symbol':      d.symbol,
                        'volume':      d.volume,
                        'price':       d.price,
                        'profit':      d.profit,
                        'time':        datetime.fromtimestamp(d.time),
                        'comment':     d.comment,
                    })
            return result
        except Exception as e:
            logger.error(f"Erreur get_recent_closed_deals : {e}")
            return []

    # ────────────────────────────────────────────────────────────
    # MONITORING DES POSITIONS
    # ────────────────────────────────────────────────────────────

    def get_open_positions(self) -> List[MT5Position]:
        """Retourne toutes les positions ouvertes."""
        if self.simulation:
            return []

        if not MT5_AVAILABLE or not self.connected:
            return []

        try:
            positions = mt5.positions_get()
            if positions is None:
                return []

            result = []
            for p in positions:
                result.append(MT5Position(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    type='buy' if p.type == 0 else 'sell',
                    volume=p.volume,
                    open_price=p.price_open,
                    current_price=p.price_current,
                    stop_loss=p.sl,
                    take_profit=p.tp,
                    profit=p.profit,
                    open_time=datetime.fromtimestamp(p.time),
                    comment=p.comment,
                ))
            return result
        except Exception as e:
            logger.error(f"Erreur get_open_positions : {e}")
            return []

    def get_account_summary(self) -> Dict:
        """Résumé complet du compte."""
        if self.simulation:
            return self.account_info

        if not MT5_AVAILABLE or not self.connected:
            return {}

        try:
            info = mt5.account_info()
            if info is None:
                return {}
            return {
                'balance':    info.balance,
                'equity':     info.equity,
                'margin':     info.margin,
                'free_margin': info.margin_free,
                'profit':     info.profit,
                'mode':       'DEMO' if info.trade_mode == 0 else 'REAL',
            }
        except Exception as e:
            logger.error(f"Erreur get_account_summary : {e}")
            return {}

    def print_account_dashboard(self):
        """Affiche le tableau de bord du compte."""
        info = self.get_account_summary()
        positions = self.get_open_positions()

        print(f"\n╔══════════════════════════════════════════════════════════╗")
        print(f"║  TABLEAU DE BORD MT5 — {datetime.now().strftime('%d/%m/%Y %H:%M')}              ║")
        print(f"╚══════════════════════════════════════════════════════════╝")
        print(f"  Mode         : {'🟡 DÉMO' if info.get('mode') == 'DEMO' else '🔴 RÉEL'}")
        print(f"  Balance      : ${info.get('balance', 0):>12,.2f}")
        print(f"  Equity       : ${info.get('equity', 0):>12,.2f}")
        print(f"  Marge libre  : ${info.get('free_margin', 0):>12,.2f}")
        print(f"  Profit ouvert: ${info.get('profit', 0):>+12,.2f}")

        if positions:
            print(f"\n  📂 POSITIONS OUVERTES ({len(positions)})")
            print(f"  {'Ticket':<10} {'Symbole':<10} {'Type':<6} {'Vol':>6} "
                  f"{'Ouvert':>10} {'Actuel':>10} {'PnL':>10} {'SL':>10}")
            print("  " + "─" * 74)
            for p in positions:
                icon = '🟢' if p.profit >= 0 else '🔴'
                print(f"  {icon} #{p.ticket:<8} {p.symbol:<10} {p.type:<6} "
                      f"{p.volume:>6.2f} {p.open_price:>10.5f} "
                      f"{p.current_price:>10.5f} ${p.profit:>+9.2f} "
                      f"{p.stop_loss:>10.5f}")
