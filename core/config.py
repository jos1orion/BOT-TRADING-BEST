"""
Configuration centrale du bot de trading.
Modifiez ce fichier pour adapter le bot à votre style.
"""

from dataclasses import dataclass, field
from typing import List, Dict

@dataclass
class Config:
    # ── Capital & Risk ─────────────────────────────────────
    initial_capital: float = 10_000.0
    risk_per_trade: float  = 0.01        # 1% du capital risqué par trade
    max_positions: int     = 8            # Maximum de positions simultanées
    max_sector_exposure: float = 0.30    # Max 30% dans un seul secteur

    # ── Filtres de marché ──────────────────────────────────
    market_ema_short: int  = 8
    market_ema_mid: int    = 21
    market_ema_long: int   = 50
    market_indices: List[str] = field(default_factory=lambda: ['SPY', 'QQQ'])

    # ── Critères screener (comme dans le PDF) ─────────────
    min_price: float       = 3.0          # Prix minimum
    min_market_cap: float  = 3e8          # 300M$ minimum
    min_avg_volume: int    = 500_000      # Volume quotidien min
    min_adr_pct: float     = 3.0          # ADR > 3%

    # ── Take Profit (Scale Out) ────────────────────────────
    tp1_pct: float         = 0.10         # +10% → vendre 25%
    tp2_pct: float         = 0.20         # +20% → vendre 25% de plus
    # Les 50% restants suivis par EMA 8/21

    # ── Stop Loss ─────────────────────────────────────────
    atr_stop_multiplier: float = 2.0      # Stop à 2×ATR (style Turtle)
    breakout_sl_type: str  = 'candle_low' # 'candle_low' | 'atr'

    # ── Stratégie activée ─────────────────────────────────
    strategy_filter: str   = 'all'        # 'all' | 'breakout' | 'canslim' | 'turtle' | 'mean_reversion'
    #                                        | 'pullback' | 'bull_flag' | 'double_bottom'
    #                                        | 'inside_bar' | 'orb'
    #                                        | 'sr_reversion' | 'range_channel' | 'soft_pullback'  (reconstructions "Bobby")

    # ── Protection Drawdown (kill-switch) ──────────────────
    drawdown_daily_limit_pct:  float = 3.0   # Pause si -3% sur la journée
    drawdown_weekly_limit_pct: float = 6.0   # Pause si -6% sur la semaine
    max_consecutive_losses:    int   = 5     # Pause après N pertes d'affilée

    # ── Slippage (exécution réaliste) ──────────────────────
    slippage_pct: float = 0.05            # 0.05% de glissement supposé à l'entrée/sortie
    commission_per_trade: float = 0.0     # $ par trade (0 = courtier sans commission)

    # ── Filtre d'actualités économiques ───────────────────
    avoid_news: bool          = True
    news_buffer_minutes: int  = 30        # Bloque les trades ±30 min autour d'une news à fort impact

    # ── Notifications Telegram ─────────────────────────────
    telegram_enabled: bool = False        # Surchargé par broker_credentials.TELEGRAM_CONFIG si présent

    # ── Corrélation entre positions ────────────────────────
    correlation_threshold: float     = 0.70   # Seuil au-delà duquel 2 actifs sont "corrélés"
    max_correlated_positions: int    = 2      # Max de positions ouvertes simultanément sur des actifs corrélés

    # ── Liquidité vs taille d'ordre ────────────────────────
    max_volume_participation_pct: float = 2.0  # Ne jamais représenter plus de 2% du volume moyen 20j

    # ── Journal de trading ─────────────────────────────────
    journal_csv_path: str = "trading_journal.csv"

    # ── Paramètres par stratégie ──────────────────────────

    # Breakout Momentum (ton document)
    breakout_volume_multiplier: float = 1.5   # Volume ≥ 1.5× la moyenne
    consolidation_days: int = 10              # Jours de consolidation minimum

    # CANSLIM
    canslim_min_eps_growth: float = 25.0      # Croissance EPS min 25%
    canslim_min_rs_rating: int    = 80        # RS Rating minimum

    # Trend Following (Turtle)
    turtle_donchian_s1: int   = 20            # Canal Donchian S1 (entrée)
    turtle_donchian_s2: int   = 55            # Canal Donchian S2 (entrée)
    turtle_exit_s1: int       = 10            # Sortie S1
    turtle_exit_s2: int       = 20            # Sortie S2
    turtle_atr_period: int    = 20            # Période ATR pour sizing
    turtle_unit_risk: float   = 0.01          # Risque par unité = 1%
    turtle_max_units: int     = 4             # Unités max par marché

    # Mean Reversion
    bb_period: int            = 20            # Période Bollinger
    bb_std: float             = 2.0           # Écarts-types
    rsi_period: int           = 14            # Période RSI
    rsi_oversold: int         = 30            # Survente
    rsi_overbought: int       = 70            # Surachat

    # ── Reconstructions "façon Bobby" (S/R, range, pullback doux) ──
    # ⚠️ Ce sont des hypothèses de reconstruction à partir de stats
    # publiques d'un robot tiers, pas sa logique réelle (jamais
    # révélée) — à valider par backtest avant tout usage réel.
    srrev_lookback: int          = 40    # Fenêtre de détection des niveaux S/R
    srrev_touch_tolerance_pct: float = 0.15  # Tolérance (%) pour juger un prix "sur" le niveau
    srrev_adx_max: float         = 25    # Range uniquement (pas de tendance forte)

    range_donchian_period: int  = 20     # Canal Donchian (bornes du range)
    range_adx_max: float         = 20    # Range strict requis

    pullback_ema_fast: int      = 21
    pullback_ema_slow: int      = 55
    pullback_adx_min: float      = 15    # Tendance molle minimum...
    pullback_adx_max: float      = 30    # ...mais pas une tendance forte (sinon Turtle est plus adapté)

    # ── Univers d'actions ─────────────────────────────────
    verbose: bool = False

    @property
    def watchlist(self) -> List[str]:
        """
        Univers d'actions surveillées.
        Mix de leaders tech, semi-conducteurs, biotech, finance, conso.
        Inspiré des exemples du PDF ($MU, $ARM, $NBIS, $RKLB...).
        """
        return [
            # Semi-conducteurs (secteur fort)
            'NVDA', 'AMD', 'MU', 'ARM', 'AVGO', 'AMAT', 'LRCX', 'KLAC',
            # Tech / Cloud
            'MSFT', 'GOOGL', 'META', 'AMZN', 'CRM', 'NOW', 'SNOW',
            # Défense / Espace
            'RKLB', 'AXON', 'LHX', 'NOC',
            # Biotech / MedTech
            'NBIS', 'ABBV', 'LLY', 'ISRG',
            # Finance
            'GS', 'JPM', 'V', 'MA',
            # Énergie / Matières premières
            'XOM', 'CVX', 'FCX',
            # Consumer
            'AAPL', 'TSLA', 'NKE',
        ]

    @property
    def sector_map(self) -> Dict[str, str]:
        return {
            'NVDA':'Semi-conducteurs','AMD':'Semi-conducteurs','MU':'Semi-conducteurs',
            'ARM':'Semi-conducteurs','AVGO':'Semi-conducteurs','AMAT':'Semi-conducteurs',
            'LRCX':'Semi-conducteurs','KLAC':'Semi-conducteurs',
            'MSFT':'Tech','GOOGL':'Tech','META':'Tech','AMZN':'Tech',
            'CRM':'Tech','NOW':'Tech','SNOW':'Tech',
            'RKLB':'Défense/Espace','AXON':'Défense/Espace','LHX':'Défense/Espace','NOC':'Défense/Espace',
            'NBIS':'Biotech','ABBV':'Biotech','LLY':'Biotech','ISRG':'Biotech',
            'GS':'Finance','JPM':'Finance','V':'Finance','MA':'Finance',
            'XOM':'Énergie','CVX':'Énergie','FCX':'Matières premières',
            'AAPL':'Consumer','TSLA':'Consumer','NKE':'Consumer',
        }
