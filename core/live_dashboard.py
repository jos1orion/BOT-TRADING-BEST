"""
Tableau de bord LIVE (HTML autonome) pour le bot MT5.

Le bot réécrit `dashboard_live_<broker>.html` à chaque cycle. Ouvrez ce fichier
dans Chrome (double-clic) : la page se recharge toute seule toutes les 15 s.
Aucune dépendance, aucun serveur, aucune donnée envoyée sur Internet.
"""

from __future__ import annotations

import html
import json
import math
import os
import tempfile
from datetime import datetime
from typing import Dict, List

REFRESH_SECONDS = 15


def _money(v: float, cur: str = "USD") -> str:
    return f"{v:+,.2f}".replace(",", " ") + f" {cur}"


def _cls(v: float) -> str:
    return "pos" if v > 0 else ("neg" if v < 0 else "")


def _equity_svg(pnls: List[float], width: int = 760, height: int = 180) -> str:
    if not pnls:
        return '<div class="empty">Aucun trade clôturé pour l\'instant</div>'
    pts, run = [0.0], 0.0
    for p in pnls:
        run += p
        pts.append(run)
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    pad = 12
    def xy(i, v):
        x = pad + i * (width - 2 * pad) / max(1, len(pts) - 1)
        y = height - pad - (v - lo) * (height - 2 * pad) / span
        return x, y
    line = " ".join(f"{xy(i, v)[0]:.1f},{xy(i, v)[1]:.1f}" for i, v in enumerate(pts))
    zero_y = xy(0, 0.0)[1]
    color = "var(--pos)" if pts[-1] >= 0 else "var(--neg)"
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Courbe de gain cumulé">'
        f'<line x1="{pad}" x2="{width - pad}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" class="zero"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.5" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def _breakdown(closed: List[Dict], key: str, cur: str) -> str:
    groups: Dict[str, List[float]] = {}
    for r in closed:
        try:
            groups.setdefault(str(r.get(key) or "—"), []).append(float(r["pnl"]))
        except (KeyError, ValueError):
            pass
    if not groups:
        return "<tr><td colspan='5' class='empty'>Pas encore de données</td></tr>"
    out = []
    for name, v in sorted(groups.items(), key=lambda kv: -sum(kv[1])):
        wins = sum(1 for x in v if x > 0)
        gp = sum(x for x in v if x > 0)
        gl = abs(sum(x for x in v if x <= 0))
        pf = "∞" if gl == 0 and gp > 0 else (f"{gp / gl:.2f}" if gl else "—")
        out.append(f"<tr><td>{html.escape(name)}</td><td class='num'>{len(v)}</td>"
                   f"<td class='num'>{wins / len(v) * 100:.0f} %</td><td class='num'>{pf}</td>"
                   f"<td class='num {_cls(sum(v))}'>{_money(sum(v), cur)}</td></tr>")
    return "".join(out)


def _daily(closed: List[Dict], cur: str) -> str:
    days: Dict[str, float] = {}
    for r in closed:
        d = str(r.get("exit_date") or r.get("entry_date") or "")[:10]
        try:
            days[d] = days.get(d, 0.0) + float(r["pnl"])
        except (KeyError, ValueError):
            pass
    if not days:
        return "<tr><td colspan='2' class='empty'>Pas encore de données</td></tr>"
    return "".join(f"<tr><td>{d}</td><td class='num {_cls(v)}'>{_money(v, cur)}</td></tr>"
                   for d, v in sorted(days.items(), reverse=True)[:14])


def write_live_dashboard(path: str, broker: str, mode: str, account: Dict,
                         positions: list, closed_rows: List[Dict], stats: Dict,
                         guard_status: str, symbols: List[str],
                         last_event: str = "", activity: List[str] = None,
                         info: Dict = None) -> str:
    activity = activity or []
    info = info or {}
    cur = account.get("currency", "USD")
    balance = float(account.get("balance", 0) or 0)
    equity = float(account.get("equity", 0) or 0)
    floating = float(account.get("profit", 0) or 0)
    free_margin = float(account.get("free_margin", 0) or 0)

    closed = [r for r in closed_rows if r.get("status") == "CLOSED"]
    pnls = []
    for r in closed:
        try:
            pnls.append(float(r["pnl"]))
        except (KeyError, ValueError):
            pass

    esc = html.escape
    pos_rows = "".join(
        f"<tr><td>#{p.ticket}</td><td>{esc(p.symbol)}</td>"
        f"<td><span class='tag {p.type}'>{p.type.upper()}</span></td>"
        f"<td class='num'>{p.volume}</td><td class='num'>{p.open_price:g}</td>"
        f"<td class='num'>{p.current_price:g}</td><td class='num'>{p.stop_loss:g}</td>"
        f"<td class='num'>{p.take_profit:g}</td>"
        f"<td class='num {_cls(p.profit)}'>{_money(p.profit, cur)}</td></tr>"
        for p in positions
    ) or "<tr><td colspan='9' class='empty'>Aucune position ouverte</td></tr>"

    hist_rows = "".join(
        f"<tr><td>{esc(str(r.get('exit_date') or r.get('entry_date') or ''))[:16]}</td>"
        f"<td>{esc(str(r.get('ticker', '')))}</td><td>{esc(str(r.get('strategy', '')))}</td>"
        f"<td class='num {_cls(float(r.get('pnl') or 0))}'>{_money(float(r.get('pnl') or 0), cur)}</td></tr>"
        for r in reversed(closed[-15:])
    ) or "<tr><td colspan='4' class='empty'>Aucun trade clôturé</td></tr>"

    n = stats.get("nb_trades", 0)
    def stat(label, value, klass=""):
        return f"<div class='kpi'><span>{label}</span><b class='{klass}'>{value}</b></div>"
    stat_html = "".join([
        stat("Trades clôturés", n),
        stat("Taux de réussite", f"{stats.get('win_rate', 0)} %" if n else "—"),
        stat("Profit factor", stats.get("profit_factor", "—") if n else "—"),
        stat("Gain net", _money(stats.get("net_pnl", 0), cur) if n else "—", _cls(stats.get("net_pnl", 0)) if n else ""),
        stat("Drawdown max", f"{stats.get('max_drawdown_pct', 0)} %" if n else "—"),
    ])

    paused = guard_status.startswith("⛔")
    is_real = mode.upper().startswith("R")
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>Bot {esc(broker)} — suivi live</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--mute:#65707f;--line:#e3e7ec;--pos:#0a8f5a;--neg:#d23b3b;--warn:#b7791f;--accent:#2a5bd7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1116;--card:#171b22;--ink:#e8ecf1;--mute:#8b96a5;--line:#262c36;--pos:#35c985;--neg:#ff6b6b;--warn:#e0a84a;--accent:#6f93ff}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,Segoe UI,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:20px 16px 48px}}
header{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:space-between;margin-bottom:18px}}
h1{{font-size:20px;margin:0}}h2{{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--mute);margin:26px 0 10px}}
.badge{{display:inline-block;padding:3px 10px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid var(--line)}}
.demo{{color:var(--warn)}}.real{{color:var(--neg)}}.ok{{color:var(--pos)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}
.kpi,.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
.kpi span{{display:block;color:var(--mute);font-size:12px}}.kpi b{{font-size:20px;font-variant-numeric:tabular-nums}}
.pos{{color:var(--pos)}}.neg{{color:var(--neg)}}
.card{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th{{text-align:left;color:var(--mute);font-weight:500;padding:6px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:7px 8px;border-bottom:1px solid var(--line);white-space:nowrap}}tr:last-child td{{border-bottom:0}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}th.num{{text-align:right}}
.tag{{font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px;border:1px solid currentColor}}.buy{{color:var(--pos)}}.sell{{color:var(--neg)}}
.empty{{color:var(--mute);text-align:center;padding:14px}}svg{{width:100%;height:auto;display:block}}.zero{{stroke:var(--line);stroke-dasharray:4 4}}
.alert{{border-color:var(--neg);color:var(--neg)}}.two{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr));gap:0 14px}}.log{{font:12.5px/1.6 ui-monospace,Consolas,monospace;max-height:320px;overflow-y:auto}}.log div{{border-bottom:1px solid var(--line);padding:2px 0}}small{{color:var(--mute)}}
</style></head><body><main>
<header><div><h1>Bot {esc(broker)} — suivi live</h1>
<small>Mis à jour {now} · rechargement auto {REFRESH_SECONDS}s</small></div>
<span class="badge {'real' if is_real else 'demo'}">{'COMPTE RÉEL' if is_real else 'COMPTE DÉMO'}</span></header>

<div class="grid">
<div class="kpi"><span>Solde</span><b>{balance:,.2f} {cur}</b></div>
<div class="kpi"><span>Equity</span><b>{equity:,.2f} {cur}</b></div>
<div class="kpi"><span>Résultat flottant</span><b class="{_cls(floating)}">{_money(floating, cur)}</b></div>
<div class="kpi"><span>Marge libre</span><b>{free_margin:,.2f}</b></div>
</div>

<div class="card {'alert' if paused else ''}" style="margin-top:10px"><b>Garde-fou drawdown :</b> {esc(guard_status)}
{f"<br><small>{esc(last_event)}</small>" if last_event else ""}</div>

<h2>Positions ouvertes ({len(positions)})</h2>
<div class="card"><table><thead><tr><th>Ticket</th><th>Symbole</th><th>Sens</th><th class="num">Lots</th>
<th class="num">Ouverture</th><th class="num">Actuel</th><th class="num">SL</th><th class="num">TP</th><th class="num">Résultat</th></tr></thead>
<tbody>{pos_rows}</tbody></table></div>

<h2>Performance</h2><div class="grid">{stat_html}</div>
<div class="card" style="margin-top:10px">{_equity_svg(pnls)}</div>

<h2>Derniers trades clôturés</h2>
<div class="card"><table><thead><tr><th>Date</th><th>Symbole</th><th>Stratégie</th><th class="num">Résultat</th></tr></thead>
<tbody>{hist_rows}</tbody></table></div>

<div class="two">
<div><h2>Par stratégie</h2><div class="card"><table><thead><tr><th>Stratégie</th><th class="num">Trades</th><th class="num">Réussite</th><th class="num">PF</th><th class="num">Net</th></tr></thead><tbody>{_breakdown(closed, 'strategy', cur)}</tbody></table></div></div>
<div><h2>Par symbole</h2><div class="card"><table><thead><tr><th>Symbole</th><th class="num">Trades</th><th class="num">Réussite</th><th class="num">PF</th><th class="num">Net</th></tr></thead><tbody>{_breakdown(closed, 'ticker', cur)}</tbody></table></div></div>
</div>
<h2>Résultat par jour</h2><div class="card"><table><thead><tr><th>Jour</th><th class="num">Résultat</th></tr></thead><tbody>{_daily(closed, cur)}</tbody></table></div>

<h2>Activité du bot</h2><div class="card log">{''.join(f"<div>{esc(a)}</div>" for a in reversed(activity[-40:])) or "<div class='empty'>Aucune activité pour l'instant</div>"}</div>

<h2>Paramètres du bot</h2><div class="card"><table><tbody>
<tr><td>Démarré</td><td>{esc(str(info.get('started', '—')))}</td></tr>
<tr><td>Dernier cycle</td><td>{esc(str(info.get('last_cycle', '—')))}</td></tr>
<tr><td>Prochain scan dans</td><td>{esc(str(info.get('next_scan', '—')))}</td></tr>
<tr><td>Timeframe / scan</td><td>{esc(str(info.get('timeframe', '—')))} · toutes les {esc(str(info.get('interval', '—')))} s</td></tr>
<tr><td>Risque par trade</td><td>{esc(str(info.get('risk', '—')))} %</td></tr>
<tr><td>Positions max</td><td>{esc(str(info.get('max_positions', '—')))}</td></tr>
<tr><td>Heures de trading</td><td>{esc(str(info.get('hours', '—')))}</td></tr>
<tr><td>Limites drawdown</td><td>{esc(str(info.get('limits', '—')))}</td></tr>
<tr><td>Symboles surveillés</td><td>{esc(', '.join(symbols))}</td></tr>
</tbody></table></div>
</main></body></html>"""

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, path)       # écriture atomique : Chrome ne lit jamais un fichier à moitié écrit
    return path


def write_live_dashboard_state(path: str, broker: str, mode: str, account: Dict,
                               positions: list, closed_rows: List[Dict], stats: Dict,
                               guard_status: str, symbols: List[str],
                               activity: List[str] = None,
                               info: Dict = None,
                               connections: Dict = None,
                               market_chart: Dict = None) -> str:
    """Écrit les seules données de suivi nécessaires à la Mini App Telegram."""
    def number(value):
        try:
            result = float(value or 0)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    payload = {
        "broker": str(broker),
        "mode": str(mode),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "account": {
            "balance": number(account.get("balance")),
            "equity": number(account.get("equity")),
            "profit": number(account.get("profit")),
            "free_margin": number(account.get("free_margin")),
            "currency": str(account.get("currency") or "USD"),
        },
        "guard_status": str(guard_status),
        "positions": [
            {
                "ticket": int(position.ticket),
                "symbol": str(position.symbol),
                "type": str(position.type),
                "volume": number(position.volume),
                "open_price": number(position.open_price),
                "current_price": number(position.current_price),
                "stop_loss": number(position.stop_loss),
                "take_profit": number(position.take_profit),
                "profit": number(position.profit),
            }
            for position in positions
        ],
        "stats": {
            "nb_trades": int(stats.get("nb_trades", 0) or 0),
            "win_rate": number(stats.get("win_rate")),
            "profit_factor": number(stats.get("profit_factor")),
            "net_pnl": number(stats.get("net_pnl")),
            "max_drawdown_pct": number(stats.get("max_drawdown_pct")),
            "today_pnl": number(sum(
                number(row.get("pnl")) or 0
                for row in closed_rows
                if row.get("status") == "CLOSED"
                and str(row.get("exit_date") or row.get("entry_date") or "")[:10]
                == datetime.now().strftime("%Y-%m-%d")
            )),
        },
        "closed_trades": [
            {
                "date": str(row.get("exit_date") or row.get("entry_date") or ""),
                "symbol": str(row.get("ticker") or ""),
                "strategy": str(row.get("strategy") or ""),
                "direction": str(row.get("direction") or ""),
                "entry_date": str(row.get("entry_date") or ""),
                "entry_price": number(row.get("entry_price")),
                "exit_price": number(row.get("exit_price")),
                "exit_reason": str(row.get("exit_reason") or ""),
                "pnl": number(row.get("pnl")),
            }
            for row in closed_rows
            if row.get("status") == "CLOSED"
        ][-90:],
        "symbols": [str(symbol) for symbol in symbols],
        "activity": [str(item) for item in (activity or [])[-20:]],
        "info": {str(key): str(value) for key, value in (info or {}).items()},
        "connections": {
            "bot": bool((connections or {}).get("bot", True)),
            "mt5": bool((connections or {}).get(
                "mt5", account.get("equity") is not None
            )),
        },
        "market_chart": market_chart or {},
    }

    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, allow_nan=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return path
