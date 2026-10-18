"""
Moteur principal du bot de trading.
Orchestre le scan, le backtest et le paper trading.
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from core.config import Config
from core.data import DataFetcher
from core.indicators import Indicators as I
from core.risk import RiskManager, Position
from core.news_filter import EconomicCalendar
from core.notifier import TelegramNotifier
from core.journal import TradeJournal
from core.drawdown_guard import DrawdownGuard
from core.market_filter import MarketFilter, guess_asset_class
from core.pair_selector import print_ranking
from strategies.strategies import (
    Signal, BreakoutStrategy, CANSLIMStrategy,
    TurtleStrategy, MeanReversionStrategy
)
from strategies.patterns import (
    PullbackStrategy, BullFlagStrategy, DoubleBottomStrategy,
    InsideBarStrategy, OpeningRangeBreakoutStrategy
)
from strategies.bobby_variants import (
    SRMeanReversionStrategy, RangeChannelStrategy, SoftTrendPullbackStrategy
)


class TradingEngine:

    def __init__(self, config: Config):
        self.c       = config
        self.data    = DataFetcher(verbose=config.verbose)
        self.risk    = RiskManager(config)
        self.cash    = config.initial_capital
        self.positions: List[Position]  = []
        self.closed_trades: List[Position] = []

        # Initialiser les stratégies
        self.strategies = {}
        if config.strategy_filter in ('all', 'breakout'):
            self.strategies['breakout'] = BreakoutStrategy(config)
        if config.strategy_filter in ('all', 'canslim'):
            self.strategies['canslim'] = CANSLIMStrategy(config)
        if config.strategy_filter in ('all', 'turtle'):
            self.strategies['turtle'] = TurtleStrategy(config)
        if config.strategy_filter in ('all', 'mean_reversion'):
            self.strategies['mean_reversion'] = MeanReversionStrategy(config)
        if config.strategy_filter in ('all', 'pullback'):
            self.strategies['pullback'] = PullbackStrategy(config)
        if config.strategy_filter in ('all', 'bull_flag'):
            self.strategies['bull_flag'] = BullFlagStrategy(config)
        if config.strategy_filter in ('all', 'double_bottom'):
            self.strategies['double_bottom'] = DoubleBottomStrategy(config)
        if config.strategy_filter in ('all', 'inside_bar'):
            self.strategies['inside_bar'] = InsideBarStrategy(config)
        if config.strategy_filter in ('all', 'orb'):
            self.strategies['orb'] = OpeningRangeBreakoutStrategy(config)
        # Reconstructions "Bobby" : volontairement PAS incluses dans 'all'
        # tant qu'elles n'ont pas été backtestées (ce sont des hypothèses,
        # pas du code validé) — à sélectionner explicitement.
        if config.strategy_filter == 'sr_reversion':
            self.strategies['sr_reversion'] = SRMeanReversionStrategy(config)
        if config.strategy_filter == 'range_channel':
            self.strategies['range_channel'] = RangeChannelStrategy(config)
        if config.strategy_filter == 'soft_pullback':
            self.strategies['soft_pullback'] = SoftTrendPullbackStrategy(config)

        # ── Modules ajoutés : news, notifications, journal, drawdown ──
        self.news = EconomicCalendar(buffer_minutes=config.news_buffer_minutes,
                                      verbose=config.verbose)
        self.notifier = TelegramNotifier.from_credentials()
        self.journal = TradeJournal(csv_path=config.journal_csv_path)
        self.drawdown_guard = DrawdownGuard(
            daily_limit_pct=config.drawdown_daily_limit_pct,
            weekly_limit_pct=config.drawdown_weekly_limit_pct,
            max_consecutive_losses=config.max_consecutive_losses,
        )
        self.market_filter = MarketFilter(data_fetcher=self.data)
        self._trade_counter = 0
        self._df_cache: Dict[str, pd.DataFrame] = {}   # ticker -> DataFrame (corrélation, liquidité)

    # ────────────────────────────────────────────────────────────
    # CORRÉLATION & LIQUIDITÉ
    # ────────────────────────────────────────────────────────────

    def _correlation_fn(self, ticker_a: str, ticker_b: str) -> float:
        """Corrélation des rendements entre deux tickers, via le cache si possible."""
        df_a = self._df_cache.get(ticker_a) or self.data.get_ohlcv(ticker_a, period='6mo')
        df_b = self._df_cache.get(ticker_b) or self.data.get_ohlcv(ticker_b, period='6mo')
        if df_a is None or df_b is None:
            return 0.0
        return I.correlation(df_a['Close'], df_b['Close'], window=60)

    def _avg_volume(self, ticker: str, df: Optional[pd.DataFrame] = None) -> Optional[float]:
        """Volume moyen 20j d'un ticker, pour le contrôle de liquidité."""
        df = df if df is not None else self._df_cache.get(ticker)
        if df is None or 'Volume' not in df.columns or len(df) < 20:
            return None
        return float(df['Volume'].tail(20).mean())

    # ────────────────────────────────────────────────────────────
    # DISPATCH STRATÉGIES
    # ────────────────────────────────────────────────────────────

    def _generate_signal_for(self, strat_name: str, strat, ticker: str,
                              df: pd.DataFrame, market: str,
                              benchmark: Optional[pd.Series]) -> Optional[Signal]:
        """Point unique d'appel de chaque stratégie — évite la duplication
        du if/elif dans scan() et _paper_trading_cycle()."""
        if strat_name == 'breakout':
            return strat.generate_signal(ticker, df, market)
        elif strat_name == 'canslim':
            funds = self.data.get_fundamentals(ticker)
            return strat.generate_signal(ticker, df, funds, benchmark, market)
        elif strat_name == 'turtle':
            return strat.generate_signal(ticker, df)
        elif strat_name == 'mean_reversion':
            return strat.generate_signal(ticker, df, market)
        elif strat_name == 'pullback':
            return strat.generate_signal(ticker, df)
        elif strat_name == 'bull_flag':
            return strat.generate_signal(ticker, df)
        elif strat_name == 'double_bottom':
            return strat.generate_signal(ticker, df)
        elif strat_name == 'inside_bar':
            return strat.generate_signal(ticker, df)
        elif strat_name == 'orb':
            return strat.generate_signal(ticker, df)
        elif strat_name == 'sr_reversion':
            return strat.generate_signal(ticker, df)
        elif strat_name == 'range_channel':
            return strat.generate_signal(ticker, df)
        elif strat_name == 'soft_pullback':
            return strat.generate_signal(ticker, df)
        return None

    # ────────────────────────────────────────────────────────────
    # FILTRE MARCHÉ
    # ────────────────────────────────────────────────────────────

    def _get_market_condition(self) -> str:
        """
        Évalue la condition du marché en lisant SPY et QQQ.
        Règle 1 (PDF) : Si SPY & QQQ au-dessus EMA 8/21/50 → BULL
        Règle 2        : Si sous les EMA → BEAR
        Sinon          : NEUTRAL
        """
        bull_count = 0
        bear_count = 0

        for idx in self.c.market_indices:
            df = self.data.get_ohlcv(idx, period='6mo')
            if df is None or len(df) < 55:
                continue
            close = df['Close']
            e8    = I.ema(close, self.c.market_ema_short)
            e21   = I.ema(close, self.c.market_ema_mid)
            e50   = I.ema(close, self.c.market_ema_long)
            price = close.iloc[-1]
            if price > e8.iloc[-1] and price > e21.iloc[-1] and price > e50.iloc[-1]:
                bull_count += 1
            elif price < e8.iloc[-1] and price < e21.iloc[-1]:
                bear_count += 1

        if bull_count == len(self.c.market_indices):
            return 'BULL'
        elif bear_count >= 1:
            return 'BEAR'
        return 'NEUTRAL'

    # ────────────────────────────────────────────────────────────
    # SCAN
    # ────────────────────────────────────────────────────────────

    def scan(self):
        """Scanne toute la watchlist et affiche les meilleures opportunités."""
        print("📡 Analyse du contexte de marché...")
        market = self._get_market_condition()
        print(f"   → Condition marché : {'🟢 BULL' if market=='BULL' else '🔴 BEAR' if market=='BEAR' else '🟡 NEUTRAL'}\n")

        if market == 'BEAR':
            print("⚠️  Marché baissier — les stratégies Long sont désactivées.\n")

        if self.c.avoid_news:
            self.news.load()
            print(self.news.summary(hours_ahead=48) + "\n")

        print(f"🔍 Scan de {len(self.c.watchlist)} actions...\n")

        # Télécharger les données SPY pour le RS
        spy_df = self.data.get_ohlcv('SPY', period='1y')
        benchmark = spy_df['Close'] if spy_df is not None else None

        all_signals: List[Signal] = []

        for i, ticker in enumerate(self.c.watchlist):
            if self.c.verbose:
                print(f"  Analyse {ticker} ({i+1}/{len(self.c.watchlist)})...")

            df = self.data.get_ohlcv(ticker, period='1y')
            if df is None or len(df) < 60:
                continue
            self._df_cache[ticker] = df

            # Appliquer chaque stratégie active
            for strat_name, strat in self.strategies.items():
                try:
                    sig = self._generate_signal_for(strat_name, strat, ticker, df, market, benchmark)
                    if sig is None:
                        continue

                    if sig.strength >= 40:
                        all_signals.append(sig)
                except Exception as e:
                    if self.c.verbose:
                        print(f"    Erreur {ticker}/{strat_name}: {e}")

        # Trier par force décroissante
        all_signals.sort(key=lambda s: s.strength, reverse=True)

        # Affichage
        actionable = [s for s in all_signals if s.direction == 'LONG']
        watching   = [s for s in all_signals if not s.direction and s.strength >= 50]

        print(f"╔══════════════════════════════════════════════════════════╗")
        print(f"║  RÉSULTATS DU SCAN — {datetime.now().strftime('%d/%m/%Y %H:%M')}               ║")
        print(f"╚══════════════════════════════════════════════════════════╝\n")

        if actionable:
            print(f"🟢 SIGNAUX ACTIONNABLES ({len(actionable)} trouvés)")
            print("─" * 78)
            for sig in actionable[:10]:  # Top 10
                print(f"\n  {sig.ticker:<6} [{sig.strategy}] | Force : {sig.strength:.0f}/100")
                print(f"  {sig.reason}")
                print(f"  Entrée   : ${sig.entry:.2f}")
                print(f"  Stop Loss: ${sig.stop_loss:.2f}  ({(sig.stop_loss/sig.entry-1)*100:.1f}%)")
                print(f"  TP1      : ${sig.tp1:.2f}  (+{(sig.tp1/sig.entry-1)*100:.1f}%)")
                print(f"  TP2      : ${sig.tp2:.2f}  (+{(sig.tp2/sig.entry-1)*100:.1f}%)")
                print(f"  R/R      : {sig.risk_reward:.1f}:1")
                can_open, reason = self.risk.can_open_position(
                    sig, self.positions, self.cash, self.c.sector_map,
                    avg_daily_volume=self._avg_volume(sig.ticker),
                    correlation_fn=self._correlation_fn)
                if can_open and self.c.avoid_news:
                    blocked, event = self.news.is_blocked(sig.ticker)
                    if blocked:
                        can_open = False
                        reason = f"News à fort impact : {event.title} ({event.date.strftime('%H:%M UTC')})"
                shares = self.risk.calculate_position_size(sig, self.cash)
                shares = self.risk.cap_shares_by_liquidity(shares, self._avg_volume(sig.ticker))
                print(f"  Sizing   : {shares} actions (risque 1% = ${shares*abs(sig.entry-sig.stop_loss):.0f})")
                print(f"  {'✅ Eligible' if can_open else '❌ '+reason}")
                if self.c.verbose:
                    for check in sig.checklist:
                        print(f"    {check}")
        else:
            print("⏳ Aucun signal actionnable en ce moment — patientez.")

        if watching:
            print(f"\n🟡 EN SURVEILLANCE ({len(watching)} actions)\n")
            for sig in watching[:5]:
                dist = (sig.entry / (sig.tp1 / (1 + self.c.tp1_pct)) - 1) * 100
                print(f"  {sig.ticker:<6} [{sig.strategy}] | Force : {sig.strength:.0f}/100 | {sig.reason}")

        print(f"\n📊 Total analysé : {len(self.c.watchlist)} | Signaux : {len(all_signals)} | Actionnables : {len(actionable)}")

    # ────────────────────────────────────────────────────────────
    # SÉLECTION D'INSTRUMENT — principe tiré de la vidéo "Bobby"
    # (pas son edge, jamais révélé : sa philosophie de choix de paire)
    # ────────────────────────────────────────────────────────────

    def rank_pairs(self):
        """
        Classe la watchlist par affinité avec une approche de type
        range/mean-reversion : respect du support/résistance plutôt que
        tendance forcenée, volatilité modérée — voir core/pair_selector.py.
        Utile pour choisir où concentrer MeanReversionStrategy plutôt que
        Breakout/Turtle, qui eux préfèrent l'inverse (forte tendance).
        """
        print(f"\n🔍 Récupération des données pour {len(self.c.watchlist)} symboles...\n")
        symbol_dfs = {}
        for ticker in self.c.watchlist:
            df = self.data.get_ohlcv(ticker, period='1y')
            if df is not None and len(df) > 90:
                symbol_dfs[ticker] = df
        print_ranking(symbol_dfs)

    # ────────────────────────────────────────────────────────────
    # BACKTEST (simulation sur données historiques)
    # ────────────────────────────────────────────────────────────

    def _simulate_period(self, dates: List, tickers_data: Dict[str, pd.DataFrame],
                          benchmark_full: Optional[pd.Series],
                          fundamentals_cache: Dict[str, Dict]) -> Dict:
        """
        Cœur du simulateur, factorisé pour être réutilisé à la fois par
        backtest() (une seule fenêtre) et backtest_walk_forward() (plusieurs
        fenêtres indépendantes, pour valider la robustesse hors-échantillon
        sur différents régimes de marché).

        Retourne un dict de métriques + le détail des trades par stratégie.
        """
        cash = self.c.initial_capital
        trade_records: List[Dict] = []
        equity_curve = [cash]
        open_positions: List[Position] = []
        total_trades = 0
        wins = 0

        for date_idx, date in enumerate(dates):
            portfolio_value = cash + sum(
                p.current_price * p.shares for p in open_positions if p.status == 'OPEN'
            )
            equity_curve.append(portfolio_value)

            # ── Mettre à jour les prix et vérifier les sorties ──
            for pos in open_positions:
                if pos.status != 'OPEN':
                    continue
                df = tickers_data.get(pos.ticker)
                if df is None:
                    continue
                hist = df[df.index <= date]
                if len(hist) == 0:
                    continue
                current_price = hist['Close'].iloc[-1]
                pos.current_price = current_price

                exit_signal = self.risk.check_exits(pos, current_price)

                if exit_signal == 'STOP':
                    exit_reel = self.risk.estimate_fill_price(pos.stop_loss, 'SHORT')
                    pos.status     = 'CLOSED'
                    pos.exit_price = exit_reel
                    pos.exit_date  = date
                    pos.exit_reason = 'STOP LOSS'
                    remaining = pos.shares - pos.shares_sold_tp1 - pos.shares_sold_tp2
                    pnl = (pos.exit_price - pos.entry_price) * remaining - self.c.commission_per_trade
                    cash += pos.exit_price * remaining - self.c.commission_per_trade
                    trade_records.append({'strategy': pos.strategy, 'pnl': pnl})
                    total_trades += 1
                    if pnl > 0:
                        wins += 1
                elif exit_signal == 'TP1':
                    shares_to_sell = pos.shares // 4
                    pos.shares_sold_tp1 = shares_to_sell
                    cash += pos.tp1 * shares_to_sell
                    pos.partial_exits.append({'price': pos.tp1, 'shares': shares_to_sell, 'reason': 'TP1'})
                    pos.stop_loss = pos.entry_price  # break even
                elif exit_signal == 'TP2':
                    shares_to_sell = pos.shares // 4
                    pos.shares_sold_tp2 = shares_to_sell
                    cash += pos.tp2 * shares_to_sell
                    pos.partial_exits.append({'price': pos.tp2, 'shares': shares_to_sell, 'reason': 'TP2'})

            # ── Scanner les opportunités sur TOUTES les stratégies actives ──
            for ticker, df in tickers_data.items():
                hist = df[df.index <= date]
                if len(hist) < 60:
                    continue
                already_in = any(p.ticker == ticker and p.status == 'OPEN' for p in open_positions)
                if already_in:
                    continue

                benchmark_hist = benchmark_full[benchmark_full.index <= date] if benchmark_full is not None else None
                candidate_signals = []

                for strat_name, strat in self.strategies.items():
                    try:
                        if strat_name == 'canslim':
                            funds = fundamentals_cache.get(ticker, {})
                            sig = strat.generate_signal(ticker, hist, funds, benchmark_hist, 'BULL')
                        else:
                            sig = self._generate_signal_for(strat_name, strat, ticker, hist, 'BULL', benchmark_hist)
                        if sig is not None and sig.direction == 'LONG' and sig.strength >= 60:
                            candidate_signals.append(sig)
                    except Exception:
                        continue

                if not candidate_signals:
                    continue

                # Si plusieurs stratégies signalent le même ticker le même jour,
                # ne retenir que la plus forte (évite le double comptage de risque).
                sig = max(candidate_signals, key=lambda s: s.strength)

                def _bt_correlation_fn(t_a: str, t_b: str, _date=date) -> float:
                    df_a = tickers_data.get(t_a)
                    df_b = tickers_data.get(t_b)
                    if df_a is None or df_b is None:
                        return 0.0
                    ha = df_a[df_a.index <= _date]
                    hb = df_b[df_b.index <= _date]
                    if len(ha) < 20 or len(hb) < 20:
                        return 0.0
                    return I.correlation(ha['Close'], hb['Close'], window=60)

                avg_vol = float(hist['Volume'].tail(20).mean()) if len(hist) >= 20 else None

                can_open, _ = self.risk.can_open_position(
                    sig, open_positions, cash, self.c.sector_map,
                    avg_daily_volume=avg_vol, correlation_fn=_bt_correlation_fn)
                if not can_open:
                    continue

                shares = self.risk.calculate_position_size(sig, cash)
                shares = self.risk.cap_shares_by_liquidity(shares, avg_vol)
                entry_reel = self.risk.estimate_fill_price(sig.entry, 'LONG')
                if shares > 0 and entry_reel * shares <= cash:
                    cost = entry_reel * shares + self.c.commission_per_trade
                    cash -= cost
                    pos = Position(
                        ticker=ticker, strategy=sig.strategy,
                        direction='LONG', entry_price=entry_reel,
                        shares=shares, stop_loss=sig.stop_loss,
                        tp1=sig.tp1, tp2=sig.tp2,
                        entry_date=date, current_price=entry_reel
                    )
                    open_positions.append(pos)

        # Clore les positions restantes
        for pos in open_positions:
            if pos.status == 'OPEN':
                df = tickers_data.get(pos.ticker)
                if df is not None:
                    final_price = self.risk.estimate_fill_price(df['Close'].iloc[-1], 'SHORT')
                    remaining = pos.shares - pos.shares_sold_tp1 - pos.shares_sold_tp2
                    cash += final_price * remaining - self.c.commission_per_trade
                    pnl = (final_price - pos.entry_price) * remaining - self.c.commission_per_trade
                    trade_records.append({'strategy': pos.strategy, 'pnl': pnl})
                    total_trades += 1
                    if pnl > 0:
                        wins += 1

        # ── Métriques ──────────────────────────────────────────
        trades = [t['pnl'] for t in trade_records]
        final_equity = cash
        total_return = (final_equity / self.c.initial_capital - 1) * 100
        win_rate     = (wins / total_trades * 100) if total_trades > 0 else 0

        peak = self.c.initial_capital
        max_dd = 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100
            max_dd = max(max_dd, dd)

        win_trades  = [t for t in trades if t > 0]
        loss_trades = [t for t in trades if t < 0]
        avg_win  = np.mean(win_trades) if win_trades else 0
        avg_loss = np.mean(loss_trades) if loss_trades else 0
        gross_profit = sum(win_trades)
        gross_loss   = abs(sum(loss_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0

        by_strategy: Dict[str, List[float]] = {}
        for t in trade_records:
            by_strategy.setdefault(t['strategy'], []).append(t['pnl'])

        return {
            'final_equity': final_equity, 'total_return': total_return,
            'total_trades': total_trades, 'wins': wins, 'win_rate': win_rate,
            'avg_win': avg_win, 'avg_loss': avg_loss,
            'profit_factor': profit_factor, 'max_dd': max_dd,
            'by_strategy': by_strategy,
            'start_date': dates[0] if dates else None,
            'end_date': dates[-1] if dates else None,
        }

    def _print_period_report(self, r: Dict, title: str):
        pf_display = "∞" if r['profit_factor'] == float('inf') else f"{r['profit_factor']:.2f}"
        print(f"╔══════════════════════════════════════════════════════════╗")
        print(f"║  {title:<58}║")
        print(f"╚══════════════════════════════════════════════════════════╝")
        print(f"  Capital initial      : ${self.c.initial_capital:>12,.0f}")
        print(f"  Capital final        : ${r['final_equity']:>12,.0f}")
        print(f"  Rendement total      : {r['total_return']:>+11.1f}%")
        print(f"  ─────────────────────────────────────────────")
        print(f"  Trades totaux        : {r['total_trades']:>12}")
        print(f"  Trades gagnants      : {r['wins']:>12}")
        print(f"  Win Rate             : {r['win_rate']:>11.1f}%")
        print(f"  ─────────────────────────────────────────────")
        print(f"  Gain moyen           : ${r['avg_win']:>11,.0f}")
        print(f"  Perte moyenne        : ${r['avg_loss']:>11,.0f}")
        print(f"  Profit Factor        : {pf_display:>12}")
        print(f"  Max Drawdown         : {r['max_dd']:>11.1f}%")

        by_strategy = r['by_strategy']
        if len(by_strategy) > 1:
            print(f"\n  ─── Détail par stratégie ──────────────────────")
            print(f"  {'Stratégie':<28} {'Trades':>7} {'WinRate':>8} {'PnL net':>12} {'Fiabilité':>12}")
            for strat_name, pnls in sorted(by_strategy.items(), key=lambda x: -sum(x[1])):
                n = len(pnls)
                wr = sum(1 for p in pnls if p > 0) / n * 100 if n else 0
                net = sum(pnls)
                fiabilite = "FIABLE" if n >= 50 else "FAIBLE" if n >= 25 else "INSUFFISANT"
                print(f"  {strat_name:<28} {n:>7} {wr:>7.1f}% ${net:>+10,.0f} {fiabilite:>12}")

    def backtest(self, days: int = 252):
        """
        Simule TOUTES les stratégies actives sur les N derniers jours
        (celles listées dans self.strategies — dépend de config.strategy_filter).

        ⚠️ Limitations connues, à garder à l'esprit en lisant les résultats :
        - Univers fixe (watchlist actuelle) -> biais de survivance possible.
        - CANSLIM : les fondamentaux sont récupérés une seule fois (valeur
          actuelle), pas reconstitués historiquement -> approximatif.
        - Une seule fenêtre temporelle ici : utilisez backtest_walk_forward()
          pour valider la robustesse sur plusieurs régimes de marché.
        """
        print(f"📈 Backtest sur {days} jours de trading...")
        print(f"   Stratégies testées : {', '.join(s.name if hasattr(s, 'name') else n for n, s in self.strategies.items())}")
        print(f"   Slippage supposé : {self.c.slippage_pct}% | Commission : ${self.c.commission_per_trade}/trade\n")

        tickers_data = self.data.get_multiple(self.c.watchlist[:20], period='2y')
        spy_df = self.data.get_ohlcv('SPY', period='2y')
        benchmark_full = spy_df['Close'] if spy_df is not None else None

        if not tickers_data:
            print("❌ Impossible de charger les données pour le backtest.")
            return

        fundamentals_cache: Dict[str, Dict] = {}
        if 'canslim' in self.strategies:
            for ticker in tickers_data:
                fundamentals_cache[ticker] = self.data.get_fundamentals(ticker)

        all_dates = sorted(spy_df.index) if spy_df is not None else []
        start_idx = max(0, len(all_dates) - days)
        dates = all_dates[start_idx + 60:]   # 60 premiers jours = warm-up indicateurs

        r = self._simulate_period(dates, tickers_data, benchmark_full, fundamentals_cache)
        self._print_period_report(r, f"RÉSULTATS DU BACKTEST ({days} jours) — TOUTES STRATÉGIES")

        print(f"\n⚠️  Résultats historiques — ne garantissent pas les performances futures.")
        print(f"⚠️  Une seule fenêtre temporelle : lancez aussi --mode backtest-wf "
              f"pour un test hors-échantillon sur plusieurs régimes de marché.")

    def backtest_walk_forward(self, fold_days: int = 126, n_folds: int = 4):
        """
        Découpe l'historique disponible en `n_folds` fenêtres consécutives
        et indépendantes de `fold_days` jours chacune, puis lance une
        simulation complète sur chaque fenêtre séparément.

        Objectif : vérifier que la stratégie n'est pas simplement "chanceuse"
        sur une seule période, mais reste cohérente à travers différents
        régimes de marché (haussier/baissier/latéral). Chaque fold démarre
        avec un capital neuf (pas de compounding entre folds) pour que les
        résultats restent comparables entre eux.

        ⚠️ Ce n'est pas un walk-forward au sens "optimisation de paramètres
        sur le passé puis validation sur le futur" (les stratégies ici sont
        des règles fixes, pas des modèles entraînés) — c'est un test de
        robustesse multi-période / multi-régime, ce qui est la vérification
        pertinente pour ce type de stratégie.
        """
        total_days_needed = fold_days * n_folds + 60
        print(f"📈 Backtest Walk-Forward : {n_folds} fenêtres de {fold_days} jours "
              f"(indépendantes, capital ré-initialisé à chaque fenêtre)\n")

        period = '2y' if total_days_needed <= 500 else '5y'
        tickers_data = self.data.get_multiple(self.c.watchlist[:20], period=period)
        spy_df = self.data.get_ohlcv('SPY', period=period)
        benchmark_full = spy_df['Close'] if spy_df is not None else None

        if not tickers_data or spy_df is None:
            print("❌ Impossible de charger les données pour le backtest walk-forward.")
            return

        fundamentals_cache: Dict[str, Dict] = {}
        if 'canslim' in self.strategies:
            for ticker in tickers_data:
                fundamentals_cache[ticker] = self.data.get_fundamentals(ticker)

        all_dates = sorted(spy_df.index)
        if len(all_dates) < total_days_needed:
            print(f"⚠️  Seulement {len(all_dates)} jours de données disponibles "
                  f"(besoin de {total_days_needed}) — réduction du nombre/de la taille des folds.")
            n_folds = max(1, (len(all_dates) - 60) // fold_days)

        results = []
        for fold_idx in range(n_folds):
            end_offset = len(all_dates) - fold_idx * fold_days
            start_offset = max(60, end_offset - fold_days)
            fold_dates = all_dates[start_offset:end_offset]
            if len(fold_dates) < 30:
                continue

            r = self._simulate_period(fold_dates, tickers_data, benchmark_full, fundamentals_cache)
            results.append(r)
            label = f"Fold {n_folds - fold_idx} ({fold_dates[0].strftime('%Y-%m-%d')} → {fold_dates[-1].strftime('%Y-%m-%d')})"
            self._print_period_report(r, label)
            print()

        if not results:
            print("❌ Aucun fold n'a pu être simulé (données insuffisantes).")
            return

        # ── Synthèse de robustesse ─────────────────────────────
        returns  = [r['total_return'] for r in results]
        pfs      = [r['profit_factor'] for r in results if r['profit_factor'] != float('inf')]
        win_rates = [r['win_rate'] for r in results if r['total_trades'] > 0]
        max_dds  = [r['max_dd'] for r in results]
        profitable_folds = sum(1 for r in returns if r > 0)

        print(f"╔══════════════════════════════════════════════════════════╗")
        print(f"║  SYNTHÈSE DE ROBUSTESSE — {len(results)} FOLDS INDÉPENDANTS{'':<15}║")
        print(f"╚══════════════════════════════════════════════════════════╝")
        print(f"  Folds profitables    : {profitable_folds}/{len(results)}")
        print(f"  Rendement moyen      : {np.mean(returns):>+11.1f}%")
        print(f"  Rendement médian     : {np.median(returns):>+11.1f}%")
        print(f"  Rendement min/max    : {min(returns):>+.1f}% / {max(returns):>+.1f}%")
        if win_rates:
            print(f"  Win Rate moyen       : {np.mean(win_rates):>11.1f}%")
        if pfs:
            print(f"  Profit Factor moyen  : {np.mean(pfs):>11.2f}")
        print(f"  Max Drawdown (pire)  : {max(max_dds):>11.1f}%")

        if profitable_folds < len(results):
            print(f"\n  ⚠️  La stratégie n'est PAS profitable sur tous les régimes testés "
                  f"({len(results) - profitable_folds} fold(s) perdant(s)).")
            print(f"      Cela peut indiquer une dépendance excessive à un contexte de "
                  f"marché particulier (ex: bull market) plutôt qu'un edge robuste.")
        else:
            print(f"\n  ✅ Profitable sur les {len(results)} fenêtres testées — "
                  f"signe encourageant, mais reste à confirmer sur plus de données/temps réel.")

        print(f"\n⚠️  Chaque fold est indépendant (capital réinitialisé) — ceci mesure la "
              f"cohérence de l'edge, pas la performance cumulée réelle sur la période totale.")

    # ────────────────────────────────────────────────────────────
    # PAPER TRADING (boucle live)
    # ────────────────────────────────────────────────────────────

    def run_paper_trading(self, interval_minutes: int = 60):
        """
        Lance la boucle de paper trading.
        Scanne le marché toutes les N minutes, exécute les signaux.
        """
        print(f"🤖 Paper Trading démarré | Rafraîchissement : {interval_minutes}min\n")
        print("   Appuyez sur Ctrl+C pour arrêter.\n")

        try:
            while True:
                portfolio_value = self.cash + sum(
                    p.current_price * (p.shares - p.shares_sold_tp1 - p.shares_sold_tp2)
                    for p in self.positions if p.status == 'OPEN'
                )
                allowed, reason = self.drawdown_guard.check(portfolio_value)
                if not allowed:
                    print(f"\n⛔ {reason}")
                    self.notifier.notify_pause(reason)
                    print(f"⏱  Nouvelle vérification dans {interval_minutes} minutes...\n")
                    time.sleep(interval_minutes * 60)
                    continue

                self._paper_trading_cycle()
                self.print_report()
                self.journal.print_summary()
                print(f"\n⏱  Prochain scan dans {interval_minutes} minutes...\n")
                time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            print("\n\n⛔ Paper trading arrêté.")
            self.print_report()
            self.journal.print_summary()

    def _paper_trading_cycle(self):
        """Un cycle complet : mise à jour positions + scan nouveaux signaux."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{timestamp}] ─── Cycle de trading ───────────────────────")

        market = self._get_market_condition()
        spy_df = self.data.get_ohlcv('SPY', period='1y')
        benchmark = spy_df['Close'] if spy_df is not None else None

        if self.c.avoid_news:
            self.news.load()  # utilise le cache si < 6h, sinon rafraîchit

        # 1. Mettre à jour les positions ouvertes
        for pos in self.positions:
            if pos.status != 'OPEN':
                continue
            df = self.data.get_ohlcv(pos.ticker, period='3mo')
            if df is None:
                continue

            current_price = df['Close'].iloc[-1]
            pos.current_price = current_price

            # EMA pour trailing stop
            e8  = I.ema(df['Close'], 8).iloc[-1]
            e21 = I.ema(df['Close'], 21).iloc[-1]
            self.risk.update_trailing_stop(pos, e8, e21)

            exit_signal = self.risk.check_exits(pos, current_price)

            if exit_signal == 'STOP':
                remaining = pos.shares - pos.shares_sold_tp1 - pos.shares_sold_tp2
                self.cash += pos.stop_loss * remaining
                pos.status     = 'CLOSED'
                pos.exit_price = pos.stop_loss
                pos.exit_date  = datetime.now()
                pos.exit_reason = 'STOP LOSS'
                self.closed_trades.append(pos)
                pnl = pos.realized_pnl
                print(f"  🔴 SORTIE STOP   {pos.ticker} | PnL: ${pnl:+,.0f} ({(pos.exit_price/pos.entry_price-1)*100:+.1f}%)")
                self.notifier.notify_trade_closed(pos.ticker, pnl, pos.pnl_pct, 'STOP LOSS')
                self.journal.log_trade(
                    trade_id=f"{pos.ticker}_{pos.entry_date.strftime('%Y%m%d%H%M%S')}",
                    ticker=pos.ticker, strategy=pos.strategy, direction=pos.direction,
                    entry_date=pos.entry_date, entry_price=pos.entry_price, shares=pos.shares,
                    exit_date=pos.exit_date, exit_price=pos.exit_price, exit_reason=pos.exit_reason,
                    stop_loss=pos.stop_loss, tp1=pos.tp1, tp2=pos.tp2, pnl=pnl, status='CLOSED')
                self.drawdown_guard.record_trade_result(pnl)

            elif exit_signal == 'TP1':
                shares_to_sell = max(1, pos.shares // 4)
                pos.shares_sold_tp1 = shares_to_sell
                self.cash += pos.tp1 * shares_to_sell
                pos.partial_exits.append({'price': pos.tp1, 'shares': shares_to_sell, 'reason': 'TP1'})
                pos.stop_loss = pos.entry_price
                print(f"  🟡 TP1 PARTIEL   {pos.ticker} | -{shares_to_sell} actions @ ${pos.tp1:.2f} | SL → Break Even")

            elif exit_signal == 'TP2':
                shares_to_sell = max(1, pos.shares // 4)
                pos.shares_sold_tp2 = shares_to_sell
                self.cash += pos.tp2 * shares_to_sell
                pos.partial_exits.append({'price': pos.tp2, 'shares': shares_to_sell, 'reason': 'TP2'})
                print(f"  🟢 TP2 PARTIEL   {pos.ticker} | -{shares_to_sell} actions @ ${pos.tp2:.2f} | Trailing stop actif")

        # 2. Scanner de nouveaux signaux
        if market != 'BEAR':
            for ticker in self.c.watchlist[:15]:  # Sous-ensemble pour la vitesse
                df = self.data.get_ohlcv(ticker, period='1y')
                if df is None:
                    continue
                self._df_cache[ticker] = df
                for strat_name, strat in self.strategies.items():
                    try:
                        sig = self._generate_signal_for(strat_name, strat, ticker, df, market, benchmark)
                        if sig is None:
                            continue

                        if sig.direction == 'LONG' and sig.strength >= 65:
                            can_open, reason = self.risk.can_open_position(
                                sig, self.positions, self.cash, self.c.sector_map,
                                avg_daily_volume=self._avg_volume(ticker, df),
                                correlation_fn=self._correlation_fn)

                            if can_open and self.c.avoid_news:
                                blocked, event = self.news.is_blocked(ticker)
                                if blocked:
                                    can_open = False
                                    print(f"  📅 {ticker} bloqué — news {event.title} @ {event.date.strftime('%H:%M UTC')}")
                                    self.notifier.notify_news_block(ticker, event.title, event.date.strftime('%H:%M UTC'))

                            if can_open:
                                entry_reel = self.risk.estimate_fill_price(sig.entry, 'LONG')
                                shares = self.risk.calculate_position_size(sig, self.cash)
                                shares = self.risk.cap_shares_by_liquidity(shares, self._avg_volume(ticker, df))
                                if shares > 0:
                                    cost = entry_reel * shares + self.c.commission_per_trade
                                    self.cash -= cost
                                    self._trade_counter += 1
                                    entry_dt = datetime.now()
                                    pos = Position(
                                        ticker=ticker, strategy=sig.strategy,
                                        direction='LONG', entry_price=entry_reel,
                                        shares=shares, stop_loss=sig.stop_loss,
                                        tp1=sig.tp1, tp2=sig.tp2,
                                        entry_date=entry_dt,
                                        current_price=entry_reel
                                    )
                                    self.positions.append(pos)
                                    print(f"  🟢 ACHAT         {ticker} | {sig.strategy}")
                                    print(f"     {shares} actions @ ${entry_reel:.2f} (slippage inclus) | "
                                          f"SL ${sig.stop_loss:.2f} | TP1 ${sig.tp1:.2f} | R/R {sig.risk_reward:.1f}:1")
                                    self.notifier.notify_trade_opened(
                                        ticker, sig.strategy, 'LONG', shares, entry_reel, sig.stop_loss, sig.tp1)
                                    self.journal.log_trade(
                                        trade_id=f"{ticker}_{entry_dt.strftime('%Y%m%d%H%M%S')}",
                                        ticker=ticker, strategy=sig.strategy, direction='LONG',
                                        entry_date=entry_dt, entry_price=entry_reel, shares=shares,
                                        stop_loss=sig.stop_loss, tp1=sig.tp1, tp2=sig.tp2, status='OPEN')
                    except Exception as e:
                        logger_msg = f"{strat_name}/{ticker}: {e}"
                        if self.c.verbose:
                            print(f"    Erreur {logger_msg}")

    # ────────────────────────────────────────────────────────────
    # RAPPORT DE PERFORMANCE
    # ────────────────────────────────────────────────────────────

    def print_report(self):
        """Affiche le rapport complet du portfolio."""
        open_pos  = [p for p in self.positions if p.status == 'OPEN']
        closed    = self.closed_trades + [p for p in self.positions if p.status == 'CLOSED']

        portfolio_value = self.cash + sum(p.current_price * (p.shares - p.shares_sold_tp1 - p.shares_sold_tp2) for p in open_pos)
        total_return    = (portfolio_value / self.c.initial_capital - 1) * 100
        unrealized_pnl  = sum(p.unrealized_pnl for p in open_pos)

        print(f"\n╔══════════════════════════════════════════════════════════╗")
        print(f"║  RAPPORT PORTFOLIO — {datetime.now().strftime('%d/%m/%Y %H:%M')}              ║")
        print(f"╚══════════════════════════════════════════════════════════╝")
        print(f"  Capital initial      : ${self.c.initial_capital:>12,.0f}")
        print(f"  Liquidités           : ${self.cash:>12,.0f}")
        print(f"  Valeur portfolio     : ${portfolio_value:>12,.0f}")
        print(f"  Rendement total      : {total_return:>+11.1f}%")
        print(f"  PnL non réalisé      : ${unrealized_pnl:>+11,.0f}")

        if open_pos:
            print(f"\n  📂 POSITIONS OUVERTES ({len(open_pos)})")
            print(f"  {'Ticker':<8} {'Stratégie':<22} {'Shares':<7} {'Entrée':>8} {'Prix':<10} {'PnL':>10} {'%':>7} {'SL':>8}")
            print("  " + "─" * 80)
            for p in open_pos:
                remaining = p.shares - p.shares_sold_tp1 - p.shares_sold_tp2
                pnl = p.unrealized_pnl
                pct = p.pnl_pct
                icon = '🟢' if pnl >= 0 else '🔴'
                print(f"  {icon} {p.ticker:<6} {p.strategy:<22} {remaining:<7} "
                      f"${p.entry_price:>7.2f}  ${p.current_price:<9.2f} "
                      f"${pnl:>+9,.0f} {pct:>+6.1f}%  ${p.stop_loss:.2f}")

        if closed:
            wins   = [p for p in closed if p.realized_pnl > 0]
            losses = [p for p in closed if p.realized_pnl <= 0]
            total_realized = sum(p.realized_pnl for p in closed)
            win_rate = len(wins) / len(closed) * 100 if closed else 0

            print(f"\n  📊 TRADES FERMÉS ({len(closed)})")
            print(f"  Win Rate   : {win_rate:.0f}%  ({len(wins)} gagnants / {len(losses)} perdants)")
            print(f"  PnL total  : ${total_realized:>+,.0f}")
            if wins:
                avg_win = np.mean([p.realized_pnl for p in wins])
                print(f"  Gain moyen : ${avg_win:>,.0f}")
            if losses:
                avg_loss = np.mean([p.realized_pnl for p in losses])
                print(f"  Perte moy. : ${avg_loss:>,.0f}")

            print(f"\n  Derniers trades :")
            for p in closed[-5:]:
                pnl  = p.realized_pnl
                icon = '✅' if pnl > 0 else '❌'
                print(f"  {icon} {p.ticker:<6} {p.strategy:<22} | "
                      f"Entrée ${p.entry_price:.2f} → Sortie ${p.exit_price:.2f} | "
                      f"PnL ${pnl:>+,.0f} | {p.exit_reason}")

        print(f"\n  🛡️  Drawdown Guard : {self.drawdown_guard.status}")
        print(f"\n⚠️  Paper Trading uniquement — aucun ordre réel n'a été passé.")
