"""
Commandes Telegram du bot MT5 : consulter, mettre en repos, fermer des trades.

Exécutées par la boucle principale du bot (jamais par le thread Telegram).
Chaque handler retourne le texte de la réponse.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Dict, List

CONFIRM_DELAY_S = 60

HELP = """🤖 Commandes du bot

CONSULTER
/statut — état du bot et du compte
/positions — trades ouverts
/trades [n] — derniers trades fermés
/bilan — résultat jour / semaine / total
/activite — dernières actions du bot
/symboles — symboles surveillés

CONTRÔLER
/pause — repos : plus de NOUVEAUX trades (les trades ouverts restent gérés par leur SL/TP)
/reprise — reprend le trading
/reset_garde — réinitialise le compteur de pertes après confirmation humaine
/fermer TICKET — ferme un trade (ou /fermer SYMBOLE)
/toutfermer — ferme tout + repos (confirmation demandée)
/exclure SYMBOLE — ne plus trader ce symbole
/inclure SYMBOLE — le retrader
/stop — arrête complètement le bot (confirmation demandée)

Les actions sensibles se confirment avec /oui (ou /non) dans la minute."""


def _fmt(v: float) -> str:
    return f"{v:+,.2f}".replace(",", " ")


class BotCommands:
    def __init__(self, bot):
        self.bot = bot
        self._pending = None            # (action, expiration, libellé)

    # ── dispatch ──────────────────────────────────────────────────
    def handle(self, text: str) -> str:
        parts = text.strip().split()
        if not parts or not parts[0].startswith("/"):
            return "Je comprends seulement les commandes. Tapez /aide."
        cmd = parts[0][1:].split("@")[0].lower()
        args = parts[1:]
        handler = {
            "start": self.cmd_aide, "aide": self.cmd_aide, "help": self.cmd_aide,
            "statut": self.cmd_statut, "status": self.cmd_statut,
            "positions": self.cmd_positions, "trades": self.cmd_trades,
            "bilan": self.cmd_bilan, "activite": self.cmd_activite,
            "symboles": self.cmd_symboles,
            "pause": self.cmd_pause, "reprise": self.cmd_reprise,
            "reset_garde": self.cmd_reset_garde,
            "fermer": self.cmd_fermer, "toutfermer": self.cmd_toutfermer,
            "exclure": self.cmd_exclure, "inclure": self.cmd_inclure,
            "stop": self.cmd_stop, "oui": self.cmd_oui, "non": self.cmd_non,
        }.get(cmd)
        if handler is None:
            return f"Commande inconnue : /{cmd}. Tapez /aide."
        try:
            return handler(args)
        except Exception as e:                                   # ne jamais faire tomber le bot
            return f"⚠️ Erreur pendant /{cmd} : {e}"

    # ── consultation ──────────────────────────────────────────────
    def cmd_aide(self, args) -> str:
        return HELP

    def cmd_statut(self, args) -> str:
        b = self.bot
        acc = b.mt5.get_account_summary() or {}
        if not acc:
            return "⚠️ Connexion à MetaTrader 5 perdue (compte illisible). Vérifiez que MT5 est ouvert."
        pos = b.mt5.get_open_positions()
        state = "⏸ EN REPOS (commande /pause)" if b.user_paused else "▶️ ACTIF"
        nxt = "—"
        if b._last_cycle:
            nxt = f"{max(0, int(b.live_config['scan_interval_seconds'] - (datetime.now() - b._last_cycle).total_seconds()))} s"
        out = [
            f"🤖 Bot {b.broker} — {'DÉMO' if b.demo else 'RÉEL'}",
            f"État : {state}",
            f"Garde-fou : {b.drawdown_guard.status}",
            f"Solde : {acc.get('balance', 0):,.2f} | Equity : {acc.get('equity', 0):,.2f}",
            f"Résultat flottant : {_fmt(acc.get('profit', 0))}",
            f"Positions : {len(pos)}/{b.live_config['max_positions']}",
            f"Symboles surveillés : {len(b.symbol_map) - len(b.disabled_symbols)}"
            + (f" ({len(b.disabled_symbols)} exclu(s))" if b.disabled_symbols else ""),
            f"Dernier scan : {b._last_cycle:%H:%M:%S}" if b._last_cycle else "Dernier scan : —",
            f"Prochain scan dans : {nxt}",
        ]
        return "\n".join(out)

    def cmd_positions(self, args) -> str:
        pos = self.bot.mt5.get_open_positions()
        if not pos:
            return "Aucune position ouverte."
        lines, total = [], 0.0
        for p in pos:
            total += p.profit
            icon = "🟢" if p.profit >= 0 else "🔴"
            lines.append(
                f"{icon} #{p.ticket} {p.symbol} {p.type.upper()} {p.volume} lot\n"
                f"   entrée {p.open_price:g} → actuel {p.current_price:g}\n"
                f"   SL {p.stop_loss:g} | TP {p.take_profit:g} | résultat {_fmt(p.profit)}")
        lines.append(f"\nTotal flottant : {_fmt(total)}\nPour fermer : /fermer TICKET")
        return "\n".join(lines)

    def _closed_rows(self) -> List[Dict]:
        return [r for r in self.bot.journal._read_all() if r.get("status") == "CLOSED"]

    def cmd_trades(self, args) -> str:
        n = 8
        if args and args[0].isdigit():
            n = max(1, min(25, int(args[0])))
        rows = self._closed_rows()[-n:]
        if not rows:
            return "Aucun trade clôturé pour l'instant."
        lines = []
        for r in reversed(rows):
            pnl = float(r.get("pnl") or 0)
            lines.append(f"{'✅' if pnl >= 0 else '❌'} {str(r.get('exit_date', ''))[:16]} "
                         f"{r.get('ticker')} [{r.get('strategy')}] {_fmt(pnl)}")
        return "\n".join(lines)

    def cmd_bilan(self, args) -> str:
        rows = self._closed_rows()
        today = datetime.now().date()
        def total(since):
            s, n = 0.0, 0
            for r in rows:
                try:
                    d = datetime.strptime(str(r.get("exit_date"))[:10], "%Y-%m-%d").date()
                    if since is None or d >= since:
                        s += float(r.get("pnl") or 0)
                        n += 1
                except ValueError:
                    continue
            return s, n
        d, dn = total(today)
        w, wn = total(today - timedelta(days=6))
        t, tn = total(None)
        st = self.bot.journal.compute_stats()
        extra = ""
        if st.get("nb_trades"):
            extra = (f"\nRéussite : {st['win_rate']} % | Profit factor : {st['profit_factor']}"
                     f"\nDrawdown max : {st['max_drawdown_pct']} %")
        return (f"📊 Bilan\nAujourd'hui : {_fmt(d)} ({dn} trade(s))\n"
                f"7 derniers jours : {_fmt(w)} ({wn})\nTotal : {_fmt(t)} ({tn}){extra}")

    def cmd_activite(self, args) -> str:
        act = list(self.bot.activity)[-12:]
        return "\n".join(reversed(act)) if act else "Aucune activité enregistrée."

    def cmd_symboles(self, args) -> str:
        b = self.bot
        lines = []
        for canon, real in b.symbol_map.items():
            off = canon in b.disabled_symbols
            lines.append(f"{'🚫' if off else '✔'} {real}" + (" (exclu)" if off else ""))
        return "\n".join(lines) or "Aucun symbole."

    # ── contrôle ──────────────────────────────────────────────────
    def cmd_pause(self, args) -> str:
        self.bot.user_paused = True
        self.bot._log("⏸ Repos demandé par Telegram")
        self.bot._cycle_now = True
        return ("⏸ Bot en REPOS : plus aucun nouveau trade.\n"
                "Les trades déjà ouverts restent protégés par leur SL/TP et suivis.\n"
                "/reprise pour relancer. (Un redémarrage du bot annule le repos.)")

    def cmd_reprise(self, args) -> str:
        self.bot.user_paused = False
        self.bot._log("▶️ Reprise demandée par Telegram")
        self.bot._cycle_now = True
        extra = ""
        if self.bot.drawdown_guard.is_paused:
            extra = f"\n⚠️ Le garde-fou drawdown reste actif : {self.bot.drawdown_guard.status}"
        return "▶️ Trading repris." + extra

    def cmd_reset_garde(self, args) -> str:
        guard = self.bot.drawdown_guard
        if not guard.is_paused:
            return "Le garde-fou n'est pas en pause."
        if "pertes consécutives" not in guard.status:
            return "La pause vient d'une limite de drawdown et restera active jusqu'au prochain jour ou à la prochaine semaine."
        return self._ask(
            "reset_losses",
            "Réinitialiser le compteur de pertes consécutives ? Vérifiez les positions et le journal avant de confirmer.",
        )

    def _match_positions(self, key: str):
        pos = self.bot.mt5.get_open_positions()
        if key.isdigit():
            return [p for p in pos if str(p.ticket) == key], pos
        k = key.lower()
        return [p for p in pos if k in p.symbol.lower()], pos

    def _close(self, p) -> bool:
        ok = self.bot.mt5.close_position(p.ticket, p.symbol, p.volume, p.type)
        self.bot._log(f"{'🔒' if ok else '❌'} Fermeture {'réussie' if ok else 'ÉCHOUÉE'} #{p.ticket} {p.symbol} (Telegram)")
        return ok

    def cmd_fermer(self, args) -> str:
        if not args:
            return "Indiquez le ticket : /fermer 123456 (voir /positions)"
        matches, allpos = self._match_positions(" ".join(args))
        if not matches:
            return "Aucune position ne correspond. Voir /positions."
        if len(matches) > 1:
            return ("Plusieurs positions correspondent, précisez le ticket :\n"
                    + "\n".join(f"#{p.ticket} {p.symbol} {p.type}" for p in matches))
        p = matches[0]
        if self._close(p):
            self.bot._cycle_now = True
            return (f"🔒 Position #{p.ticket} {p.symbol} fermée ({_fmt(p.profit)} environ).\n"
                    f"Si un nouveau signal apparaît, le bot peut rouvrir ce symbole : /exclure {p.symbol}")
        return f"❌ Échec de fermeture de #{p.ticket}. Vérifiez MT5 (trading algo activé ? marché ouvert ?)."

    def _ask(self, action: str, label: str) -> str:
        self._pending = (action, time.time() + CONFIRM_DELAY_S, label)
        return f"⚠️ {label}\nConfirmez avec /oui (ou /non pour annuler) dans les {CONFIRM_DELAY_S} secondes."

    def cmd_toutfermer(self, args) -> str:
        pos = self.bot.mt5.get_open_positions()
        if not pos:
            return "Aucune position ouverte à fermer."
        return self._ask("closeall", f"Fermer les {len(pos)} position(s) ouverte(s) et mettre le bot en repos ?")

    def cmd_stop(self, args) -> str:
        return self._ask("stop", "Arrêter complètement le bot ? Les trades ouverts RESTENT ouverts "
                                 "(protégés par leur SL/TP, mais plus suivis par le bot).")

    def cmd_non(self, args) -> str:
        if self._pending:
            self._pending = None
            return "Annulé."
        return "Rien à annuler."

    def cmd_oui(self, args) -> str:
        if not self._pending:
            return "Aucune action en attente."
        action, expires, _ = self._pending
        self._pending = None
        if time.time() > expires:
            return "Délai dépassé, action annulée. Refaites la commande."
        if action == "closeall":
            self.bot.user_paused = True
            res = [(p, self._close(p)) for p in self.bot.mt5.get_open_positions()]
            self.bot._cycle_now = True
            ok = sum(1 for _, r in res if r)
            msg = f"🔒 {ok}/{len(res)} position(s) fermée(s). Bot en REPOS (/reprise pour relancer)."
            bad = [p for p, r in res if not r]
            if bad:
                msg += "\n❌ Échec : " + ", ".join(f"#{p.ticket} {p.symbol}" for p in bad)
            return msg
        if action == "stop":
            self.bot._stop_requested = True
            return "⛔ Arrêt du bot en cours."
        if action == "reset_losses":
            self.bot.drawdown_guard.reset_consecutive_losses()
            self.bot._log("Compteur de pertes consécutives réinitialisé après confirmation Telegram")
            self.bot._cycle_now = True
            return "Compteur de pertes réinitialisé après confirmation. Le bot reprend uniquement si les autres garde-fous l'autorisent."
        return "Action inconnue."

    def _find_symbol(self, key: str):
        k = key.lower()
        for canon, real in self.bot.symbol_map.items():
            if k in (canon.lower(), real.lower()):
                return canon
        cands = [c for c, r in self.bot.symbol_map.items() if k in c.lower() or k in r.lower()]
        return cands[0] if len(cands) == 1 else None

    def cmd_exclure(self, args) -> str:
        if not args:
            return "Indiquez le symbole : /exclure V75 (voir /symboles)"
        c = self._find_symbol(" ".join(args))
        if not c:
            return "Symbole introuvable ou ambigu. Voir /symboles."
        self.bot.disabled_symbols.add(c)
        self.bot._log(f"🚫 {c} exclu (Telegram)")
        return f"🚫 {self.bot.symbol_map[c]} exclu : plus de nouveaux trades dessus. /inclure {c} pour annuler."

    def cmd_inclure(self, args) -> str:
        if not args:
            return "Indiquez le symbole : /inclure V75"
        c = self._find_symbol(" ".join(args))
        if not c:
            return "Symbole introuvable ou ambigu. Voir /symboles."
        self.bot.disabled_symbols.discard(c)
        self.bot._log(f"✔ {c} ré-inclus (Telegram)")
        return f"✔ {self.bot.symbol_map[c]} de nouveau actif."
