"""
╔══════════════════════════════════════════════════════════════════╗
║  STRATÉGIE — ENGLOBANTE HAUSSIÈRE (Bullish Engulfing)           ║
║                                                                  ║
║  Source : Vidéo challenge 30 min — trader 9 ans                 ║
║                                                                  ║
║  Concept : Une petite bougie baissière suivie d'une large       ║
║  bougie haussière dont le corps ENGLOBE entièrement le corps    ║
║  de la précédente. Signal de retournement à court terme.        ║
║                                                                  ║
║  Plus le nombre de bougies englobées est élevé, plus le        ║
║  signal est fort.                                               ║
║                                                                  ║
║  ⚠️  Backtestez toujours avant de trader en réel.              ║
╚══════════════════════════════════════════════════════════════════╝
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
import pandas as pd
import numpy as np
from core.indicators import Indicators as I
from core.config import Config


@dataclass
class EnglobanteSignal:
    """Signal complet de la stratégie Englobante Haussière."""
    ticker:          str
    strategy:        str    = "Englobante Haussière"
    variante:        str    = "isolée"
    direction:       Optional[str] = None
    strength:        float  = 0.0
    entry:           float  = 0.0
    entry_type:      str    = "clôture"   # clôture | 50pct | ouverture_suivante
    stop_loss:       float  = 0.0
    tp1:             float  = 0.0
    tp2:             float  = 0.0
    tp3:             float  = 0.0
    risk_reward:     float  = 0.0
    nb_bougies_englobees: int = 1
    checklist:       List[str] = field(default_factory=list)
    filtres_valides: List[str] = field(default_factory=list)
    filtres_invalides: List[str] = field(default_factory=list)
    avertissements:  List[str] = field(default_factory=list)
    reason:          str    = ""

    def __str__(self):
        if not self.direction:
            return f"[Englobante] {self.ticker} — Pas de signal"
        return (
            f"[Englobante {self.variante}] {self.ticker} {self.direction} "
            f"| Force {self.strength:.0f}/100 | {self.nb_bougies_englobees} bougie(s) englobée(s) "
            f"| Entrée {self.entry_type} @ ${self.entry:.2f} "
            f"| SL ${self.stop_loss:.2f} | TP1 ${self.tp1:.2f} | R/R {self.risk_reward:.1f}:1"
        )

    def print_checklist(self):
        """Affiche la checklist complète de validation."""
        print(f"\n  📋 CHECKLIST — {self.ticker} ({self.variante})")
        print("  " + "─" * 60)
        for item in self.checklist:
            print(f"  {item}")
        if self.filtres_invalides:
            print("\n  ❌ Filtres non validés :")
            for f in self.filtres_invalides:
                print(f"    {f}")
        if self.avertissements:
            print("\n  ⚠️  Avertissements :")
            for a in self.avertissements:
                print(f"    {a}")


class EnglobanteHaussiere:
    """
    ═══════════════════════════════════════════════════════════
    STRATÉGIE ENGLOBANTE HAUSSIÈRE — 5 VARIANTES
    ═══════════════════════════════════════════════════════════

    VARIANTES DISPONIBLES (comme présentées dans la vidéo) :
    ─────────────────────────────────────────────────────────
    1. isolée        — Englobante seule, sans filtre contextuel
    2. sur_support   — Englobante sur une zone de support identifiable
    3. sur_ma        — Englobante sur une moyenne mobile (50/100/150)
    4. sur_divergence — Englobante avec divergence haussière RSI
    5. sur_bad_range  — Englobante sur une consolidation (bad range)

    RÈGLES D'ENTRÉE (3 options, comme dans la vidéo) :
    ─────────────────────────────────────────────────────────
    - "clôture"          : entrée à la clôture de l'englobante
    - "50pct"            : entrée à 50% du corps de l'englobante
    - "ouverture_suivante": entrée à l'ouverture de la bougie suivante

    FILTRES DISPONIBLES :
    ─────────────────────────────────────────────────────────
    - tendance_haussiere : prix au-dessus MA (50/100/150)
    - volume_superieur   : volume > moyenne 20j
    - rsi_divergence     : divergence haussière RSI
    - pas_annonce_majeure: (à vérifier manuellement — FOMC, NFP, CPI)
    - ratio_rr_minimum   : R/R ≥ seuil défini
    - atr_filter         : ATR > minimum (évite les marchés trop calmes)
    """

    name = "Englobante Haussière"

    # ── RÈGLE D'OR (vidéo) ────────────────────────────────────
    # "Ne trader QUE des actifs Long — actifs qui ne font qu'évoluer
    #  à la hausse — pour avoir la tendance avec soi."
    # ──────────────────────────────────────────────────────────

    def __init__(self, config: Config,
                 variante: str = "sur_ma",
                 entry_type: str = "clôture",
                 ma_period: int = 100,
                 min_rr: float = 2.0,
                 filtres_actifs: Optional[List[str]] = None):
        """
        Args:
            config      : Configuration globale du bot
            variante    : Parmi isolée|sur_support|sur_ma|sur_divergence|sur_bad_range
            entry_type  : clôture|50pct|ouverture_suivante
            ma_period   : Période MA (50, 100 ou 150 selon les résultats)
            min_rr      : Ratio Risque/Récompense minimum accepté
            filtres_actifs : Liste des filtres à activer (None = tous)
        """
        self.c = config
        self.variante    = variante
        self.entry_type  = entry_type
        self.ma_period   = ma_period
        self.min_rr      = min_rr
        self.filtres_actifs = filtres_actifs or [
            'tendance_haussiere',
            'volume_superieur',
            'ratio_rr_minimum',
            'atr_filter',
        ]

    # ────────────────────────────────────────────────────────────
    # DÉTECTION DU PATTERN
    # ────────────────────────────────────────────────────────────

    def _detect_englobante(self, opens: pd.Series, closes: pd.Series,
                           idx: int) -> Tuple[bool, int]:
        """
        Détecte une englobante haussière à l'index idx.

        RÈGLE (vidéo) :
        - Bougie courante : haussière (close > open)
        - Bougie précédente : baissière (close < open)
        - Corps de la bougie courante ENGLOBE ENTIÈREMENT
          le corps de la bougie précédente (Haussière ou Baissière)

        Retourne (direction, nb_bougies_englobées) où direction in ('LONG', 'SHORT', None)
        """
        if idx < 1:
            return None, 0

        curr_open  = opens.iloc[idx]
        curr_close = closes.iloc[idx]
        prev_open  = opens.iloc[idx-1]
        prev_close = closes.iloc[idx-1]

        # 1. ENGLOBANTE HAUSSIÈRE (LONG)
        if curr_close > curr_open and prev_close < prev_open:
            if curr_open <= min(prev_open, prev_close) and curr_close >= max(prev_open, prev_close):
                nb = 1
                for i in range(idx-2, max(0, idx-5), -1):
                    body_low  = min(opens.iloc[i], closes.iloc[i])
                    body_high = max(opens.iloc[i], closes.iloc[i])
                    if curr_open <= body_low and curr_close >= body_high:
                        nb += 1
                    else:
                        break
                return 'LONG', nb

        # 2. ENGLOBANTE BAISSIÈRE (SHORT)
        elif curr_close < curr_open and prev_close > prev_open:
            if curr_open >= max(prev_open, prev_close) and curr_close <= min(prev_open, prev_close):
                nb = 1
                for i in range(idx-2, max(0, idx-5), -1):
                    body_low  = min(opens.iloc[i], closes.iloc[i])
                    body_high = max(opens.iloc[i], closes.iloc[i])
                    if curr_open >= body_high and curr_close <= body_low:
                        nb += 1
                    else:
                        break
                return 'SHORT', nb

        return None, 0

    # ────────────────────────────────────────────────────────────
    # FILTRES
    # ────────────────────────────────────────────────────────────

    def _filtre_tendance(self, close: pd.Series, direction: str) -> Tuple[bool, str]:
        """Filtre tendance aligné sur la direction du signal (MA50/100/150)."""
        if len(close) < self.ma_period + 5:
            return True, f"Données limitées pour MA{self.ma_period}"
        ma = I.sma(close, self.ma_period)
        current_price = close.iloc[-1]
        current_ma    = ma.iloc[-1]

        if direction == 'LONG':
            if current_price > current_ma * 0.998:
                pct = (current_price / current_ma - 1) * 100
                return True, f"✅ Tendance haussière : prix {pct:+.1f}% vs MA{self.ma_period}"
            else:
                pct = (current_ma / current_price - 1) * 100
                return False, f"❌ Prix {pct:.1f}% sous MA{self.ma_period} — contre-tendance Long"
        else: # SHORT
            if current_price < current_ma * 1.002:
                pct = (current_ma / current_price - 1) * 100
                return True, f"✅ Tendance baissière : prix {pct:+.1f}% vs MA{self.ma_period}"
            else:
                pct = (current_price / current_ma - 1) * 100
                return False, f"❌ Prix {pct:.1f}% au-dessus MA{self.ma_period} — contre-tendance Short"

    def _filtre_volume(self, volume: pd.Series) -> Tuple[bool, str]:
        """Volume de l'englobante avec support des volumes synthétiques / tick."""
        is_flat_vol = (volume.tail(20).std() < 1e-6) or (volume.iloc[-1] == 0)
        if is_flat_vol:
            return True, "ℹ️ Volume régulier/synthétique — validation price action pure"
        avg_vol = volume.tail(21).iloc[:-1].mean()
        curr_vol = volume.iloc[-1]
        ratio = curr_vol / avg_vol if avg_vol > 0 else 0
        if ratio >= 0.95:
            return True, f"✅ Volume {ratio:.1f}× la moyenne (confirmation de force)"
        else:
            return False, f"⚠️ Volume {ratio:.1f}× la moyenne (englobante sur faible volume)"

    def _filtre_divergence_rsi(self, close: pd.Series) -> Tuple[bool, str]:
        """
        Divergence haussière RSI (comme mentionné dans la vidéo).
        Prix fait un nouveau plus bas mais RSI ne le confirme pas.
        """
        if len(close) < 20:
            return False, "Données insuffisantes pour divergence RSI"
        rsi_vals = I.rsi(close, 14)
        window = 15
        price_min_prev = close.iloc[-window:-1].min()
        price_min_curr = close.iloc[-1]
        rsi_at_prev_min = rsi_vals.iloc[-window:-1].min()
        rsi_at_curr = rsi_vals.iloc[-1]
        if price_min_curr < price_min_prev and rsi_at_curr > rsi_at_prev_min:
            return True, f"✅ Divergence haussière RSI (prix : nouveau bas, RSI : bas plus haut)"
        return False, "⚠️  Pas de divergence haussière RSI détectée"

    def _filtre_sur_support(self, close: pd.Series, low: pd.Series,
                             high: pd.Series) -> Tuple[bool, str]:
        """
        Englobante sur un niveau de support identifiable.
        Détecte un pivot bas récent qui sert de support.
        """
        window = 30
        recent_lows = low.tail(window)
        current_price = close.iloc[-1]
        # Chercher un pivot bas à ±2% du prix actuel
        for i in range(len(recent_lows)-3, 0, -1):
            pivot = recent_lows.iloc[i]
            if (abs(current_price - pivot) / pivot) < 0.02:
                if recent_lows.iloc[i] <= recent_lows.iloc[i-1] and \
                   recent_lows.iloc[i] <= recent_lows.iloc[i+1]:
                    return True, f"✅ Englobante sur support @ ${pivot:.2f}"
        return False, "⚠️  Pas de niveau de support proche identifié"

    def _filtre_bad_range(self, close: pd.Series,
                           high: pd.Series, low: pd.Series) -> Tuple[bool, str]:
        """
        Englobante sur consolidation (bad range).
        Détecte si le marché était en consolidation les N dernières bougies.
        """
        n = 10
        recent_range = (high.tail(n) - low.tail(n)).mean()
        total_move = abs(close.tail(n).max() - close.tail(n).min())
        ratio = total_move / recent_range if recent_range > 0 else 0
        if ratio < 3.0:
            return True, f"✅ Consolidation détectée (bad range — ratio {ratio:.1f})"
        return False, f"⚠️  Pas de consolidation préalable (ratio {ratio:.1f})"

    def _filtre_rr(self, entry: float, sl: float,
                    tp: float) -> Tuple[bool, str]:
        """Ratio Risque/Récompense minimum (vidéo : RR ≥ 2:1)."""
        risk   = abs(entry - sl)
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 0
        if rr >= self.min_rr:
            return True, f"✅ R/R {rr:.1f}:1 (≥ {self.min_rr}:1 requis)"
        return False, f"❌ R/R {rr:.1f}:1 (< {self.min_rr}:1 requis)"

    def _filtre_atr(self, high: pd.Series, low: pd.Series,
                     close: pd.Series) -> Tuple[bool, str]:
        """ATR minimum — évite les marchés trop calmes (piège de la vidéo)."""
        atr = I.atr(high, low, close, 14)
        current_atr = atr.iloc[-1]
        avg_atr = atr.tail(50).mean()
        if current_atr >= avg_atr * 0.7:
            return True, f"✅ ATR actif (ATR={current_atr:.3f}, moy={avg_atr:.3f})"
        return False, f"⚠️  ATR faible ({current_atr:.3f} < {avg_atr*0.7:.3f})"

    # ────────────────────────────────────────────────────────────
    # CALCUL DES NIVEAUX
    # ────────────────────────────────────────────────────────────

    def _calculate_entry(self, curr_open: float, curr_close: float,
                          next_open: float) -> float:
        """Calcule le prix d'entrée selon le type choisi."""
        if self.entry_type == "clôture":
            return curr_close
        elif self.entry_type == "50pct":
            return (curr_open + curr_close) / 2
        elif self.entry_type == "ouverture_suivante":
            return next_open
        return curr_close

    def _calculate_levels(self, entry: float, low_englobante: float,
                           high_englobante: float, atr_val: float,
                           nb_englobees: int, direction: str = 'LONG') -> Tuple[float, float, float, float]:
        """
        Calcule SL, TP1, TP2, TP3 adaptés à la direction.
        Stop Loss : au-delà de l'englobante avec marge 0.45 ATR
        TP1 : R/R 2:1
        TP2 : R/R 3:1
        """
        if direction == 'LONG':
            sl   = low_englobante - atr_val * 0.45
            risk = entry - sl
            if risk <= 0:
                sl = entry - atr_val * 1.0
                risk = entry - sl
            tp1  = entry + risk * 2.0
            tp2  = entry + risk * 3.0
            tp3  = entry + risk * 4.0 if nb_englobees >= 2 else 0.0
            rr   = (tp2 - entry) / risk if risk > 0 else 0
        else: # SHORT
            sl   = high_englobante + atr_val * 0.45
            risk = sl - entry
            if risk <= 0:
                sl = entry + atr_val * 1.0
                risk = sl - entry
            tp1  = entry - risk * 2.0
            tp2  = entry - risk * 3.0
            tp3  = entry - risk * 4.0 if nb_englobees >= 2 else 0.0
            rr   = (entry - tp2) / risk if risk > 0 else 0
        return sl, tp1, tp2, tp3

    # ────────────────────────────────────────────────────────────
    # GÉNÉRATION DU SIGNAL
    # ────────────────────────────────────────────────────────────

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> EnglobanteSignal:
        """
        Point d'entrée principal.
        Analyse le DataFrame et retourne un signal complet (LONG ou SHORT).
        """
        sig = EnglobanteSignal(ticker=ticker, variante=self.variante)

        if df is None or len(df) < max(60, self.ma_period + 10):
            sig.avertissements.append("Données insuffisantes")
            return sig

        opens  = df['Open']
        highs  = df['High']
        lows   = df['Low']
        closes = df['Close']
        volume = df['Volume']

        # ── 1. Détecter l'englobante sur la dernière bougie ──
        idx = len(closes) - 1
        direction, nb_englobees = self._detect_englobante(opens, closes, idx)

        if not direction:
            # Vérifier aussi avant-dernière bougie (signal récent)
            idx = len(closes) - 2
            direction, nb_englobees = self._detect_englobante(opens, closes, idx)
            if not direction:
                sig.checklist.append("⏳ Pas d'englobante sur les 2 dernières bougies")
                return sig

        sig.nb_bougies_englobees = nb_englobees
        force_base = 45 + nb_englobees * 10

        # ── 2. Données de l'englobante ───────────────────────
        curr_open  = opens.iloc[idx]
        curr_close = closes.iloc[idx]
        curr_low   = lows.iloc[idx]
        curr_high  = highs.iloc[idx]
        atr_val    = I.atr(highs, lows, closes, 14).iloc[-1]

        # Prix de la bougie suivante (pour entry_type "ouverture_suivante")
        next_open = closes.iloc[-1] if idx < len(closes)-1 else curr_close

        entry = self._calculate_entry(curr_open, curr_close, next_open)
        sl, tp1, tp2, tp3 = self._calculate_levels(entry, curr_low, curr_high, atr_val, nb_englobees, direction)
        risk = abs(entry - sl)
        rr   = abs(tp2 - entry) / risk if risk > 0 else 0

        sig.entry      = entry
        sig.stop_loss  = sl
        sig.tp1        = tp1
        sig.tp2        = tp2
        sig.tp3        = tp3
        sig.risk_reward = rr
        sig.entry_type = self.entry_type

        # ── 3. Checklist de base ─────────────────────────────
        englobe_desc = f"{'les ' + str(nb_englobees) + ' bougies précédentes' if nb_englobees > 1 else 'la bougie précédente'}"
        if direction == 'LONG':
            sig.checklist.append(f"✅ Englobante HAUSSIÈRE : corps vert englobe {englobe_desc}")
        else:
            sig.checklist.append(f"✅ Englobante BAISSIÈRE : corps rouge englobe {englobe_desc}")

        if nb_englobees >= 2:
            sig.checklist.append(f"✅ Signal FORT : {nb_englobees} bougies englobées")
            force_base += 10

        # ── 4. Application des filtres ────────────────────────
        filter_pass = 0
        filter_total = 0

        # Filtre tendance aligné
        if 'tendance_haussiere' in self.filtres_actifs or self.variante == 'sur_ma':
            filter_total += 1
            ok, msg = self._filtre_tendance(closes, direction)
            sig.checklist.append(msg)
            if ok:
                filter_pass += 1
                force_base += 15
            else:
                sig.filtres_invalides.append(msg)

        # Filtre variante spécifique
        if self.variante == "sur_support":
            filter_total += 1
            ok, msg = self._filtre_sur_support(closes, lows, highs)
            sig.checklist.append(msg)
            if ok: filter_pass += 1; force_base += 15
            else: sig.filtres_invalides.append(msg)

        elif self.variante == "sur_divergence":
            filter_total += 1
            ok, msg = self._filtre_divergence_rsi(closes)
            sig.checklist.append(msg)
            if ok: filter_pass += 1; force_base += 20
            else: sig.filtres_invalides.append(msg)

        elif self.variante == "sur_bad_range":
            filter_total += 1
            ok, msg = self._filtre_bad_range(closes, highs, lows)
            sig.checklist.append(msg)
            if ok: filter_pass += 1; force_base += 15
            else: sig.filtres_invalides.append(msg)

        # Filtre volume
        if 'volume_superieur' in self.filtres_actifs:
            filter_total += 1
            ok, msg = self._filtre_volume(volume)
            sig.checklist.append(msg)
            if ok: filter_pass += 1; force_base += 10
            else: sig.filtres_invalides.append(msg)

        # Filtre ATR
        if 'atr_filter' in self.filtres_actifs:
            filter_total += 1
            ok, msg = self._filtre_atr(highs, lows, closes)
            sig.checklist.append(msg)
            if ok: filter_pass += 1; force_base += 5

        # Filtre R/R
        if 'ratio_rr_minimum' in self.filtres_actifs:
            filter_total += 1
            ok, msg = self._filtre_rr(entry, sl, tp2)
            sig.checklist.append(msg)
            if ok: filter_pass += 1; force_base += 10
            else: sig.filtres_invalides.append(msg)

        # ── 5. Décision finale ───────────────────────────────
        critical_fails = len(sig.filtres_invalides)
        if critical_fails == 0 and rr >= self.min_rr:
            sig.direction = direction
            sig.strength  = min(force_base, 100)
            sig.reason    = (
                f"Englobante {direction} {self.variante} | {nb_englobees} b. englobée(s) "
                f"| Filtres {filter_pass}/{filter_total} | R/R {rr:.1f}:1"
            )
        elif critical_fails <= 1 and rr >= self.min_rr * 0.8:
            sig.direction = direction
            sig.strength  = max(force_base - 15, 65)
            sig.reason    = f"Signal {direction} toléré ({critical_fails} filtre mineur non validé) | R/R {rr:.1f}:1"
        else:
            sig.strength  = max(force_base - 30, 20)
            sig.reason    = f"Filtres insuffisants ou R/R trop faible ({rr:.1f}:1)"

        return sig


# ══════════════════════════════════════════════════════════════════
# BACKTEST MANUEL — Méthode de la vidéo
# ══════════════════════════════════════════════════════════════════

class EnglobanteBacktester:
    """
    Backtester pour l'Englobante Haussière selon la méthode exacte
    décrite dans la vidéo :

    ÉTAPES (vidéo) :
    1. Définir les règles avant de regarder les données
       - Direction stricte de l'englobante
       - Corps ou 50% pour l'entrée
       - Confluences requises
       - Placement du TP et SL
    2. Choisir l'actif et scanner tout l'historique
    3. Identifier TOUTES les englobantes
    4. Appliquer les filtres si nécessaire
    5. Enregistrer le résultat de chaque setup valide
    6. Analyser sur minimum 50 trades
    7. Interpréter : si pas rentable → changer paramètres ou stratégie
    8. Si rentable → s'entraîner en démo d'abord

    MÉTRIQUES (vidéo) :
    - Win Rate
    - Profit Factor
    - Max Drawdown
    - Fréquence (trades/semaine, /mois, /an)
    """

    def __init__(self, strategy: EnglobanteHaussiere):
        self.strategy = strategy

    def run(self, ticker: str, df: pd.DataFrame,
            min_trades: int = 50) -> Dict:
        """
        Lance le backtest sur l'historique complet.

        Args:
            ticker     : Symbole de l'actif
            df         : DataFrame OHLCV historique
            min_trades : Minimum de trades pour une analyse fiable (vidéo : 50)

        Returns:
            Dictionnaire avec toutes les métriques
        """
        if df is None or len(df) < 100:
            return {"erreur": "Données insuffisantes pour le backtest"}

        opens  = df['Open']
        highs  = df['High']
        lows   = df['Low']
        closes = df['Close']
        volume = df['Volume']
        atr_s  = I.atr(highs, lows, closes, 14)

        trades = []
        capital = self.strategy.c.initial_capital
        equity_curve = [capital]
        lookback = max(60, self.strategy.ma_period + 5)

        # Scanner tout l'historique (méthode vidéo)
        for idx in range(lookback, len(closes) - 1):
            # Créer un slice jusqu'à idx
            sub_df = df.iloc[:idx+1].copy()
            sig = self.strategy.generate_signal(ticker, sub_df)

            if sig.direction != 'LONG':
                continue

            # Simuler le trade
            entry = sig.entry
            sl    = sig.stop_loss
            tp1   = sig.tp1
            tp2   = sig.tp2
            risk  = entry - sl
            if risk <= 0:
                continue

            # Calcul taille de position
            shares = int((capital * self.strategy.c.risk_per_trade) / risk)
            if shares == 0:
                continue

            # Simuler la progression bougie par bougie
            result = None
            max_future = min(idx + 50, len(closes) - 1)
            exit_price = None
            exit_reason = None
            shares_sold_tp1 = 0

            for fut_idx in range(idx + 1, max_future):
                fut_high = highs.iloc[fut_idx]
                fut_low  = lows.iloc[fut_idx]

                # Stop Loss
                if fut_low <= sl:
                    exit_price = sl
                    exit_reason = "STOP LOSS"
                    remaining = shares - shares_sold_tp1
                    pnl = (exit_price - entry) * remaining
                    if shares_sold_tp1 > 0:
                        pnl += (tp1 - entry) * shares_sold_tp1
                    result = pnl
                    break

                # TP1 (vendre 25% — scale out vidéo)
                if fut_high >= tp1 and shares_sold_tp1 == 0:
                    shares_sold_tp1 = max(1, shares // 4)

                # TP2
                if fut_high >= tp2:
                    remaining = shares - shares_sold_tp1
                    exit_price = tp2
                    exit_reason = "TP2"
                    pnl = (tp2 - entry) * remaining
                    if shares_sold_tp1 > 0:
                        pnl += (tp1 - entry) * shares_sold_tp1
                    result = pnl
                    break

            if result is None and exit_price is None:
                # Forcer la clôture à la fin
                exit_price = closes.iloc[max_future - 1]
                exit_reason = "TIMEOUT"
                remaining = shares - shares_sold_tp1
                result = (exit_price - entry) * remaining
                if shares_sold_tp1 > 0:
                    result += (tp1 - entry) * shares_sold_tp1

            if result is not None:
                capital += result
                trades.append({
                    'idx':         idx,
                    'date':        df.index[idx],
                    'entry':       entry,
                    'exit':        exit_price,
                    'exit_reason': exit_reason,
                    'pnl':         result,
                    'pnl_pct':     (result / (entry * shares)) * 100 if entry * shares > 0 else 0,
                    'win':         result > 0,
                    'variante':    sig.variante,
                })
                equity_curve.append(capital)

        # ── Calcul des métriques (vidéo) ─────────────────────
        if len(trades) < 10:
            return {
                "ticker": ticker,
                "trades": len(trades),
                "avertissement": f"Seulement {len(trades)} trades — minimum recommandé : {min_trades}"
            }

        wins   = [t for t in trades if t['win']]
        losses = [t for t in trades if not t['win']]

        win_rate     = len(wins) / len(trades) * 100
        avg_win      = np.mean([t['pnl'] for t in wins]) if wins else 0
        avg_loss     = abs(np.mean([t['pnl'] for t in losses])) if losses else 0
        profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if losses and avg_loss > 0 else 0

        # Drawdown maximum
        peak = self.strategy.c.initial_capital
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            max_dd = max(max_dd, dd)

        # Fréquence
        if len(trades) >= 2:
            days_total = (trades[-1]['date'] - trades[0]['date']).days
            freq_week  = len(trades) / (days_total / 7) if days_total > 0 else 0
            freq_month = len(trades) / (days_total / 30) if days_total > 0 else 0
        else:
            freq_week = freq_month = 0

        total_return = (capital / self.strategy.c.initial_capital - 1) * 100

        fiabilite = "INSUFFISANT" if len(trades) < min_trades else \
                    "FAIBLE" if len(trades) < min_trades * 2 else "FIABLE"

        return {
            "ticker":          ticker,
            "variante":        self.strategy.variante,
            "entry_type":      self.strategy.entry_type,
            "ma_period":       self.strategy.ma_period,
            # Métriques vidéo
            "nb_trades":       len(trades),
            "win_rate":        round(win_rate, 1),
            "profit_factor":   round(profit_factor, 2),
            "max_drawdown":    round(max_dd, 1),
            "freq_par_semaine": round(freq_week, 1),
            "freq_par_mois":   round(freq_month, 1),
            # Financier
            "capital_initial": self.strategy.c.initial_capital,
            "capital_final":   round(capital, 0),
            "rendement_total": round(total_return, 1),
            "gain_moyen":      round(avg_win, 0),
            "perte_moyenne":   round(avg_loss, 0),
            "ratio_rr_reel":   round(avg_win / avg_loss, 2) if avg_loss > 0 else 0,
            "fiabilite":       fiabilite,
            # Avertissements (méthode vidéo)
            "avertissements": [
                "Les résultats passés ne garantissent pas les performances futures",
                "Backtestez sur plusieurs actifs différents avant de trader en réel",
                "Commencez par un compte démo",
                f"Échantillon {'insuffisant' if len(trades) < min_trades else 'acceptable'} "
                f"({len(trades)} trades / {min_trades} minimum recommandé)"
            ]
        }
