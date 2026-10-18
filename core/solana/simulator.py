"""
Simulateur de sniping — mode "simulate" du module Solana.

Aucune transaction réelle n'est envoyée ici. Chaque token qui passe les
filtres de sécurité est journalisé comme un "trade simulé" avec un prix
d'entrée fictif, pour évaluer a posteriori :
- combien de tokens auraient passé les filtres,
- combien auraient été des rugs malgré tout (à vérifier manuellement),
- quel aurait été le PnL théorique.

C'est l'étape à faire tourner plusieurs jours AVANT de brancher un wallet
réel — c'est ce qui permet de juger si les filtres sont pertinents pour
de vrai, pas seulement en théorie.
"""

import csv
import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger("solana.simulator")

JOURNAL_PATH = "solana_snipe_journal.csv"

FIELDNAMES = [
    "timestamp", "mint", "signature", "action",
    "liquidity_usd", "holder_count", "top10_holder_pct",
    "reasons_rejected", "simulated_entry_usd",
]


class SnipeSimulator:
    def __init__(self, journal_path: str = JOURNAL_PATH):
        self.journal_path = journal_path
        self._ensure_journal()

    def _ensure_journal(self):
        if not os.path.exists(self.journal_path):
            with open(self.journal_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()

    def log_candidate(self, mint: str, signature: str, safety_report,
                       simulated_entry_usd: Optional[float] = None):
        """Journalise un token candidat, qu'il ait passé les filtres ou non."""
        action = "SIMULATED_BUY" if safety_report.passed else "REJECTED"
        row = {
            "timestamp": int(time.time()),
            "mint": mint,
            "signature": signature,
            "action": action,
            "liquidity_usd": safety_report.liquidity_usd,
            "holder_count": safety_report.holder_count,
            "top10_holder_pct": safety_report.top10_holder_pct,
            "reasons_rejected": " | ".join(safety_report.reasons_rejected),
            "simulated_entry_usd": simulated_entry_usd or "",
        }
        with open(self.journal_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writerow(row)

        if safety_report.passed:
            logger.info("✅ [SIMULÉ] Achat simulé sur %s (liquidité=$%.0f, holders=%d)",
                        mint, safety_report.liquidity_usd, safety_report.holder_count)
        else:
            logger.info("❌ [REJETÉ] %s — raisons: %s", mint,
                        ", ".join(safety_report.reasons_rejected))

    def summary(self) -> dict:
        """Résumé rapide du journal (nombre de candidats, taux d'acceptation)."""
        if not os.path.exists(self.journal_path):
            return {"total": 0}
        total, accepted = 0, 0
        with open(self.journal_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total += 1
                if row["action"] == "SIMULATED_BUY":
                    accepted += 1
        return {
            "total_candidats": total,
            "acceptes_par_filtres": accepted,
            "taux_acceptation_pct": round(100 * accepted / total, 1) if total else 0,
        }
