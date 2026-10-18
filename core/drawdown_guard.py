"""
Garde-fou contre le drawdown excessif.

Règle : si le drawdown dépasse un seuil défini sur la journée ou
la semaine, le bot arrête d'ouvrir de nouvelles positions jusqu'à
la période suivante (reset automatique à minuit / lundi).

Suit aussi les pertes consécutives (ex: 5 trades perdants d'affilée)
comme second déclencheur indépendant du drawdown en $.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple


@dataclass
class DrawdownGuard:
    daily_limit_pct: float = 3.0          # Pause si -3% sur la journée
    weekly_limit_pct: float = 6.0         # Pause si -6% sur la semaine
    max_consecutive_losses: int = 5        # Pause après 5 pertes d'affilée
    min_loss_amount: float = 0.0          # Montant minimum de perte ($) avant de déclencher la pause
    state_path: Optional[Path] = None

    _day_start_equity: float = 0.0
    _week_start_equity: float = 0.0
    _current_day: Optional[str] = None     # 'YYYY-MM-DD'
    _current_week: Optional[str] = None    # 'YYYY-WW'
    _consecutive_losses: int = 0
    _paused: bool = False
    _pause_reason: str = ""

    def __post_init__(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return

        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("format d'état invalide")
            if state.get("version") != 1:
                raise ValueError("version d'état inconnue")
            self._day_start_equity = float(state["day_start_equity"])
            self._week_start_equity = float(state["week_start_equity"])
            self._current_day = state["current_day"]
            self._current_week = state["current_week"]
            self._consecutive_losses = int(state["consecutive_losses"])
            if not isinstance(state["paused"], bool):
                raise ValueError("état de pause invalide")
            self._paused = state["paused"]
            self._pause_reason = str(state["pause_reason"])
            if (
                not math.isfinite(self._day_start_equity)
                or not math.isfinite(self._week_start_equity)
                or self._consecutive_losses < 0
            ):
                raise ValueError("valeurs d'état invalides")
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Impossible de charger l'état du drawdown ({self.state_path}): {exc}"
            ) from exc

    def _persist_state(self) -> None:
        if self.state_path is None:
            return

        state = {
            "version": 1,
            "day_start_equity": self._day_start_equity,
            "week_start_equity": self._week_start_equity,
            "current_day": self._current_day,
            "current_week": self._current_week,
            "consecutive_losses": self._consecutive_losses,
            "paused": self._paused,
            "pause_reason": self._pause_reason,
        }
        temporary_path = None
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.state_path.name}.",
                suffix=".tmp",
                dir=self.state_path.parent,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(state, output)
                output.flush()
                os.fsync(output.fileno())

            for attempt in range(8):
                try:
                    os.replace(temporary_path, self.state_path)
                    temporary_path = None
                    break
                except PermissionError:
                    if attempt == 7:
                        if self.state_path.read_text(encoding="utf-8") == json.dumps(state):
                            break
                        raise
                    time.sleep(0.1 * (attempt + 1))
        except OSError as exc:
            raise RuntimeError(
                f"Impossible d'enregistrer l'état du drawdown ({self.state_path}): {exc}"
            ) from exc
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError as exc:
                    raise RuntimeError(
                        f"Impossible de nettoyer le fichier temporaire du drawdown "
                        f"({temporary_path}): {exc}"
                    ) from exc

    def _day_key(self, now: datetime) -> str:
        return now.strftime("%Y-%m-%d")

    def _week_key(self, now: datetime) -> str:
        return now.strftime("%Y-%W")

    def update_period(self, equity: float, now: Optional[datetime] = None) -> None:
        """À appeler à chaque cycle : gère le reset jour/semaine."""
        now = now or datetime.now()
        day_key = self._day_key(now)
        week_key = self._week_key(now)
        previous_state = (
            self._day_start_equity, self._week_start_equity,
            self._current_day, self._current_week, self._paused, self._pause_reason,
        )

        if self._current_day != day_key:
            self._current_day = day_key
            self._day_start_equity = equity
            # Un nouveau jour lève automatiquement une pause liée au drawdown journalier
            if self._paused and "journalier" in self._pause_reason:
                self._paused = False
                self._pause_reason = ""

        if self._current_week != week_key:
            self._current_week = week_key
            self._week_start_equity = equity
            if self._paused and "hebdomadaire" in self._pause_reason:
                self._paused = False
                self._pause_reason = ""
        try:
            self._persist_state()
        except RuntimeError:
            (
                self._day_start_equity, self._week_start_equity,
                self._current_day, self._current_week, self._paused, self._pause_reason,
            ) = previous_state
            raise

    def record_trade_result(self, pnl: float) -> None:
        """À appeler à chaque clôture de trade."""
        previous_losses = self._consecutive_losses
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0
        try:
            self._persist_state()
        except RuntimeError:
            self._consecutive_losses = previous_losses
            raise

    def check(self, equity: float, now: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Vérifie tous les critères d'arrêt. Retourne (autorisé_a_trader, raison).
        Met aussi à jour l'état interne de pause.
        """
        now = now or datetime.now()
        self.update_period(equity, now)

        if self._day_start_equity > 0:
            loss_day = self._day_start_equity - equity
            daily_dd = loss_day / self._day_start_equity * 100
            if daily_dd >= self.daily_limit_pct and loss_day >= self.min_loss_amount:
                self._paused = True
                self._pause_reason = (
                    f"Drawdown journalier de {daily_dd:.1f}% ({loss_day:.2f}$) "
                    f"(limite {self.daily_limit_pct}%) — pause jusqu'à demain"
                )
                self._persist_state()
                return False, self._pause_reason

        if self._week_start_equity > 0:
            loss_week = self._week_start_equity - equity
            weekly_dd = loss_week / self._week_start_equity * 100
            if weekly_dd >= self.weekly_limit_pct and loss_week >= self.min_loss_amount:
                self._paused = True
                self._pause_reason = (
                    f"Drawdown hebdomadaire de {weekly_dd:.1f}% ({loss_week:.2f}$) "
                    f"(limite {self.weekly_limit_pct}%) — pause jusqu'à la semaine prochaine"
                )
                self._persist_state()
                return False, self._pause_reason

        if self._consecutive_losses >= self.max_consecutive_losses:
            self._paused = True
            self._pause_reason = (
                f"{self._consecutive_losses} pertes consécutives "
                f"(limite {self.max_consecutive_losses}) — pause manuelle requise"
            )
            self._persist_state()
            return False, self._pause_reason

        if self._paused:
            self._persist_state()
            return False, self._pause_reason

        self._persist_state()
        return True, "OK"

    def reset_consecutive_losses(self):
        """Permet un reset manuel après revue humaine (ex: après un arrêt sur pertes consécutives)."""
        previous_state = (self._consecutive_losses, self._paused, self._pause_reason)
        self._consecutive_losses = 0
        if self._paused and "consécutives" in self._pause_reason:
            self._paused = False
            self._pause_reason = ""
        try:
            self._persist_state()
        except RuntimeError:
            self._consecutive_losses, self._paused, self._pause_reason = previous_state
            raise

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def status(self) -> str:
        if self._paused:
            return f"⛔ PAUSE — {self._pause_reason}"
        return f"✅ Actif (pertes consécutives : {self._consecutive_losses}/{self.max_consecutive_losses})"
