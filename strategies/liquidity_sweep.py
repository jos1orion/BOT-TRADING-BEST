"""
╔══════════════════════════════════════════════════════════════════╗
║  STRATÉGIE — LIQUIDITY SWEEP (Prise de Liquidité)              ║
║                                                                  ║
║  Source : Vidéo challenge 1 heure — trader 5 ans               ║
║                                                                  ║
║  Concept (Smart Money / Institutionnel) :                       ║
║  Les institutions viennent chercher les zones de liquidité     ║
║  (là où se concentrent les stop loss) pour trouver une         ║
║  contrepartie, puis repartent dans la direction opposée.       ║
║                                                                  ║
║  3 ÉTAPES (vidéo) :                                            ║
║  1. Identifier la poche de liquidité (swing high/low)          ║
║  2. Attendre que le marché vienne la "sweeper"                 ║
║  3. Rentrer sur le reversal (retournement post-sweep)          ║
║                                                                  ║
║  ⚠️  Erreurs à éviter (vidéo) :                               ║
║  - Rentrer PENDANT le sweep (piège classique)                  ║
║  - Stop loss trop serré sur le reversal                        ║
║  - Ne pas attendre la confirmation du retournement             ║
╚══════════════════════════════════════════════════════════════════╝
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
import pandas as pd
import numpy as np
from core.indicators import Indicators as I
from core.config import Config


@dataclass
class LiquidityZone:
    """Représente une zone de liquidité identifiée."""
    price:      float
    zone_type:  str     # 'swing_high' | 'swing_low' | 'double_top' | 'double_bottom'
                        # | 'trendline' | 'round_number' | 'support' | 'resistance'
    strength:   int     # 1–5 (nombre de touches)
    swept:      bool    = False
    idx:        int     = 0
    description: str   = ""

    # Qualité de la zone (vidéo : certaines zones sont meilleures)
    QUALITY_MAP = {
        'double_top':    5,  # Le plus fiable selon la vidéo
        'double_bottom': 5,
        'round_number':  4,  # Prix psychologiques
        'swing_high':    3,
        'swing_low':     3,
        'trendline':     3,
        'support':       2,
        'resistance':    2,
    }

    @property
    def quality_score(self) -> int:
        return self.QUALITY_MAP.get(self.zone_type, 2) + min(self.strength - 1, 3)


@dataclass
class LiquiditySweepSignal:
    """Signal complet de la stratégie Liquidity Sweep."""
    ticker:        str
    strategy:      str  = "Liquidity Sweep"
    direction:     Optional[str] = None
    strength:      float = 0.0
    entry:         float = 0.0
    stop_loss:     float = 0.0
    tp1:           float = 0.0
    tp2:           float = 0.0
    risk_reward:   float = 0.0
    zone:          Optional[LiquidityZone] = None
    sweep_price:   float = 0.0
    checklist:     List[str] = field(default_factory=list)
    erreurs_eviter: List[str] = field(default_factory=list)
    reason:        str  = ""

    def __str__(self):
        if not self.direction:
            return f"[Liquidity Sweep] {self.ticker} — Pas de signal"
        zone_desc = self.zone.description if self.zone else ""
        return (
            f"[Liquidity Sweep] {self.ticker} {self.direction} "
            f"| Sweep de {zone_desc} "
            f"| Entrée @ ${self.entry:.2f} "
            f"| SL ${self.stop_loss:.2f} | TP1 ${self.tp1:.2f} "
            f"| R/R {self.risk_reward:.1f}:1 | Force {self.strength:.0f}/100"
        )


class LiquiditySweepStrategy:
    """
    ═══════════════════════════════════════════════════════════
    STRATÉGIE LIQUIDITY SWEEP — Smart Money Concept
    ═══════════════════════════════════════════════════════════

    IDENTIFICATION DES ZONES DE LIQUIDITÉ (vidéo) :
    ─────────────────────────────────────────────────────────
    1. Swing Highs / Swing Lows
       → Zones où les stop loss s'accumulent
       → Le marché vient les chercher pour trouver contrepartie

    2. Double Top / Double Bottom
       → Niveau touché deux fois = concentration de stops
       → Zone psychologique forte

    3. Trendlines
       → Les breaks de trendline = sweep de liquidité
       → Souvent faux breakout institutionnel

    4. Nombres ronds (psychologiques)
       → Bitcoin @ 100 000$, or @ 2 000$, S&P @ 5 000
       → Concentration naturelle de stops et d'ordres

    5. Support / Résistance classique
       → Zones touchées plusieurs fois

    PROCESSUS D'EXÉCUTION (3 étapes, vidéo) :
    ─────────────────────────────────────────────────────────
    1. Identifier la poche de liquidité (avant qu'elle soit touchée)
    2. Attendre le SWEEP (passage au-delà de la zone)
    3. Rentrer sur le REVERSAL (confirmation de retournement)
       ⚠️  NE PAS rentrer PENDANT le sweep

    ERREURS À ÉVITER (vidéo) :
    ─────────────────────────────────────────────────────────
    - Rentrer pendant le sweep → se retrouver coincé dans la liquidité
    - Stop loss trop serré → sortie prématurée
    - Prendre chaque sweep sans confirmation du reversal
    - Ignorer la tendance générale
    - Trader une zone déjà liquidée (zone "grise" dans l'indicateur vidéo)
    """

    name = "Liquidity Sweep"

    # Timeframes recommandés dans la vidéo
    TIMEFRAMES_RECOMMANDES = {
        'scalping':   '1min',
        'intraday':   '5min',   # Recommandé pour le challenge 1h
        'swing':      '15min',
        'position':   '1h',
    }

    # Actifs recommandés dans la vidéo
    ACTIFS_RECOMMANDES = {
        'forex_haute_liquidite': ['EURUSD', 'GBPUSD', 'USDJPY'],
        'forex_volatil':        ['GBPJPY', 'EURJPY'],
        'indices':              ['DAX', 'SPX500', 'NAS100'],
        'crypto_instit':        ['BTCUSD'],
    }

    def __init__(self, config: Config,
                 swing_lookback: int = 5,
                 sweep_confirmation_bars: int = 2,
                 min_rr: float = 2.0,
                 use_round_numbers: bool = True):
        """
        Args:
            config                   : Config globale
            swing_lookback           : Bougies de chaque côté pour valider un swing (défaut: 5)
            sweep_confirmation_bars  : Bougies de confirmation après le sweep
            min_rr                   : R/R minimum
            use_round_numbers        : Activer la détection des prix ronds
        """
        self.c = config
        self.swing_lookback = swing_lookback
        self.sweep_confirmation_bars = sweep_confirmation_bars
        self.min_rr = min_rr
        self.use_round_numbers = use_round_numbers

    # ────────────────────────────────────────────────────────────
    # IDENTIFICATION DES ZONES DE LIQUIDITÉ
    # ────────────────────────────────────────────────────────────

    def identify_liquidity_zones(self, highs: pd.Series, lows: pd.Series,
                                  closes: pd.Series) -> List[LiquidityZone]:
        """
        Identifie toutes les zones de liquidité sur l'historique.
        Méthode complète telle que décrite dans la vidéo.
        """
        zones = []
        n = len(closes)
        lk = self.swing_lookback

        # ── 1. Swing Highs ─────────────────────────────────
        for i in range(lk, n - lk):
            window_highs = highs.iloc[i-lk:i+lk+1]
            if highs.iloc[i] == window_highs.max():
                # Compter les touches (strength)
                touches = self._count_touches(highs, closes, highs.iloc[i], 'resistance', i, n)
                zones.append(LiquidityZone(
                    price=highs.iloc[i],
                    zone_type='swing_high',
                    strength=touches,
                    idx=i,
                    description=f"Swing High @ ${highs.iloc[i]:.2f} ({touches} touche(s))"
                ))

        # ── 2. Swing Lows ──────────────────────────────────
        for i in range(lk, n - lk):
            window_lows = lows.iloc[i-lk:i+lk+1]
            if lows.iloc[i] == window_lows.min():
                touches = self._count_touches(lows, closes, lows.iloc[i], 'support', i, n)
                zones.append(LiquidityZone(
                    price=lows.iloc[i],
                    zone_type='swing_low',
                    strength=touches,
                    idx=i,
                    description=f"Swing Low @ ${lows.iloc[i]:.2f} ({touches} touche(s))"
                ))

        # ── 3. Double Top / Double Bottom ──────────────────
        double_zones = self._detect_double_patterns(highs, lows, closes)
        zones.extend(double_zones)

        # ── 4. Nombres ronds ──────────────────────────────
        if self.use_round_numbers:
            round_zones = self._detect_round_numbers(closes)
            zones.extend(round_zones)

        # Dédupliquer (zones trop proches = même zone)
        zones = self._deduplicate_zones(zones)

        # Marquer les zones déjà liquidées (comme dans l'indicateur vidéo)
        zones = self._mark_swept_zones(zones, closes)

        return zones

    def _count_touches(self, series: pd.Series, closes: pd.Series,
                        price: float, side: str,
                        start_idx: int, n: int,
                        tolerance_pct: float = 0.003) -> int:
        """
        Compte le nombre de fois que le prix est revenu sur un niveau.
        Plus il y a de touches, plus la liquidité est forte (vidéo).
        """
        touches = 1
        for i in range(start_idx + 1, min(n, start_idx + 100)):
            val = series.iloc[i]
            if abs(val - price) / price <= tolerance_pct:
                touches += 1
        return touches

    def _detect_double_patterns(self, highs: pd.Series, lows: pd.Series,
                                  closes: pd.Series) -> List[LiquidityZone]:
        """
        Double Top / Double Bottom — zones de haute liquidité (vidéo).
        "Le marché vient une fois, deux fois. C'est un niveau psychologique."
        """
        zones = []
        n = len(closes)
        tolerance = 0.005

        swing_highs = []
        swing_lows  = []
        lk = self.swing_lookback

        for i in range(lk, n - lk):
            if highs.iloc[i] == highs.iloc[i-lk:i+lk+1].max():
                swing_highs.append((i, highs.iloc[i]))
            if lows.iloc[i] == lows.iloc[i-lk:i+lk+1].min():
                swing_lows.append((i, lows.iloc[i]))

        # Double Top
        for i in range(len(swing_highs) - 1):
            for j in range(i+1, min(i+5, len(swing_highs))):
                p1 = swing_highs[i][1]
                p2 = swing_highs[j][1]
                if abs(p1 - p2) / p1 <= tolerance:
                    zones.append(LiquidityZone(
                        price=(p1 + p2) / 2,
                        zone_type='double_top',
                        strength=3,
                        idx=swing_highs[j][0],
                        description=f"Double Top @ ${(p1+p2)/2:.2f} — Haute liquidité"
                    ))

        # Double Bottom
        for i in range(len(swing_lows) - 1):
            for j in range(i+1, min(i+5, len(swing_lows))):
                p1 = swing_lows[i][1]
                p2 = swing_lows[j][1]
                if abs(p1 - p2) / p1 <= tolerance:
                    zones.append(LiquidityZone(
                        price=(p1 + p2) / 2,
                        zone_type='double_bottom',
                        strength=3,
                        idx=swing_lows[j][0],
                        description=f"Double Bottom @ ${(p1+p2)/2:.2f} — Haute liquidité"
                    ))

        return zones

    def _detect_round_numbers(self, closes: pd.Series) -> List[LiquidityZone]:
        """
        Détecte les prix psychologiques (nombres ronds).
        Vidéo : "Bitcoin @ 100 000$, or @ 2 000$ — prix faciles à retenir."
        """
        zones = []
        current_price = closes.iloc[-1]
        magnitude = 10 ** max(0, int(np.log10(current_price)) - 1)

        for multiplier in [1, 2, 5, 10]:
            step = magnitude * multiplier
            lower = int(current_price / step) * step
            for level in [lower - step, lower, lower + step, lower + 2*step]:
                if level > 0:
                    proximity = abs(closes.iloc[-1] - level) / closes.iloc[-1]
                    if proximity < 0.05:  # Dans les 5%
                        zones.append(LiquidityZone(
                            price=level,
                            zone_type='round_number',
                            strength=4,
                            idx=len(closes)-1,
                            description=f"Prix psychologique @ ${level:.0f}"
                        ))

        return zones

    def _deduplicate_zones(self, zones: List[LiquidityZone],
                            tolerance_pct: float = 0.005) -> List[LiquidityZone]:
        """Fusionne les zones trop proches."""
        if not zones:
            return zones
        zones.sort(key=lambda z: z.price)
        deduped = [zones[0]]
        for z in zones[1:]:
            if abs(z.price - deduped[-1].price) / deduped[-1].price > tolerance_pct:
                deduped.append(z)
            else:
                # Garder la zone la plus forte
                if z.quality_score > deduped[-1].quality_score:
                    deduped[-1] = z
        return deduped

    def _mark_swept_zones(self, zones: List[LiquidityZone],
                           closes: pd.Series) -> List[LiquidityZone]:
        """
        Marque les zones déjà liquidées.
        Vidéo : "Une zone grise = déjà cassée, ne plus travailler dessus."
        """
        for zone in zones:
            # Si le prix a traversé la zone après sa formation
            if zone.idx + 1 < len(closes):
                future_prices = closes.iloc[zone.idx+1:]
                if zone.zone_type in ('swing_high', 'double_top', 'resistance'):
                    if future_prices.max() > zone.price * 1.002:
                        zone.swept = True
                elif zone.zone_type in ('swing_low', 'double_bottom', 'support'):
                    if future_prices.min() < zone.price * 0.998:
                        zone.swept = True
        return zones

    # ────────────────────────────────────────────────────────────
    # DÉTECTION DU SWEEP
    # ────────────────────────────────────────────────────────────

    def _detect_sweep(self, highs: pd.Series, lows: pd.Series,
                       closes: pd.Series, zone: LiquidityZone,
                       idx: int) -> Tuple[bool, str]:
        """
        Détecte si un sweep vient de se produire sur la zone.

        RÈGLE VIDÉO : Le marché dépasse le niveau PUIS revient rapidement.
        C'est la signature d'une prise de liquidité institutionnelle.
        """
        if idx < 2:
            return False, ""

        current_close = closes.iloc[idx]
        current_high  = highs.iloc[idx]
        current_low   = lows.iloc[idx]
        tolerance     = zone.price * 0.002

        # Sweep d'un swing high (le marché monte AU-DESSUS puis redescend)
        if zone.zone_type in ('swing_high', 'double_top', 'resistance', 'round_number'):
            swept = (current_high > zone.price + tolerance and
                     current_close < zone.price)
            if swept:
                return True, f"SWEEP HAUSSIER de {zone.description} — Chercher une VENTE"

        # Sweep d'un swing low (le marché descend EN-DESSOUS puis remonte)
        elif zone.zone_type in ('swing_low', 'double_bottom', 'support'):
            swept = (current_low < zone.price - tolerance and
                     current_close > zone.price)
            if swept:
                return True, f"SWEEP BAISSIER de {zone.description} — Chercher un ACHAT"

        return False, ""

    # ────────────────────────────────────────────────────────────
    # CONFIRMATION DU REVERSAL
    # ────────────────────────────────────────────────────────────

    def _confirm_reversal(self, opens: pd.Series, highs: pd.Series,
                           lows: pd.Series, closes: pd.Series,
                           sweep_idx: int, direction: str) -> Tuple[bool, str]:
        idx = len(closes) - 1
        curr_open  = opens.iloc[idx]
        curr_close = closes.iloc[idx]
        curr_high  = highs.iloc[idx]
        curr_low   = lows.iloc[idx]

        if direction == 'LONG':
            # Reversal haussier : bougie verte ou forte mèche basse de rejet
            body = abs(curr_close - curr_open)
            lower_wick = min(curr_open, curr_close) - curr_low
            if curr_close > curr_open or (lower_wick > body and curr_close >= curr_open * 0.999):
                return True, "✅ Reversal haussier confirmé (rejet de la liquidité)"
            return False, "⏳ En attente de confirmation haussière"

        elif direction == 'SHORT':
            # Reversal baissier : bougie rouge ou forte mèche haute de rejet
            body = abs(curr_close - curr_open)
            upper_wick = curr_high - max(curr_open, curr_close)
            if curr_close < curr_open or (upper_wick > body and curr_close <= curr_open * 1.001):
                return True, "✅ Reversal baissier confirmé (rejet de la liquidité)"
            return False, "⏳ En attente de confirmation baissière"

        return False, "Direction inconnue"

    # ────────────────────────────────────────────────────────────
    # GÉNÉRATION DU SIGNAL
    # ────────────────────────────────────────────────────────────

    def generate_signal(self, ticker: str, df: pd.DataFrame) -> LiquiditySweepSignal:
        """
        Analyse complète et génération du signal Liquidity Sweep.
        """
        sig = LiquiditySweepSignal(ticker=ticker)

        if df is None or len(df) < 50:
            return sig

        opens  = df['Open']
        highs  = df['High']
        lows   = df['Low']
        closes = df['Close']
        volume = df['Volume']
        atr    = I.atr(highs, lows, closes, 14)

        current_price = closes.iloc[-1]
        current_atr   = atr.iloc[-1]

        # ── Identifier toutes les zones ───────────────────────
        zones = self.identify_liquidity_zones(highs, lows, closes)

        # Filtrer : zones non sweepées, proches du prix actuel (±5%)
        active_zones = [
            z for z in zones
            if not z.swept
            and abs(z.price - current_price) / current_price < 0.05
        ]

        if not active_zones:
            sig.checklist.append("⏳ Aucune zone de liquidité active dans les ±5% du prix actuel")
            sig.checklist.append(f"   Prix actuel: ${current_price:.2f}")
            self._add_erreurs_eviter(sig)
            return sig

        # Trier par qualité décroissante
        active_zones.sort(key=lambda z: z.quality_score, reverse=True)

        idx = len(closes) - 1
        swept_zone = None
        sweep_msg = ""
        sweep_i = None

        # Chercher si une des zones actives a subi un sweep sur la bougie courante ou précédente
        for zone in active_zones:
            for check_idx in (idx, idx - 1):
                is_swept, msg = self._detect_sweep(highs, lows, closes, zone, check_idx)
                if is_swept:
                    swept_zone = zone
                    sweep_msg = msg
                    sweep_i = check_idx
                    break
            if swept_zone:
                break

        if not swept_zone:
            best_zone = active_zones[0]
            sig.zone = best_zone
            sig.checklist.append(f"⏳ Zone identifiée : {best_zone.description}")
            sig.checklist.append(f"   Attendre que le marché vienne tester ${best_zone.price:.2f}")
            sig.strength = 30 + best_zone.quality_score * 3
            self._add_erreurs_eviter(sig)
            return sig

        sig.zone = swept_zone
        sig.sweep_price = swept_zone.price
        sig.checklist.append(f"✅ SWEEP DÉTECTÉ : {sweep_msg}")

        # Déterminer la direction du trade
        if "ACHAT" in sweep_msg:
            direction = 'LONG'
        elif "VENTE" in sweep_msg:
            direction = 'SHORT'
        else:
            return sig

        # ── Confirmer le reversal ─────────────────────────────
        confirmed, confirm_msg = self._confirm_reversal(
            opens, highs, lows, closes, sweep_i, direction)
        sig.checklist.append(confirm_msg)

        if not confirmed:
            sig.checklist.append("⏳ Sweep présent — attendre confirmation du rejet avant d'entrer")
            sig.strength = 50 + swept_zone.quality_score * 3
            self._add_erreurs_eviter(sig)
            return sig

        # ── Calculer les niveaux ─────────────────────────────
        entry = current_price
        if direction == 'LONG':
            sweep_low = min(lows.iloc[sweep_i], lows.iloc[-1])
            sl  = sweep_low - current_atr * 0.4        # Sous le sweep low avec marge ATR
            risk = entry - sl
            if risk <= 0:
                sl = entry - current_atr * 1.0
                risk = entry - sl
            tp1 = entry + risk * 2.0                    # R/R 2:1
            tp2 = entry + risk * 3.5                    # R/R 3.5:1
        else:
            sweep_high = max(highs.iloc[sweep_i], highs.iloc[-1])
            sl  = sweep_high + current_atr * 0.4       # Au-dessus du sweep high avec marge ATR
            risk = sl - entry
            if risk <= 0:
                sl = entry + current_atr * 1.0
                risk = sl - entry
            tp1 = entry - risk * 2.0
            tp2 = entry - risk * 3.5

        rr = abs(tp2 - entry) / risk if risk > 0 else 0

        sig.direction   = direction
        sig.entry       = entry
        sig.stop_loss   = sl
        sig.tp1         = tp1
        sig.tp2         = tp2
        sig.risk_reward = rr

        # ── Checklist finale ──────────────────────────────────
        sig.checklist.append(f"✅ Direction confirmée : {direction}")
        sig.checklist.append(f"   Entrée  : ${entry:.2f}")
        sig.checklist.append(f"   Stop    : ${sl:.2f} (structure invalidation)")
        sig.checklist.append(f"   TP1     : ${tp1:.2f} (R/R 2:1)")
        sig.checklist.append(f"   TP2     : ${tp2:.2f} (R/R 3.5:1)")
        sig.checklist.append(f"   R/R     : {rr:.1f}:1")

        # Confirmation Volume : bonus si volume disponible et en hausse
        vol_ratio = I.volume_ratio(volume, 20).iloc[-1]
        is_flat_vol = (volume.tail(20).std() < 1e-6) or (volume.iloc[-1] == 0)
        if vol_ratio > 1.2:
            sig.checklist.append(f"✅ Volume de confirmation : {vol_ratio:.1f}× la moyenne")
            sig.strength = min(75 + swept_zone.quality_score * 3 + int(vol_ratio * 4), 100)
        elif is_flat_vol:
            sig.checklist.append("ℹ️ Volume tick synthétique/plat — validation sur price action pure")
            sig.strength = min(72 + swept_zone.quality_score * 3, 95)
        else:
            sig.checklist.append(f"⚠️ Volume régulier ({vol_ratio:.1f}×)")
            sig.strength = min(68 + swept_zone.quality_score * 3, 90)

        sig.reason = (
            f"Sweep de {swept_zone.description} | Reversal {direction} confirmé "
            f"| R/R {rr:.1f}:1"
        )

        self._add_erreurs_eviter(sig)
        return sig

    def _add_erreurs_eviter(self, sig: LiquiditySweepSignal):
        """Ajoute les erreurs à éviter de la vidéo."""
        sig.erreurs_eviter = [
            "❌ Ne pas rentrer PENDANT le sweep (piège classique)",
            "❌ Stop loss trop serré — attendre la bougie de confirmation complète",
            "❌ Ne pas prendre une zone déjà sweepée (zone 'grise')",
            "❌ Ignorer la tendance générale — trader dans le sens dominant",
            "❌ Prendre chaque sweep sans confirmation bougie de retournement",
            "❌ Entrer sur une zone de trop faible qualité (1 seule touche)",
            "⚠️  Vérifier l'absence d'annonces économiques majeures",
        ]

    def get_all_zones_report(self, ticker: str, df: pd.DataFrame) -> str:
        """Rapport complet de toutes les zones identifiées sur un actif."""
        if df is None:
            return f"Données manquantes pour {ticker}"

        zones = self.identify_liquidity_zones(df['High'], df['Low'], df['Close'])
        current_price = df['Close'].iloc[-1]

        lines = [
            f"\n  📊 ZONES DE LIQUIDITÉ — {ticker} (prix actuel: ${current_price:.2f})",
            "  " + "─" * 65,
            f"  {'Zone':<35} {'Type':<15} {'Force':>5} {'Statut':>10}",
            "  " + "─" * 65,
        ]

        for z in sorted(zones, key=lambda x: x.price, reverse=True):
            dist = (z.price / current_price - 1) * 100
            statut = "✓ ACTIF" if not z.swept else "✗ sweepée"
            lines.append(
                f"  {z.description:<35} {z.zone_type:<15} {z.quality_score:>5}/8 {statut:>10}  ({dist:+.1f}%)"
            )

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# INDICATEUR PINE SCRIPT (vidéo 2 — demandé à Claude)
# ══════════════════════════════════════════════════════════════════

PINESCRIPT_LIQUIDITY_INDICATOR = '''
//@version=5
// ═══════════════════════════════════════════════════════════════
// INDICATEUR LIQUIDITY ZONES — Stratégie Liquidity Sweep
// Basé sur la stratégie présentée dans la vidéo challenge 1h
// ═══════════════════════════════════════════════════════════════
//
// FONCTIONNALITÉS :
// - Swing Highs / Swing Lows (zones de liquidité)
// - Double Top / Double Bottom
// - Nombres ronds (prix psychologiques)
// - Zones grisées si déjà liquidées
// - Alertes au moment du sweep
//
// UTILISATION :
// 1. Copiez ce code dans TradingView > Pine Script Editor
// 2. Cliquez sur "Ajouter au graphique"
// 3. Configurez les paramètres selon votre timeframe
// ═══════════════════════════════════════════════════════════════

indicator("Liquidity Zones — Sweep Strategy", overlay=true,
         max_boxes_count=200, max_lines_count=200)

// ── Paramètres ────────────────────────────────────────────────
lookback      = input.int(5, "Lookback Swing High/Low", minval=2, maxval=20)
zone_extend   = input.int(50, "Extension des zones (bougies)")
show_round_nb = input.bool(true, "Afficher les nombres ronds")
round_step    = input.float(0.0, "Pas des nombres ronds (0 = auto)")
show_swept    = input.bool(true, "Afficher les zones sweepées (grisées)")
alert_on_sweep = input.bool(true, "Alerte lors d'un sweep")

// Couleurs
col_resistance = input.color(color.new(color.red,   70), "Résistance")
col_support    = input.color(color.new(color.green,  70), "Support")
col_swept      = input.color(color.new(color.gray,   85), "Zone sweepée")
col_double     = input.color(color.new(color.orange, 60), "Double Top/Bottom")

// ── Détection Swing High / Swing Low ──────────────────────────
is_swing_high = ta.pivothigh(high, lookback, lookback)
is_swing_low  = ta.pivotlow( low,  lookback, lookback)

// Dessiner les zones de résistance (Swing High)
if not na(is_swing_high)
    // Vérifier si la zone a déjà été cassée (zone "grise")
    was_broken = ta.highest(high, bar_index - (bar_index - lookback)) > is_swing_high
    zone_col = show_swept and was_broken ? col_swept : col_resistance

    box.new(bar_index - lookback, is_swing_high * 1.001,
            bar_index + zone_extend, is_swing_high * 0.999,
            bgcolor=zone_col, border_color=zone_col,
            border_width=1)

    // Label
    if not was_broken
        label.new(bar_index - lookback, is_swing_high,
                  "R — Liquidité", style=label.style_label_right,
                  color=color.new(color.red, 80),
                  textcolor=color.red, size=size.tiny)

// Dessiner les zones de support (Swing Low)
if not na(is_swing_low)
    was_broken = ta.lowest(low, bar_index - (bar_index - lookback)) < is_swing_low
    zone_col = show_swept and was_broken ? col_swept : col_support

    box.new(bar_index - lookback, is_swing_low * 1.001,
            bar_index + zone_extend, is_swing_low * 0.999,
            bgcolor=zone_col, border_color=zone_col,
            border_width=1)

    if not was_broken
        label.new(bar_index - lookback, is_swing_low,
                  "S — Liquidité", style=label.style_label_right,
                  color=color.new(color.green, 80),
                  textcolor=color.green, size=size.tiny)

// ── Détection Double Top / Double Bottom ──────────────────────
var float last_pivot_high = na
var float last_pivot_low  = na

if not na(is_swing_high)
    if not na(last_pivot_high)
        diff = math.abs(is_swing_high - last_pivot_high) / last_pivot_high
        if diff < 0.005  // Tolérance 0.5%
            level = (is_swing_high + last_pivot_high) / 2
            box.new(bar_index - lookback * 2, level * 1.003,
                    bar_index + zone_extend, level * 0.997,
                    bgcolor=col_double, border_color=col_double,
                    border_width=2)
            label.new(bar_index, level * 1.005,
                      "⚡ DOUBLE TOP — Haute Liquidité",
                      style=label.style_label_left,
                      color=color.new(color.orange, 70),
                      textcolor=color.orange, size=size.small)
    last_pivot_high := is_swing_high

if not na(is_swing_low)
    if not na(last_pivot_low)
        diff = math.abs(is_swing_low - last_pivot_low) / last_pivot_low
        if diff < 0.005
            level = (is_swing_low + last_pivot_low) / 2
            box.new(bar_index - lookback * 2, level * 1.003,
                    bar_index + zone_extend, level * 0.997,
                    bgcolor=col_double, border_color=col_double,
                    border_width=2)
            label.new(bar_index, level * 0.997,
                      "⚡ DOUBLE BOTTOM — Haute Liquidité",
                      style=label.style_label_left,
                      color=color.new(color.orange, 70),
                      textcolor=color.orange, size=size.small)
    last_pivot_low := is_swing_low

// ── Détection du SWEEP (alerte) ───────────────────────────────
// Sweep baissier (passage sous swing low puis clôture au-dessus)
sweep_bullish = not na(is_swing_low[1]) and
               low < is_swing_low[1] * 0.998 and
               close > is_swing_low[1]

// Sweep haussier (passage au-dessus swing high puis clôture en-dessous)
sweep_bearish = not na(is_swing_high[1]) and
               high > is_swing_high[1] * 1.002 and
               close < is_swing_high[1]

// Flèches de sweep
plotshape(sweep_bullish, style=shape.triangleup,
          location=location.belowbar,
          color=color.lime, size=size.normal,
          title="Sweep Haussier — Signal ACHAT potentiel")

plotshape(sweep_bearish, style=shape.triangledown,
          location=location.abovebar,
          color=color.red, size=size.normal,
          title="Sweep Baissier — Signal VENTE potentiel")

// ── Alertes ───────────────────────────────────────────────────
if alert_on_sweep
    if sweep_bullish
        alert("🟢 LIQUIDITY SWEEP HAUSSIER sur " + syminfo.ticker +
              " — Chercher ACHAT après confirmation", alert.freq_once_per_bar)
    if sweep_bearish
        alert("🔴 LIQUIDITY SWEEP BAISSIER sur " + syminfo.ticker +
              " — Chercher VENTE après confirmation", alert.freq_once_per_bar)
'''


def save_pinescript(output_path: str = "liquidity_zones.pine") -> str:
    """Sauvegarde l'indicateur Pine Script dans un fichier."""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(PINESCRIPT_LIQUIDITY_INDICATOR)
    return output_path
