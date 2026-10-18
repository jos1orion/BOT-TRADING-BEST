(() => {
  const telegram = window.Telegram && window.Telegram.WebApp;
  const localPreview = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  const message = document.getElementById("message");
  let latestState = null;
  let selectedPeriod = "7";
  let visibleTrades = [];
  let accessPin = "";
  let pinConfigured = false;

  function telegramHeaders() {
    const headers = {};
    if (telegram && telegram.initData) {
      headers.Authorization = `tma ${telegram.initData}`;
    }
    return headers;
  }

  async function responseError(response) {
    try {
      const failure = await response.json();
      return failure.error || `Erreur serveur ${response.status}.`;
    } catch (_error) {
      return `Erreur serveur ${response.status}.`;
    }
  }

  function showPinSetup(configured) {
    pinConfigured = configured;
    latestState = null;
    accessPin = "";
    document.getElementById("dashboard").hidden = true;
    document.getElementById("access-panel").hidden = false;
    document.getElementById("pin-form").hidden = false;
    document.getElementById("pin-input").value = "";
    document.getElementById("pin-confirm").value = "";
    document.getElementById("pin-confirm-wrap").hidden = configured;
    document.getElementById("pin-input").autocomplete =
      configured ? "current-password" : "new-password";
    document.getElementById("access-title").textContent =
      configured ? "Accès sécurisé" : "Créer un code PIN";
    document.getElementById("access-description").textContent =
      configured
        ? "Saisis ton PIN à 6 chiffres pour consulter le tableau de bord."
        : "Définis un PIN à 6 chiffres pour protéger le tableau partagé.";
    document.getElementById("pin-label").textContent =
      configured ? "Code PIN" : "Nouveau code PIN";
    document.getElementById("pin-submit").textContent =
      configured ? "Déverrouiller" : "Créer le PIN";
    document.getElementById("pin-error").textContent = "";
  }

  async function checkPinStatus() {
    try {
      const response = await fetch("/api/pin/status", {
        cache: "no-store",
        headers: telegramHeaders()
      });
      if (!response.ok) throw new Error(await responseError(response));
      const status = await response.json();
      showPinSetup(status.configured === true);
    } catch (error) {
      document.getElementById("pin-form").hidden = true;
      document.getElementById("pin-error").textContent =
        error.message || "Impossible de vérifier l’accès.";
    }
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function money(value, currency) {
    if (value === null || value === undefined) return "—";
    return new Intl.NumberFormat("fr-FR", {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 2
    }).format(value);
  }

  function signedMoney(value, currency) {
    const formatted = money(value, currency);
    return Number(value) > 0 ? `+${formatted}` : formatted;
  }

  function setValue(id, value) {
    document.getElementById(id).textContent = value;
  }

  function setResultValue(id, value, currency) {
    const node = document.getElementById(id);
    node.textContent = signedMoney(value, currency);
    node.classList.toggle("positive", Number(value) > 0);
    node.classList.toggle("negative", Number(value) < 0);
  }

  function renderPosition(position, currency) {
    const card = element("article", "row");
    const details = element("div");
    details.append(
      element("strong", "", `${position.symbol} · ${position.type}`),
      element("span", "muted", `Ticket #${position.ticket} · ${position.volume} lot(s)`),
      element("span", "position-levels",
        `Entrée ${position.open_price ?? "—"} · Actuel ${position.current_price ?? "—"}`),
      element("span", "position-levels",
        `SL ${position.stop_loss || "—"} · TP ${position.take_profit || "—"}`)
    );
    const result = element(
      "strong",
      Number(position.profit) >= 0 ? "positive" : "negative",
      signedMoney(position.profit, currency)
    );
    card.append(details, result);
    return card;
  }

  function renderTrade(trade, currency) {
    const card = element("details", "trade-card");
    const summary = element("summary", "row trade-summary");
    const details = element("span", "trade-summary-main");
    details.append(
      element("strong", "", trade.symbol || "Trade"),
      element("span", "muted", `${trade.strategy || "—"} · ${trade.date || "—"}`)
    );
    const result = element(
      "span",
      Number(trade.pnl) >= 0 ? "positive" : "negative",
      signedMoney(trade.pnl, currency)
    );
    summary.append(details, result);
    const expanded = element("div", "trade-expanded");
    [
      ["Sens", trade.direction || "—"],
      ["Entrée", trade.entry_price == null ? "—" : String(trade.entry_price)],
      ["Sortie", trade.exit_price == null ? "—" : String(trade.exit_price)],
      ["Motif de clôture", trade.exit_reason || "—"]
    ].forEach(([label, value]) => {
      const line = element("p", "trade-detail");
      line.append(element("span", "muted", label), element("strong", "", value));
      expanded.append(line);
    });
    card.append(summary, expanded);
    return card;
  }

  function populateSymbolFilter(trades) {
    const select = document.getElementById("trade-symbol");
    const selected = select.value || "all";
    const symbols = [...new Set(trades.map((trade) => trade.symbol).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
    select.replaceChildren(new Option("Tous", "all"));
    symbols.forEach((symbol) => select.append(new Option(symbol, symbol)));
    select.value = symbols.includes(selected) ? selected : "all";
  }

  function filterTrades(trades) {
    const query = document.getElementById("trade-search").value.trim().toLocaleLowerCase("fr");
    const period = document.getElementById("trade-period").value;
    const outcome = document.getElementById("trade-outcome").value;
    const symbol = document.getElementById("trade-symbol").value;
    const cutoff = period === "all"
      ? 0
      : Date.now() - Number(period) * 24 * 60 * 60 * 1000;
    return trades.filter((trade) => {
      const tradeTimestamp = tradeTime(trade);
      if (tradeTimestamp === null || tradeTimestamp < cutoff) return false;
      if (symbol !== "all" && trade.symbol !== symbol) return false;
      if (query && !`${trade.symbol || ""} ${trade.strategy || ""}`.toLocaleLowerCase("fr").includes(query)) {
        return false;
      }
      const pnl = Number(trade.pnl) || 0;
      if (outcome === "wins" && pnl <= 0) return false;
      if (outcome === "losses" && pnl >= 0) return false;
      return true;
    }).sort((a, b) => (tradeTime(b) || 0) - (tradeTime(a) || 0));
  }

  function renderHistory() {
    if (!latestState) return;
    const trades = latestState.closed_trades || [];
    visibleTrades = filterTrades(trades);
    const currency = latestState.account.currency || "USD";
    document.getElementById("history-count").textContent =
      `${visibleTrades.length} trade(s) affiché(s) sur ${trades.length} chargés (90 derniers maximum).`;
    renderList("history", visibleTrades, renderTrade, "Aucun trade ne correspond aux filtres.", currency);
  }

  function exportVisibleTrades() {
    const fields = [
      ["date", "Date"], ["symbol", "Symbole"], ["strategy", "Stratégie"],
      ["direction", "Sens"], ["entry_price", "Entrée"], ["exit_price", "Sortie"],
      ["exit_reason", "Motif"], ["pnl", "Résultat"]
    ];
    const escapeCsv = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
    const csv = [
      fields.map(([, label]) => escapeCsv(label)).join(";"),
      ...visibleTrades.map((trade) => fields.map(([key]) => escapeCsv(trade[key])).join(";"))
    ].join("\r\n");
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = element("a");
    link.href = url;
    link.download = "hermes-trades-filtres.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  function setRiskUsage(prefix, drawdown, limit) {
    const percentage = Number(drawdown);
    const threshold = Number(limit);
    const valid = drawdown !== null && drawdown !== undefined
      && limit !== null && limit !== undefined
      && Number.isFinite(percentage) && Number.isFinite(threshold) && threshold > 0;
    const usage = valid ? Math.max(0, percentage / threshold * 100) : null;
    const label = document.getElementById(`${prefix}-usage-label`);
    const bar = document.getElementById(`${prefix}-usage-bar`);
    label.textContent = usage === null ? "Indisponible" : `${percentage.toFixed(2)} % / ${threshold} %`;
    bar.style.width = `${usage === null ? 0 : Math.min(100, usage)}%`;
    bar.classList.toggle("warning", usage !== null && usage >= 75 && usage < 100);
    bar.classList.toggle("danger", usage !== null && usage >= 100);
    return usage;
  }

  function renderConnections(state, stale) {
    const mt5Connected = state.connections?.mt5 ?? state.account?.equity != null;
    const connectionItems = [
      ["bot-status", state.connections?.bot !== false && !stale, stale ? "Données anciennes" : "À jour"],
      ["mt5-status", mt5Connected, mt5Connected ? "Connecté" : "Indisponible"],
      ["api-status", true, localPreview ? "Aperçu local" : "Tunnel HTTPS actif"]
    ];
    connectionItems.forEach(([id, connected, text]) => {
      const node = document.getElementById(id);
      node.textContent = text;
      node.classList.toggle("status-ok", connected);
      node.classList.toggle("status-down", !connected);
    });
  }

  function renderList(containerId, items, renderer, emptyText, currency) {
    const container = document.getElementById(containerId);
    container.replaceChildren();
    if (!items.length) {
      container.append(element("p", "empty", emptyText));
      return;
    }
    items.forEach((item) => container.append(renderer(item, currency)));
  }

  function tradeTime(trade) {
    const parsed = Date.parse(trade.date || "");
    return Number.isFinite(parsed) ? parsed : null;
  }

  function renderChart(trades, currency) {
    const container = document.getElementById("performance-chart");
    const summary = document.getElementById("chart-summary");
    const cutoff = selectedPeriod === "all"
      ? 0
      : Date.now() - Number(selectedPeriod) * 24 * 60 * 60 * 1000;
    const filtered = trades
      .map((trade) => ({ ...trade, timestamp: tradeTime(trade) }))
      .filter((trade) => trade.timestamp !== null && trade.timestamp >= cutoff)
      .sort((a, b) => a.timestamp - b.timestamp);
    container.replaceChildren();

    if (!filtered.length) {
      container.append(element("p", "empty", "Pas de trade clôturé sur cette période."));
      summary.textContent = "Le graphique utilise le résultat cumulé des trades clôturés.";
      return;
    }

    const values = [0];
    filtered.forEach((trade) => values.push(values[values.length - 1] + (Number(trade.pnl) || 0)));
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const width = 640;
    const height = 180;
    const padding = 14;
    const points = values.map((value, index) => {
      const x = padding + (index / Math.max(1, values.length - 1)) * (width - padding * 2);
      const y = height - padding - ((value - min) / range) * (height - padding * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `Résultat cumulé : ${money(values[values.length - 1], currency)}`);

    const zeroY = height - padding - ((0 - min) / range) * (height - padding * 2);
    const baseline = document.createElementNS("http://www.w3.org/2000/svg", "line");
    baseline.setAttribute("x1", String(padding));
    baseline.setAttribute("x2", String(width - padding));
    baseline.setAttribute("y1", zeroY.toFixed(1));
    baseline.setAttribute("y2", zeroY.toFixed(1));
    baseline.setAttribute("class", "chart-zero");

    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("points", points);
    line.setAttribute("class", values[values.length - 1] >= 0 ? "chart-line positive-line" : "chart-line negative-line");
    svg.append(baseline, line);
    container.append(svg);

    const total = values[values.length - 1];
    summary.textContent = `${filtered.length} trade(s) · Résultat cumulé : ${money(total, currency)}`;
    summary.className = `muted chart-summary ${total >= 0 ? "positive" : "negative"}`;
  }

  function updateFreshness() {
    if (!latestState) return;
    const updatedAt = Date.parse(latestState.updated_at);
    if (!Number.isFinite(updatedAt)) return;
    const ageSeconds = Math.max(0, Math.floor((Date.now() - updatedAt) / 1000));
    const expectedInterval = Number(latestState.info?.interval) || 15;
    const staleAfter = Math.max(90, expectedInterval * 2 + 30);
    const stale = ageSeconds > staleAfter;
    const mode = document.getElementById("mode");
    const freshness = document.getElementById("freshness");
    mode.textContent = stale
      ? (latestState.mode === "DEMO" ? "DÉMO · données anciennes" : "RÉEL · données anciennes")
      : (latestState.mode === "DEMO" ? "Connecté · DÉMO" : "Connecté · RÉEL");
    mode.classList.toggle("connected", !stale);
    mode.classList.toggle("stale", stale);
    freshness.textContent = stale
      ? `Données anciennes · dernière mise à jour il y a ${ageSeconds} s`
      : "Actualisation automatique · 15 s";
    freshness.classList.toggle("warning-text", stale);
    renderConnections(latestState, stale);
    if (stale) {
      message.textContent = "Le bot n’a pas actualisé ses données récemment. Vérifie que le bot et MT5 sont actifs.";
      message.classList.add("warning");
    } else {
      message.textContent = latestState.guard_status || "État du bot disponible.";
      message.classList.toggle("warning", /pause|⛔/i.test(message.textContent));
    }
  }

  function extractLimit(label, limits) {
    const match = new RegExp(`${label}\\s*-?([\\d,.]+)\\s*%`, "i").exec(limits || "");
    return match ? match[1] : "—";
  }

  function render(state) {
    latestState = state;
    const currency = state.account.currency || "USD";
    const localToday = new Date().toLocaleDateString("sv-SE");
    const todayPnl = state.stats.today_pnl ?? (state.closed_trades || [])
      .filter((trade) => (trade.date || "").slice(0, 10) === localToday)
      .reduce((total, trade) => total + (Number(trade.pnl) || 0), 0);

    setValue("equity", money(state.account.equity, currency));
    setValue("balance", money(state.account.balance, currency));
    setResultValue("floating", state.account.profit, currency);
    setResultValue("today-pnl", todayPnl, currency);
    setValue("trades", String(state.stats.nb_trades || 0));
    setValue("win-rate", state.stats.win_rate == null ? "—" : `${state.stats.win_rate} %`);
    setResultValue("net-pnl", state.stats.net_pnl, currency);
    setValue("position-count", String(state.positions.length));
    setValue("updated", `Mis à jour ${state.updated_at}`);
    setValue("drawdown", state.stats.max_drawdown_pct == null
      ? "—" : `${state.stats.max_drawdown_pct} %`);
    const streak = /pertes consécutives\s*:\s*(\d+\s*\/\s*\d+)/i
      .exec(state.guard_status || "");
    setValue("loss-streak", state.info.consecutive_losses != null
      ? `${state.info.consecutive_losses} / ${state.info.max_consecutive_losses ?? "—"}`
      : (streak ? streak[1] : "—"));
    const limits = state.info.limits || "";
    const dailyLimit = state.info.daily_limit_pct ?? extractLimit("jour", limits);
    const weeklyLimit = state.info.weekly_limit_pct ?? extractLimit("semaine", limits);
    setValue("risk-limits", `${dailyLimit} % / ${weeklyLimit} %`);
    setValue("risk-per-trade", state.info.risk == null ? "—" : `${state.info.risk} %`);
    const dailyUsage = setRiskUsage("daily",
      state.info.daily_drawdown_pct,
      state.info.daily_limit_pct);
    const weeklyUsage = setRiskUsage("weekly",
      state.info.weekly_drawdown_pct,
      state.info.weekly_limit_pct);
    const riskAlert = document.getElementById("risk-alert");
    const approachingLimits = [
      ["journalière", dailyUsage],
      ["hebdomadaire", weeklyUsage]
    ].filter(([, usage]) => usage !== null && usage >= 75);
    riskAlert.hidden = approachingLimits.length === 0;
    riskAlert.textContent = approachingLimits.length
      ? `Attention : limite ${approachingLimits.map(([period]) => period).join(" et ")} bientôt atteinte ou dépassée.`
      : "";

    renderList("positions", state.positions, renderPosition,
      "Aucune position ouverte.", currency);
    renderChart(state.closed_trades || [], currency);
    populateSymbolFilter(state.closed_trades || []);
    renderHistory();
    renderList("activity", state.activity || [], (item) => element("p", "activity-item", item),
      "Aucune activité récente.", currency);
    updateFreshness();
  }

  async function refresh() {
    if (!accessPin) return;
    try {
      const headers = telegramHeaders();
      headers["X-MiniApp-PIN"] = accessPin;
      const response = await fetch("/api/state", {
        cache: "no-store",
        headers
      });
      if (!response.ok) {
        const errorText = await responseError(response);
        if (response.status === 403 || response.status === 428) {
          showPinSetup(response.status !== 428);
          document.getElementById("pin-error").textContent = errorText;
          return;
        }
        if (response.status === 429 && !latestState) {
          document.getElementById("pin-error").textContent = errorText;
          return;
        }
        if (response.status === 401) {
          throw new Error(`Authentification Telegram refusée. ${errorText}`);
        }
        throw new Error(errorText || (response.status === 503
          ? "Le bot n’a pas encore publié son état."
          : `Le serveur Mini App a répondu avec l’erreur ${response.status}.`));
      }
      const state = await response.json();
      document.getElementById("access-panel").hidden = true;
      document.getElementById("dashboard").hidden = false;
      document.getElementById("pin-error").textContent = "";
      render(state);
    } catch (error) {
      if (!latestState) {
        document.getElementById("pin-error").textContent =
          error.message || "Impossible de vérifier l’accès.";
        return;
      }
      const mode = document.getElementById("mode");
      mode.textContent = "Non connecté";
      mode.classList.remove("real", "demo", "connected");
      message.textContent = error.message || "Impossible de charger les données du bot.";
      message.classList.add("warning");
    }
  }

  document.querySelectorAll(".period").forEach((button) => {
    button.addEventListener("click", () => {
      selectedPeriod = button.dataset.period;
      document.querySelectorAll(".period").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      if (latestState) renderChart(latestState.closed_trades || [], latestState.account.currency || "USD");
    });
  });
  ["trade-search", "trade-period", "trade-outcome", "trade-symbol"].forEach((id) => {
    document.getElementById(id).addEventListener("input", renderHistory);
    document.getElementById(id).addEventListener("change", renderHistory);
  });
  document.getElementById("export-trades").addEventListener("click", exportVisibleTrades);

  if ((!telegram || !telegram.initData) && !localPreview) {
    document.getElementById("pin-error").textContent =
      "Ouvre cette page depuis le bouton Tableau de bord dans Telegram.";
    document.getElementById("pin-form").hidden = true;
    return;
  }

  document.getElementById("pin-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const pin = document.getElementById("pin-input").value;
    const errorNode = document.getElementById("pin-error");
    errorNode.textContent = "";
    if (!/^\d{6}$/.test(pin)) {
      errorNode.textContent = "Le PIN doit contenir exactement 6 chiffres.";
      return;
    }
    if (!pinConfigured) {
      const confirmation = document.getElementById("pin-confirm").value;
      if (pin !== confirmation) {
        errorNode.textContent = "Les deux codes PIN ne correspondent pas.";
        return;
      }
      try {
        const response = await fetch("/api/pin/setup", {
          method: "POST",
          cache: "no-store",
          headers: {
            ...telegramHeaders(),
            "Content-Type": "application/json"
          },
          body: JSON.stringify({ pin })
        });
        if (!response.ok) throw new Error(await responseError(response));
        pinConfigured = true;
      } catch (error) {
        errorNode.textContent = error.message || "Impossible d’enregistrer le PIN.";
        return;
      }
    }
    accessPin = pin;
    await refresh();
  });

  document.getElementById("show-pin-change").addEventListener("click", () => {
    const panel = document.getElementById("pin-change-panel");
    const button = document.getElementById("show-pin-change");
    const opening = panel.hidden;
    panel.hidden = !opening;
    button.setAttribute("aria-expanded", String(opening));
    button.textContent = opening ? "Fermer" : "Modifier le PIN";
    const form = document.getElementById("pin-change-form");
    document.getElementById("pin-change-error").textContent = "";
    if (opening) {
      document.getElementById("pin-current").focus();
    } else {
      form.reset();
    }
  });

  document.getElementById("pin-change-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const currentPin = document.getElementById("pin-current").value;
    const newPin = document.getElementById("pin-new").value;
    const confirmation = document.getElementById("pin-new-confirm").value;
    const errorNode = document.getElementById("pin-change-error");
    errorNode.textContent = "";
    if (!/^\d{6}$/.test(currentPin) || !/^\d{6}$/.test(newPin)) {
      errorNode.textContent = "Le PIN actuel et le nouveau doivent contenir 6 chiffres.";
      return;
    }
    if (newPin !== confirmation) {
      errorNode.textContent = "Les deux nouveaux PIN ne correspondent pas.";
      return;
    }
    try {
      const response = await fetch("/api/pin/setup", {
        method: "POST",
        cache: "no-store",
        headers: {
          ...telegramHeaders(),
          "Content-Type": "application/json"
        },
        body: JSON.stringify({ pin: newPin, current_pin: currentPin })
      });
      if (!response.ok) throw new Error(await responseError(response));
      accessPin = newPin;
      document.getElementById("pin-change-form").reset();
      document.getElementById("pin-change-panel").hidden = true;
      document.getElementById("show-pin-change").setAttribute("aria-expanded", "false");
      document.getElementById("show-pin-change").textContent = "Modifier le PIN";
      await refresh();
    } catch (error) {
      errorNode.textContent = error.message || "Impossible de modifier le PIN.";
    }
  });

  if (telegram && telegram.initData) {
    telegram.ready();
    telegram.expand();
  }
  checkPinStatus();
  window.setInterval(() => {
    if (accessPin) {
      if (latestState) updateFreshness();
      refresh();
    }
  }, 15000);
})();
