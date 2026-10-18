"""
Filtre d'actualités économiques (NFP, FOMC, CPI, etc.)

Récupère un calendrier économique réel (flux JSON hebdomadaire
communément utilisé par les bots — miroir public des données
Forex Factory) et bloque automatiquement les nouvelles ouvertures
de position autour des annonces à fort impact.

Fonctionnement :
- Téléchargement + cache local (le calendrier est valable ~1 semaine)
- Si le réseau est indisponible : fallback sur le cache existant,
  puis sur une liste "de secours" mensuelle codée en dur (NFP =
  1er vendredi du mois, FOMC ≈ 8 réunions/an, CPI ≈ mi-mois) pour
  ne jamais laisser le bot trader "à l'aveugle" en cas de panne réseau.
- Ne bloque JAMAIS silencieusement : chaque décision peut être loguée.
"""

from __future__ import annotations

import json
import time
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


# Flux hebdomadaire public (agrégateur de l'agenda Forex Factory,
# largement utilisé par la communauté de bots de trading).
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", ".cache", "economic_calendar.json")
CACHE_TTL_SECONDS = 6 * 3600   # rafraîchir toutes les 6h

# Devises → actifs concernés (pour filtrer les news pertinentes par symbole)
CURRENCY_TO_ASSETS = {
    "USD": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD",
            "US500", "US100", "SPY", "QQQ", "XAUUSD", "BTCUSD", "ETHUSD"],
    "EUR": ["EURUSD", "EURJPY", "EURGBP", "DE40", "FR40"],
    "GBP": ["GBPUSD", "GBPJPY", "UK100"],
    "JPY": ["USDJPY", "EURJPY", "GBPJPY", "JP225"],
    "CHF": ["USDCHF"],
    "AUD": ["AUDUSD", "AUDJPY"],
    "CAD": ["USDCAD", "CADJPY"],
}

HIGH_IMPACT_KEYWORDS = [
    "NFP", "Non-Farm", "Non Farm", "Nonfarm",
    "FOMC", "Federal Funds", "Fed Interest Rate", "Rate Decision",
    "CPI", "Consumer Price Index",
    "GDP", "Unemployment Rate", "Interest Rate Decision",
    "ECB Press Conference", "ECB Interest Rate",
]


@dataclass
class EconomicEvent:
    title: str
    country: str        # code devise, ex: 'USD'
    date: datetime       # timezone-aware UTC
    impact: str          # 'High' | 'Medium' | 'Low'

    def is_high_impact(self) -> bool:
        if self.impact.lower() == 'high':
            return True
        return any(k.lower() in self.title.lower() for k in HIGH_IMPACT_KEYWORDS)


class EconomicCalendar:
    """
    Charge et interroge le calendrier économique.
    Bloque le trading N minutes avant/après une news à fort impact.
    """

    def __init__(self, buffer_minutes: int = 30, verbose: bool = False):
        self.buffer_minutes = buffer_minutes
        self.verbose = verbose
        self.events: List[EconomicEvent] = []
        self._loaded = False

    # ────────────────────────────────────────────────────────
    # CHARGEMENT
    # ────────────────────────────────────────────────────────

    def load(self, force_refresh: bool = False) -> bool:
        """Charge le calendrier (cache si récent, sinon télécharge)."""
        cache_dir = os.path.dirname(CACHE_PATH)
        os.makedirs(cache_dir, exist_ok=True)

        if not force_refresh and os.path.exists(CACHE_PATH):
            age = time.time() - os.path.getmtime(CACHE_PATH)
            if age < CACHE_TTL_SECONDS:
                return self._load_from_cache()

        if REQUESTS_AVAILABLE:
            try:
                resp = requests.get(CALENDAR_URL, timeout=8)
                resp.raise_for_status()
                raw = resp.json()
                with open(CACHE_PATH, 'w', encoding='utf-8') as f:
                    json.dump(raw, f)
                self._parse(raw)
                self._loaded = True
                if self.verbose:
                    print(f"  📅 Calendrier économique mis à jour ({len(self.events)} événements)")
                return True
            except Exception as e:
                if self.verbose:
                    print(f"  ⚠️  Impossible de télécharger le calendrier ({e}) — fallback")

        # Fallback 1 : cache existant même périmé
        if os.path.exists(CACHE_PATH) and self._load_from_cache():
            if self.verbose:
                print("  ⚠️  Calendrier chargé depuis le cache (périmé, réseau indisponible)")
            return True

        # Fallback 2 : estimation de secours (ne bloque pas totalement le bot)
        self.events = self._fallback_estimated_events()
        self._loaded = True
        if self.verbose:
            print("  ⚠️  Calendrier de secours utilisé (estimation NFP/FOMC/CPI) — "
                  "vérifiez manuellement forexfactory.com")
        return True

    def _load_from_cache(self) -> bool:
        try:
            with open(CACHE_PATH, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            self._parse(raw)
            self._loaded = True
            return True
        except Exception:
            return False

    def _parse(self, raw: List[Dict]) -> None:
        events = []
        for item in raw:
            try:
                # Format ff_calendar : {"title","country","date","impact",...}
                dt_str = item.get('date')
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00')) if dt_str else None
                if dt is None:
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                events.append(EconomicEvent(
                    title=item.get('title', 'Événement'),
                    country=item.get('country', ''),
                    date=dt,
                    impact=item.get('impact', 'Low'),
                ))
            except Exception:
                continue
        self.events = events

    # Dates FOMC 2026 officielles (Federal Reserve, calendrier confirmé) —
    # 2ᵉ jour de chaque réunion = jour de la décision de taux, 14h00 ET.
    # Converti en UTC selon l'heure US en vigueur à cette date (EST=UTC-5 en
    # janv./déc., EDT=UTC-4 le reste de l'année, DST du 8 mars au 1er nov. 2026).
    FOMC_DECISION_DATES_2026 = [
        (1, 28, 19), (3, 18, 18), (4, 29, 18), (6, 17, 18),
        (7, 29, 18), (9, 16, 18), (10, 28, 18), (12, 9, 19),
    ]

    def _fallback_estimated_events(self) -> List[EconomicEvent]:
        """
        Estimation utilisée quand aucune donnée n'est disponible (réseau coupé
        et pas de cache) :
        - FOMC : dates officielles 2026 codées en dur (vérifiées sur
          federalreserve.gov) ; au-delà de 2026, non estimable -> absent,
          à vérifier manuellement.
        - NFP  : 1er vendredi du mois, 13h30 UTC (approximatif, US BLS)
        - CPI  : ~12 du mois, 13h30 UTC (approximatif, US BLS)
        """
        now = datetime.now(timezone.utc)
        events = []

        if now.year == 2026:
            for month, day, hour_utc in self.FOMC_DECISION_DATES_2026:
                d = datetime(2026, month, day, hour_utc, 0, tzinfo=timezone.utc)
                if d >= now - timedelta(days=1):
                    events.append(EconomicEvent("FOMC Rate Decision (officiel)", "USD", d, "High"))

        for month_offset in (0, 1):
            year = now.year + (1 if now.month + month_offset > 12 else 0)
            month = (now.month + month_offset - 1) % 12 + 1
            d = datetime(year, month, 1, 13, 30, tzinfo=timezone.utc)
            while d.weekday() != 4:  # vendredi
                d += timedelta(days=1)
            events.append(EconomicEvent("NFP (estimation)", "USD", d, "High"))
            cpi_date = datetime(year, month, 12, 13, 30, tzinfo=timezone.utc)
            events.append(EconomicEvent("CPI (estimation)", "USD", cpi_date, "High"))
        return events

    # ────────────────────────────────────────────────────────
    # INTERROGATION
    # ────────────────────────────────────────────────────────

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    def get_upcoming_events(self, hours_ahead: int = 24,
                             high_impact_only: bool = True) -> List[EconomicEvent]:
        self._ensure_loaded()
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(hours=hours_ahead)
        result = [e for e in self.events if now <= e.date <= horizon]
        if high_impact_only:
            result = [e for e in result if e.is_high_impact()]
        return sorted(result, key=lambda e: e.date)

    def is_blocked(self, symbol: Optional[str] = None,
                    now: Optional[datetime] = None) -> (bool, Optional[EconomicEvent]):
        """
        Retourne (bloqué: bool, événement: EconomicEvent|None).
        Bloque si une news à fort impact tombe dans
        [-buffer_minutes ; +buffer_minutes] autour de maintenant,
        et si elle concerne la devise/l'actif demandé (ou toutes si symbol=None).
        """
        self._ensure_loaded()
        now = now or datetime.now(timezone.utc)
        window = timedelta(minutes=self.buffer_minutes)

        relevant_currencies = None
        if symbol:
            relevant_currencies = {
                cur for cur, assets in CURRENCY_TO_ASSETS.items()
                if symbol.upper() in [a.upper() for a in assets]
            }

        for e in self.events:
            if not e.is_high_impact():
                continue
            if relevant_currencies is not None and e.country.upper() not in relevant_currencies:
                # Si on n'a pas pu déterminer la devise concernée par le symbole,
                # on reste prudent et on bloque quand même sur USD (devise dominante).
                if relevant_currencies:
                    continue
            if e.date - window <= now <= e.date + window:
                return True, e

        return False, None

    def summary(self, hours_ahead: int = 48) -> str:
        events = self.get_upcoming_events(hours_ahead=hours_ahead)
        if not events:
            return f"✅ Aucune news à fort impact dans les prochaines {hours_ahead}h"
        lines = [f"📅 News à fort impact dans les prochaines {hours_ahead}h :"]
        for e in events:
            lines.append(f"   {e.date.strftime('%d/%m %H:%M')} UTC — {e.country} — {e.title}")
        return "\n".join(lines)
