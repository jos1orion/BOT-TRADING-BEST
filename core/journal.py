"""
Journal de trading automatique.

Enregistre chaque trade (ouverture, clôture, sorties partielles) dans
un fichier CSV consultable, et peut exporter un rapport Excel (.xlsx)
avec les métriques clés : win rate, profit factor, drawdown, etc.

Un fichier CSV est toujours produit (aucune dépendance requise).
L'export Excel utilise openpyxl s'il est disponible, sinon un CSV
récapitulatif est produit à la place avec un avertissement.
"""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False


CSV_FIELDS = [
    "trade_id", "ticker", "strategy", "direction",
    "entry_date", "entry_price", "shares",
    "exit_date", "exit_price", "exit_reason",
    "stop_loss", "tp1", "tp2",
    "pnl", "pnl_pct", "r_multiple", "status",
]


class TradeJournal:
    """
    Écrit une ligne par trade dans un CSV, et peut produire
    un rapport de synthèse (.xlsx si openpyxl est présent).
    """

    def __init__(self, csv_path: str = "trading_journal.csv", initial_capital: float = 10000.0):
        self.csv_path = csv_path
        self.initial_capital = initial_capital
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()

    # ────────────────────────────────────────────────────────
    # ÉCRITURE
    # ────────────────────────────────────────────────────────

    def log_trade(self, trade_id: str, ticker: str, strategy: str,
                  direction: str, entry_date, entry_price: float,
                  shares: float, exit_date=None, exit_price: float = 0.0,
                  exit_reason: str = "", stop_loss: float = 0.0,
                  tp1: float = 0.0, tp2: float = 0.0,
                  pnl: float = 0.0, status: str = "OPEN"):
        """Ajoute (ou met à jour en ré-écrivant) une ligne de trade."""
        risk = abs(entry_price - stop_loss) if stop_loss else 0
        r_multiple = round(pnl / (risk * shares), 2) if risk and shares else 0
        pnl_pct = round((pnl / (entry_price * shares)) * 100, 2) if entry_price and shares else 0

        row = {
            "trade_id":   trade_id,
            "ticker":     ticker,
            "strategy":   strategy,
            "direction":  direction,
            "entry_date": self._fmt_date(entry_date),
            "entry_price": round(entry_price, 5),
            "shares":     shares,
            "exit_date":  self._fmt_date(exit_date) if exit_date else "",
            "exit_price": round(exit_price, 5) if exit_price else "",
            "exit_reason": exit_reason,
            "stop_loss":  round(stop_loss, 5),
            "tp1":        round(tp1, 5),
            "tp2":        round(tp2, 5),
            "pnl":        round(pnl, 2),
            "pnl_pct":    pnl_pct,
            "r_multiple": r_multiple,
            "status":     status,
        }

        if status == "OPEN":
            self._append_row(row)
        else:
            self._update_or_append(trade_id, row)

    def close_trade(self, trade_id: str, exit_date, exit_price: float,
                    pnl: float, exit_reason: str = "") -> bool:
        """
        Clôture un trade EXISTANT en conservant toutes les infos d'ouverture
        (sens, prix d'entrée, lots, SL/TP, stratégie). Retourne False si le
        trade_id est introuvable (le trade n'a alors pas été ouvert par ce bot).
        """
        rows = self._read_all()
        for r in rows:
            if r["trade_id"] != trade_id:
                continue
            entry = float(r.get("entry_price") or 0)
            lots = float(r.get("shares") or 0)
            sl = float(r.get("stop_loss") or 0)
            risk = abs(entry - sl)
            r["exit_date"] = self._fmt_date(exit_date)
            r["exit_price"] = round(exit_price, 5) if exit_price else ""
            r["exit_reason"] = exit_reason
            r["pnl"] = round(pnl, 2)
            # % du capital de départ (la formule "prix × quantité" des actions n'a pas de sens en lots CFD)
            r["pnl_pct"] = round(pnl / self.initial_capital * 100, 2) if self.initial_capital else 0
            # R = mouvement de prix réalisé / distance au stop (indépendant de la taille du contrat)
            sign = -1 if r.get("direction") == "SHORT" else 1
            r["r_multiple"] = round(sign * (exit_price - entry) / risk, 2) if risk and exit_price else 0
            r["status"] = "CLOSED"
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            return True
        return False

    def open_trade_ids(self) -> List[str]:
        """Identifiants des trades encore OPEN dans le journal."""
        return [r["trade_id"] for r in self._read_all() if r.get("status") == "OPEN"]

    def _fmt_date(self, d) -> str:
        if isinstance(d, str):
            return d
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%d %H:%M:%S")
        return str(d) if d else ""

    def _append_row(self, row: Dict):
        with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writerow(row)

    def _update_or_append(self, trade_id: str, row: Dict):
        """Réécrit le CSV en remplaçant la ligne du trade_id si elle existe."""
        rows = self._read_all()
        found = False
        for i, r in enumerate(rows):
            if r["trade_id"] == trade_id:
                rows[i] = row
                found = True
                break
        if not found:
            rows.append(row)
        with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def _read_all(self) -> List[Dict]:
        if not os.path.exists(self.csv_path):
            return []
        with open(self.csv_path, 'r', newline='', encoding='utf-8') as f:
            return list(csv.DictReader(f))

    # ────────────────────────────────────────────────────────
    # STATISTIQUES
    # ────────────────────────────────────────────────────────

    def compute_stats(self) -> Dict:
        rows = [r for r in self._read_all() if r["status"] == "CLOSED"]
        if not rows:
            return {"nb_trades": 0}

        pnls = [float(r["pnl"]) for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf')

        equity_curve = []
        running = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in pnls:
            running += p
            equity_curve.append(running)
            peak = max(peak, running)
            dd = peak - running
            max_dd = max(max_dd, dd)

        # ── Sharpe (par trade, non annualisé — assez pour comparer
        # des runs entre eux, comme le profit factor) ──────────────
        n = len(pnls)
        mean_pnl = sum(pnls) / n
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / n if n > 1 else 0.0
        std_pnl = math.sqrt(variance)
        sharpe = round((mean_pnl / std_pnl) * math.sqrt(n), 2) if std_pnl > 0 else 0.0

        # ── Facteur de récupération : gain net / pire drawdown ─────
        recovery_factor = round(sum(pnls) / max_dd, 2) if max_dd > 0 else 0.0

        max_dd_pct = round((max_dd / self.initial_capital) * 100, 2) if self.initial_capital else 0.0

        return {
            "nb_trades":       len(rows),
            "win_rate":        round(len(wins) / len(rows) * 100, 1),
            "gross_profit":    round(gross_profit, 2),
            "gross_loss":      round(gross_loss, 2),
            "net_pnl":         round(sum(pnls), 2),
            "profit_factor":   profit_factor,
            "avg_win":         round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss":        round(sum(losses) / len(losses), 2) if losses else 0,
            "max_drawdown":    round(max_dd, 2),
            "max_drawdown_pct": max_dd_pct,
            "sharpe":          sharpe,
            "recovery_factor": recovery_factor,
            "best_trade":      round(max(pnls), 2),
            "worst_trade":     round(min(pnls), 2),
        }

    # ────────────────────────────────────────────────────────
    # DASHBOARD (Backtest Ledger)
    # ────────────────────────────────────────────────────────

    def export_dashboard_snapshot(self, path: str = "dashboard_snapshot.json",
                                   name: str = "Bot MT5", market: str = "",
                                   period: str = "", notes: str = "") -> Optional[str]:
        """
        Écrit un instantané JSON compatible avec le tableau de bord
        "Backtest Ledger" (mêmes champs que ses relevés), recalculé à
        chaque appel — donc automatiquement à jour après chaque trade
        clôturé. À importer dans le tableau de bord (bouton "Importer
        un instantané") pour refléter le live sans ressaisie manuelle.
        Écriture atomique (fichier temporaire puis renommage) pour
        éviter qu'une lecture tombe sur un fichier à moitié écrit.
        """
        stats = self.compute_stats()
        if stats.get("nb_trades", 0) == 0:
            return None

        snapshot = {
            "id": "snap_" + name.lower().replace(" ", "_"),
            "name": name,
            "market": market,
            "period": period,
            "trades": stats["nb_trades"],
            "capital": self.initial_capital,
            "profit": stats["net_pnl"],
            "dd": stats["max_drawdown_pct"],
            "winrate": stats["win_rate"],
            "pf": stats["profit_factor"],
            "sharpe": stats["sharpe"],
            "recovery": stats["recovery_factor"],
            "notes": notes,
            "createdAt": int(datetime.now().timestamp() * 1000),
            "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        directory = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        return path

    # ────────────────────────────────────────────────────────
    # EXPORT
    # ────────────────────────────────────────────────────────

    def export_excel(self, output_path: str = "trading_journal.xlsx") -> str:
        """
        Exporte un rapport Excel avec l'historique des trades + synthèse.
        Retombe sur un CSV de synthèse si openpyxl n'est pas installé.
        """
        rows = self._read_all()
        stats = self.compute_stats()

        if not OPENPYXL_AVAILABLE:
            fallback_path = output_path.replace(".xlsx", "_summary.csv")
            with open(fallback_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["openpyxl non installé — export Excel indisponible."])
                writer.writerow(["Installez-le avec : pip install openpyxl"])
                writer.writerow([])
                writer.writerow(list(stats.keys()))
                writer.writerow(list(stats.values()))
            return fallback_path

        wb = Workbook()

        # ── Feuille Trades ──────────────────────────────────
        ws = wb.active
        ws.title = "Trades"
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")

        ws.append(CSV_FIELDS)
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        for r in rows:
            ws.append([r.get(f, "") for f in CSV_FIELDS])

        for col in ws.columns:
            max_len = max((len(str(c.value)) for c in col if c.value is not None), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 30)

        # ── Feuille Synthèse ─────────────────────────────────
        ws2 = wb.create_sheet("Synthèse")
        ws2.append(["Métrique", "Valeur"])
        for cell in ws2[1]:
            cell.font = header_font
            cell.fill = header_fill

        labels = {
            "nb_trades": "Nombre de trades",
            "win_rate": "Win Rate (%)",
            "gross_profit": "Profit brut ($)",
            "gross_loss": "Perte brute ($)",
            "net_pnl": "PnL net ($)",
            "profit_factor": "Profit Factor",
            "avg_win": "Gain moyen ($)",
            "avg_loss": "Perte moyenne ($)",
            "max_drawdown": "Max Drawdown ($)",
            "best_trade": "Meilleur trade ($)",
            "worst_trade": "Pire trade ($)",
        }
        for key, label in labels.items():
            if key in stats:
                ws2.append([label, stats[key]])
        ws2.column_dimensions['A'].width = 25
        ws2.column_dimensions['B'].width = 15

        wb.save(output_path)
        return output_path

    def print_summary(self):
        stats = self.compute_stats()
        if stats.get("nb_trades", 0) == 0:
            print("\n📓 Journal de trading : aucun trade clôturé pour le moment.")
            return
        print(f"\n📓 JOURNAL DE TRADING — {stats['nb_trades']} trades clôturés")
        print(f"  Win Rate      : {stats['win_rate']}%")
        print(f"  Profit Factor : {stats['profit_factor']}")
        print(f"  PnL net       : ${stats['net_pnl']:+,.2f}")
        print(f"  Max Drawdown  : ${stats['max_drawdown']:,.2f}")
        print(f"  Fichier CSV   : {self.csv_path}")
