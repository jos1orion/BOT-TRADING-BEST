"""
Backtest des stratégies du bot sur l'HISTORIQUE RÉEL de votre broker MT5 (Deriv).

    python backtest_mt5.py --broker deriv --symbols V75 V100 V50 --timeframe H1 --bars 5000

Pour chaque (symbole × stratégie) : le bot rejoue les bougies une à une, comme en live
(300 dernières bougies visibles), entre à l'OUVERTURE de la bougie suivante au signal,
sort au SL ou au TP1. Si SL et TP sont touchés dans la même bougie, le SL est compté
(hypothèse prudente). Slippage de config appliqué à l'entrée et à la sortie.

Résultat : backtest_report_<broker>.html (à ouvrir dans Chrome) + backtest_trades_<broker>.csv

⚠️ Un backtest ne prouve rien sur le futur : il sert à ÉLIMINER les stratégies perdantes,
pas à garantir les gagnantes. Aucune optimisation de paramètres n'est faite ici.
"""
from __future__ import annotations

import argparse
import csv
import html
import math
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from core.brokers.mt5_connector import MT5Connector, AccountMode
from core.brokers.deriv_config import DERIV_SYMBOL_ALIASES, is_synthetic
from core.config import Config
from core.indicators import Indicators as I
from core.signals import build_strategies, evaluate

WARMUP = 100
WINDOW = 300          # bougies visibles par la stratégie (comme en live)
MAX_HOLD = 300        # sortie forcée après N bougies


def market_condition(df: pd.DataFrame) -> str:
    if len(df) < 55:
        return 'NEUTRAL'
    c = df['Close']
    e8, e21, e50 = (I.ema(c, n).iloc[-1] for n in (8, 21, 50))
    p = c.iloc[-1]
    if p > e8 and p > e21 and p > e50:
        return 'BULL'
    if p < e8 and p < e21:
        return 'BEAR'
    return 'NEUTRAL'


def simulate(name: str, strat, symbol: str, df: pd.DataFrame, min_strength: float,
             slippage_pct: float, step: int) -> List[Dict]:
    """Rejoue UNE stratégie sur UN symbole. Retourne la liste des trades en multiples de R."""
    o, h, l, c = (df[k].to_numpy(float) for k in ('Open', 'High', 'Low', 'Close'))
    idx = df.index
    n = len(df)
    trades: List[Dict] = []
    i = WARMUP
    while i < n - 1:
        window = df.iloc[max(0, i - WINDOW + 1): i + 1]
        try:
            sig = evaluate(name, strat, symbol, window, market_condition(window))
        except Exception:
            sig = None
        if sig is None or sig.strength < min_strength:
            i += step
            continue

        long_ = sig.direction == 'LONG'
        entry = o[i + 1] * (1 + slippage_pct / 100 if long_ else 1 - slippage_pct / 100)
        sl, tp = sig.stop_loss, sig.tp1
        # cohérence SL/TP avec le sens et le prix d'entrée réel
        if (long_ and not (sl < entry < tp)) or ((not long_) and not (tp < entry < sl)):
            i += step
            continue
        risk = abs(entry - sl)
        if risk <= 0:
            i += step
            continue

        exit_px, reason, j = c[min(n - 1, i + 1 + MAX_HOLD)], 'TEMPS', min(n - 1, i + 1 + MAX_HOLD)
        for k in range(i + 1, min(n, i + 2 + MAX_HOLD)):
            hit_sl = l[k] <= sl if long_ else h[k] >= sl
            hit_tp = h[k] >= tp if long_ else l[k] <= tp
            if hit_sl:                       # SL prioritaire si les deux dans la même bougie
                exit_px, reason, j = sl, 'SL', k
                break
            if hit_tp:
                exit_px, reason, j = tp, 'TP', k
                break
        exit_px *= (1 - slippage_pct / 100) if long_ else (1 + slippage_pct / 100)
        r = ((exit_px - entry) if long_ else (entry - exit_px)) / risk
        trades.append({
            'symbol': symbol, 'strategy': name, 'direction': sig.direction,
            'entry_time': idx[i + 1], 'exit_time': idx[j], 'entry': entry,
            'exit': exit_px, 'reason': reason, 'r': r, 'bars': j - i,
        })
        i = j + 1                              # une seule position à la fois par couple
    return trades


def metrics(trades: List[Dict], risk_pct: float) -> Dict:
    if not trades:
        return {'n': 0}
    rs = [t['r'] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gp, gl = sum(wins), abs(sum(losses))
    run = peak = dd = 0.0
    curve = [0.0]
    for r in rs:
        run += r * risk_pct
        curve.append(run)
        peak = max(peak, run)
        dd = max(dd, peak - run)
    half = len(rs) // 2
    first, second = sum(rs[:half]), sum(rs[half:])
    return {
        'n': len(rs), 'win': len(wins) / len(rs) * 100,
        'pf': (gp / gl) if gl > 0 else float('inf'),
        'exp': sum(rs) / len(rs), 'net_r': sum(rs),
        'ret': run, 'dd': dd, 'curve': curve,
        'h1': first, 'h2': second,
        'avg_bars': sum(t['bars'] for t in trades) / len(trades),
    }


def verdict(m: Dict) -> (str, str):
    if m['n'] < 30:
        return 'Trop peu de trades', 'mute'
    if m['exp'] > 0.1 and m['pf'] >= 1.3 and m['h1'] > 0 and m['h2'] > 0:
        return 'Prometteur', 'pos'
    if m['exp'] > 0:
        return 'Fragile', 'warn'
    return 'Perdant', 'neg'


def spark(curve: List[float], w=120, h=28) -> str:
    if len(curve) < 2:
        return ''
    lo, hi = min(curve), max(curve)
    span = (hi - lo) or 1
    pts = ' '.join(f"{i * w / (len(curve) - 1):.1f},{h - 2 - (v - lo) * (h - 4) / span:.1f}" for i, v in enumerate(curve))
    col = 'var(--pos)' if curve[-1] >= 0 else 'var(--neg)'
    return f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}"><polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.8"/></svg>'


def write_report(path: str, rows: List[Dict], info: Dict) -> None:
    esc = html.escape
    rows = sorted(rows, key=lambda r: (r['m'].get('exp', -99) if r['m']['n'] >= 30 else -50), reverse=True)
    body = []
    for r in rows:
        m = r['m']
        if m['n'] == 0:
            body.append(f"<tr><td>{esc(r['symbol'])}</td><td>{esc(r['strategy'])}</td><td colspan='9' class='mute'>aucun trade</td></tr>")
            continue
        v, vc = verdict(m)
        pf = '∞' if math.isinf(m['pf']) else f"{m['pf']:.2f}"
        body.append(
            f"<tr><td>{esc(r['symbol'])}</td><td>{esc(r['strategy'])}</td><td class='num'>{m['n']}</td>"
            f"<td class='num'>{m['win']:.0f} %</td><td class='num'>{pf}</td>"
            f"<td class='num {'pos' if m['exp']>0 else 'neg'}'>{m['exp']:+.2f} R</td>"
            f"<td class='num {'pos' if m['ret']>0 else 'neg'}'>{m['ret']:+.1f} %</td>"
            f"<td class='num'>{m['dd']:.1f} %</td>"
            f"<td class='num'><span class='{'pos' if m['h1']>0 else 'neg'}'>{m['h1']:+.1f}</span> / "
            f"<span class='{'pos' if m['h2']>0 else 'neg'}'>{m['h2']:+.1f}</span></td>"
            f"<td>{spark(m['curve'])}</td><td><b class='{vc}'>{v}</b></td></tr>")
    good = sum(1 for r in rows if r['m']['n'] and verdict(r['m'])[1] == 'pos')
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Backtest {esc(info['broker'])}</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--mute:#65707f;--line:#e3e7ec;--pos:#0a8f5a;--neg:#d23b3b;--warn:#b7791f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1116;--card:#171b22;--ink:#e8ecf1;--mute:#8b96a5;--line:#262c36;--pos:#35c985;--neg:#ff6b6b;--warn:#e0a84a}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,Segoe UI,sans-serif}}main{{max-width:1100px;margin:0 auto;padding:20px 16px 48px}}
h1{{font-size:20px;margin:0 0 4px}}small,.mute{{color:var(--mute)}}.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-top:12px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}th{{text-align:left;color:var(--mute);font-weight:500;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}.num{{text-align:right;font-variant-numeric:tabular-nums}}th.num{{text-align:right}}
.pos{{color:var(--pos)}}.neg{{color:var(--neg)}}.warn{{color:var(--warn)}}</style></head><body><main>
<h1>Backtest {esc(info['broker'])} — {esc(info['timeframe'])}</h1>
<small>Généré le {datetime.now():%d/%m/%Y %H:%M} · {info['bars']} bougies max par symbole · risque {info['risk']} % par trade ·
signal ≥ {info['min_strength']:.0f}/100 · slippage {info['slip']} % par côté · une position à la fois par stratégie/symbole</small>
<div class="card"><b>{good}</b> combinaison(s) « Prometteur » sur {len(rows)} testées.
« Prometteur » = ≥ 30 trades, espérance &gt; +0,1 R, profit factor ≥ 1,3 et gain positif sur les <i>deux moitiés</i> de la période.
Tout le reste est à écarter ou à surveiller de près. Les colonnes « 1re / 2e moitié » (en R) servent à repérer un résultat dû à une seule période chanceuse.</div>
<div class="card"><table><thead><tr><th>Symbole</th><th>Stratégie</th><th class="num">Trades</th><th class="num">Réussite</th><th class="num">PF</th>
<th class="num">Espérance</th><th class="num">Rendement*</th><th class="num">DD max*</th><th class="num">1re / 2e moitié (R)</th><th>Courbe</th><th>Verdict</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div>
<p><small>* en % du capital, au risque indiqué par trade, sans réinvestissement. R = montant risqué sur un trade (distance au stop).
Un backtest passé ne garantit pas les résultats futurs ; ces stratégies n'ont pas été optimisées pour ces symboles.</small></p>
</main></body></html>"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page)


def main():
    ap = argparse.ArgumentParser(description="Backtest MT5 des stratégies du bot")
    ap.add_argument('--broker', choices=['deriv', 'xm', 'axiom'], default='deriv')
    ap.add_argument('--symbols', nargs='+', default=['BTCUSD', 'ETHUSD', 'V75', 'V100', 'V50', 'V25', 'V10'])
    ap.add_argument('--timeframe', default='H1')
    ap.add_argument('--bars', type=int, default=5000)
    ap.add_argument('--risk', type=float, default=0.5, help='%% du capital risqué par trade')
    ap.add_argument('--min-strength', type=float, default=65)
    ap.add_argument('--step', type=int, default=1, help='évalue un signal toutes les N bougies (plus rapide si >1)')
    ap.add_argument('--strategies', nargs='*', default=None)
    args = ap.parse_args()

    from broker_credentials import XM_CONFIG, AXIOM_CONFIG, DERIV_CONFIG, MT5_PATH
    creds = {'xm': XM_CONFIG, 'axiom': AXIOM_CONFIG, 'deriv': DERIV_CONFIG}[args.broker]['demo']
    if creds['login'] == 0:
        sys.exit("❌ Identifiants démo non configurés (.env).")

    mt5c = MT5Connector(account_mode=AccountMode.DEMO)
    if not mt5c.connect(creds['login'], creds['password'], creds['server'], MT5_PATH):
        sys.exit("❌ Connexion MT5 impossible.")

    cfg = Config()
    strategies = build_strategies(cfg)
    if args.strategies:
        strategies = {k: v for k, v in strategies.items() if k in args.strategies}
    aliases = DERIV_SYMBOL_ALIASES if args.broker == 'deriv' else {}

    results, all_trades = [], []
    t0 = time.time()
    for canon in args.symbols:
        real = mt5c.resolve_symbol(canon, aliases.get(canon))
        if not real:
            print(f"⚠️  {canon} introuvable — ignoré")
            continue
        df = mt5c.get_ohlcv_mt5(real, args.timeframe, count=args.bars)
        if df is None or len(df) < WARMUP + 50:
            print(f"⚠️  {real}: historique insuffisant — ignoré")
            continue
        print(f"\n▶ {real} : {len(df)} bougies ({df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d})")
        for name, strat in strategies.items():
            tr = simulate(name, strat, real, df, args.min_strength, cfg.slippage_pct, args.step)
            m = metrics(tr, args.risk)
            results.append({'symbol': real, 'strategy': name, 'm': m})
            all_trades += tr
            if m['n']:
                print(f"   {name:<16} {m['n']:>4} trades | réussite {m['win']:>3.0f}% | exp {m['exp']:+.2f}R | {verdict(m)[0]}")
            else:
                print(f"   {name:<16}    0 trade")
    mt5c.disconnect()

    out_html = f"backtest_report_{args.broker}.html"
    out_csv = f"backtest_trades_{args.broker}.csv"
    write_report(out_html, results, {'broker': args.broker.upper(), 'timeframe': args.timeframe,
                 'bars': args.bars, 'risk': args.risk, 'min_strength': args.min_strength, 'slip': cfg.slippage_pct})
    if all_trades:
        with open(out_csv, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(all_trades[0].keys()))
            w.writeheader()
            w.writerows(all_trades)
    print(f"\n✅ Terminé en {time.time() - t0:.0f}s → ouvrez {out_html} dans Chrome")


if __name__ == '__main__':
    main()
