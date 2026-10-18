"""
Générateur de dashboard HTML autonome (pas de serveur requis).

Lit trading_journal.csv + crypto_bot_state.json et produit dashboard.html
— un fichier statique consultable dans n'importe quel navigateur (local
ou copié depuis un VPS). Conçu pour être régénéré à chaque cycle par
live_crypto_bot.py (voir generate_dashboard() appelé dans run_once()),
mais peut aussi être lancé à la main :

    python dashboard.py

Aucune dépendance ajoutée (json/csv/html en stdlib), aucune donnée
envoyée nulle part — tout reste en local.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional

from core.journal import TradeJournal

STATE_PATH = "crypto_bot_state.json"
JOURNAL_PATH = "crypto_trading_journal.csv"
OUTPUT_PATH = "dashboard.html"


def _load_state() -> dict:
    if not os.path.exists(STATE_PATH):
        return {"cash": 0.0, "positions": {}, "last_update": None}
    with open(STATE_PATH) as f:
        return json.load(f)


def _fmt_money(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.2f} $".replace(",", " ")


def _fmt_pct(v: float) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.2f}%"


def generate_dashboard(
    state_path: str = STATE_PATH,
    journal_path: str = JOURNAL_PATH,
    output_path: str = OUTPUT_PATH,
    drawdown_guard=None,
) -> str:
    """
    Génère dashboard.html à partir de l'état courant du bot.

    drawdown_guard : instance optionnelle de DrawdownGuard (pour afficher
    le statut pause/actif en direct). Sans elle, cette section est omise.
    """
    state = _load_state()
    cash = state.get("cash", 0.0)
    positions = state.get("positions", {})
    last_update = state.get("last_update", "—")

    journal = TradeJournal(csv_path=journal_path)
    stats = journal.compute_stats()

    positions_value = sum(
        p.get("quantity", 0) * p.get("entry_price", 0) for p in positions.values()
    )
    equity = cash + positions_value

    net_pnl = stats.get("net_pnl", 0.0)
    pnl_class = "pos" if net_pnl >= 0 else "neg"

    # ── Statut drawdown guard (si fourni) ──────────────────────
    dd_html = ""
    if drawdown_guard is not None:
        paused = drawdown_guard.is_paused
        badge_class = "paused" if paused else "active"
        dd_html = f"""
        <div class="card">
          <div class="card-label">Statut du bot</div>
          <div class="badge {badge_class}">{drawdown_guard.status}</div>
        </div>"""

    # ── Lignes de positions ouvertes ───────────────────────────
    if positions:
        rows = []
        for ticker, p in positions.items():
            entry = p.get("entry_price", 0)
            qty = p.get("quantity", 0)
            sl = p.get("stop_loss", 0)
            tp1 = p.get("tp1", 0)
            strat = p.get("strategy", "—")
            value = entry * qty
            rows.append(f"""
            <tr>
              <td class="ticker">{ticker}</td>
              <td>{strat}</td>
              <td>{qty:g}</td>
              <td>{entry:,.2f} $</td>
              <td>{value:,.2f} $</td>
              <td class="sl">{sl:,.2f} $</td>
              <td class="tp">{tp1:,.2f} $</td>
            </tr>""")
        positions_html = f"""
        <table>
          <thead>
            <tr><th>Ticker</th><th>Stratégie</th><th>Qté</th><th>Entrée</th>
                <th>Valeur</th><th>Stop Loss</th><th>TP1</th></tr>
          </thead>
          <tbody>{''.join(rows)}</tbody>
        </table>"""
    else:
        positions_html = '<p class="empty">Aucune position ouverte actuellement.</p>'

    # ── Stats de synthèse ───────────────────────────────────────
    if stats.get("nb_trades", 0) > 0:
        stats_html = f"""
        <div class="stats-grid">
          <div class="stat"><div class="stat-value">{stats['nb_trades']}</div><div class="stat-label">Trades clôturés</div></div>
          <div class="stat"><div class="stat-value">{stats['win_rate']}%</div><div class="stat-label">Win rate</div></div>
          <div class="stat"><div class="stat-value">{stats['profit_factor']}</div><div class="stat-label">Profit factor</div></div>
          <div class="stat"><div class="stat-value neg">-{stats['max_drawdown']:,.2f} $</div><div class="stat-label">Max drawdown</div></div>
          <div class="stat"><div class="stat-value pos">{stats['best_trade']:,.2f} $</div><div class="stat-label">Meilleur trade</div></div>
          <div class="stat"><div class="stat-value neg">{stats['worst_trade']:,.2f} $</div><div class="stat-label">Pire trade</div></div>
        </div>"""
    else:
        stats_html = '<p class="empty">Aucun trade clôturé pour le moment — les stats apparaîtront après la première clôture.</p>'

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard — Trading Bot</title>
<meta http-equiv="refresh" content="60">
<style>
  :root {{
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e;
    --green: #3fb950; --red: #f85149; --blue: #58a6ff; --orange: #d29922;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: 32px 20px;
  }}
  .container {{ max-width: 920px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 28px; }}
  .top-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .card {{
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 20px;
  }}
  .card-label {{ color: var(--muted); font-size: 0.8rem; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.03em; }}
  .card-value {{ font-size: 1.6rem; font-weight: 600; }}
  .pos {{ color: var(--green); }}
  .neg {{ color: var(--red); }}
  .badge {{
    display: inline-block; padding: 6px 12px; border-radius: 6px;
    font-size: 0.85rem; font-weight: 600;
  }}
  .badge.active {{ background: rgba(63,185,80,0.15); color: var(--green); }}
  .badge.paused {{ background: rgba(248,81,73,0.15); color: var(--red); }}
  section {{ margin-bottom: 28px; }}
  h2 {{ font-size: 1.05rem; margin-bottom: 12px; color: var(--text); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }}
  th, td {{ padding: 10px 14px; text-align: left; font-size: 0.88rem; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 500; text-transform: uppercase; font-size: 0.72rem; letter-spacing: 0.03em; }}
  tr:last-child td {{ border-bottom: none; }}
  .ticker {{ font-weight: 600; color: var(--blue); }}
  .sl {{ color: var(--red); }}
  .tp {{ color: var(--green); }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }}
  .stat {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px; text-align: center; }}
  .stat-value {{ font-size: 1.3rem; font-weight: 600; }}
  .stat-label {{ color: var(--muted); font-size: 0.75rem; margin-top: 4px; }}
  .empty {{ color: var(--muted); font-size: 0.9rem; font-style: italic; }}
  footer {{ color: var(--muted); font-size: 0.75rem; text-align: center; margin-top: 32px; }}
</style>
</head>
<body>
<div class="container">
  <h1>🤖 Trading Bot — Dashboard</h1>
  <div class="subtitle">Généré le {generated_at} · rafraîchi automatiquement toutes les 60s</div>

  <div class="top-grid">
    <div class="card">
      <div class="card-label">Équity totale</div>
      <div class="card-value">{equity:,.2f} $</div>
    </div>
    <div class="card">
      <div class="card-label">Cash disponible</div>
      <div class="card-value">{cash:,.2f} $</div>
    </div>
    <div class="card">
      <div class="card-label">P&amp;L net réalisé</div>
      <div class="card-value {pnl_class}">{_fmt_money(net_pnl)}</div>
    </div>{dd_html}
  </div>

  <section>
    <h2>📊 Positions ouvertes ({len(positions)})</h2>
    {positions_html}
  </section>

  <section>
    <h2>📈 Statistiques de performance</h2>
    {stats_html}
  </section>

  <footer>Dernière mise à jour de l'état : {last_update} · Fichier généré localement, aucune donnée transmise.</footer>
</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


if __name__ == "__main__":
    path = generate_dashboard()
    print(f"Dashboard généré : {path}")
