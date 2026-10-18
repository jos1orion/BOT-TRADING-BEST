"""
╔══════════════════════════════════════════════════════════════╗
║            TRADING BOT — Multi-Stratégie                     ║
║  Breakout | CANSLIM | Trend Following | Mean Reversion       ║
║                                                              ║
║  ⚠️  MODE PAPER TRADING UNIQUEMENT                           ║
║  Ce bot est à but éducatif. Il ne constitue pas un conseil  ║
║  en investissement. N'utilisez jamais de l'argent réel      ║
║  sans backtests rigoureux et validation professionnelle.    ║
╚══════════════════════════════════════════════════════════════╝
"""

import argparse
import sys
from core.engine import TradingEngine
from core.config import Config

def main():
    parser = argparse.ArgumentParser(
        description="Multi-Strategy Trading Bot (Paper Trading)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python main.py --mode scan                    # Scanner les meilleures opportunités
  python main.py --mode backtest --days 365     # Backtester sur 1 an
  python main.py --mode backtest-wf              # Backtest walk-forward (4 fenêtres indépendantes)
  python main.py --mode paper                   # Démarrer le paper trading live
  python main.py --mode report                  # Afficher le rapport de performance
  python main.py --mode journal                  # Exporter le journal de trading (Excel/CSV)
  python main.py --mode rank-pairs                # Classer la watchlist par affinité "range" (style Bobby)
  python main.py --strategy breakout --mode scan
        """
    )
    parser.add_argument('--mode',     choices=['scan','backtest','backtest-wf','paper','report','journal','rank-pairs'], default='scan')
    parser.add_argument('--strategy', choices=['all','breakout','canslim','turtle','mean_reversion',
                                                 'pullback','bull_flag','double_bottom','inside_bar','orb',
                                                 'sr_reversion','range_channel','soft_pullback'], default='all')
    parser.add_argument('--days',     type=int, default=252, help='Jours pour le backtest (défaut: 252 = 1 an)')
    parser.add_argument('--fold-days', type=int, default=126, help='Jours par fenêtre pour backtest-wf (défaut: 126 = 6 mois)')
    parser.add_argument('--folds',    type=int, default=4, help='Nombre de fenêtres indépendantes pour backtest-wf (défaut: 4)')
    parser.add_argument('--capital',  type=float, default=10000, help='Capital initial en $ (défaut: 10 000)')
    parser.add_argument('--verbose',  action='store_true', help='Affichage détaillé')
    args = parser.parse_args()

    config = Config(
        initial_capital=args.capital,
        strategy_filter=args.strategy,
        verbose=args.verbose,
    )

    print("""
╔══════════════════════════════════════════════════════════════╗
║              TRADING BOT — Paper Trading                     ║
╚══════════════════════════════════════════════════════════════╝""")
    print(f"  Mode        : {args.mode.upper()}")
    print(f"  Stratégie   : {args.strategy.upper()}")
    print(f"  Capital     : ${config.initial_capital:,.0f}")
    print(f"  Univers     : {len(config.watchlist)} actions\n")

    engine = TradingEngine(config)

    if args.mode == 'scan':
        engine.scan()
    elif args.mode == 'backtest':
        engine.backtest(days=args.days)
    elif args.mode == 'backtest-wf':
        engine.backtest_walk_forward(fold_days=args.fold_days, n_folds=args.folds)
    elif args.mode == 'paper':
        engine.run_paper_trading()
    elif args.mode == 'report':
        engine.print_report()
    elif args.mode == 'journal':
        engine.journal.print_summary()
        path = engine.journal.export_excel()
        print(f"\n📁 Rapport exporté : {path}")
    elif args.mode == 'rank-pairs':
        engine.rank_pairs()

if __name__ == '__main__':
    main()
