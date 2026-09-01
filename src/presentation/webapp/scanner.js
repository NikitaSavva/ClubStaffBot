(() => {
  "use strict";

  const telegram = window.Telegram?.WebApp;
  const panels = {
    idle: document.getElementById("idle-state"),
    loading: document.getElementById("loading-state"),
    selection: document.getElementById("selection-state"),
    success: document.getElementById("success-state"),
    message: document.getElementById("message-state"),
  };
  const scanButton = document.getElementById("scan-button");
  const closeButton = document.getElementById("close-button");
  const athleteName = document.getElementById("athlete-name");
  const athleteBirthDate = document.getElementById("athlete-birth-date");
  const successSessionName = document.getElementById("success-session-name");
  const successSessionTime = document.getElementById("success-session-time");
  const remainingVisits = document.getElementById("remaining-visits");
  const lastVisitNote = document.getElementById("last-visit-note");
  const selectionAthleteName = document.getElementById("selection-athlete-name");
  const selectionAthleteBirthDate = document.getElementById("selection-athlete-birth-date");
  const sessionList = document.getElementById("session-list");
  const noSelectableSessions = document.getElementById("no-selectable-sessions");
  const messageTitle = document.getElementById("message-title");
  const messageText = document.getElementById("message-text");
  const messageContext = document.getElementById("message-context");
  const messageAthleteName = document.getElementById("message-athlete-name");
  const messageSessionName = document.getElementById("message-session-name");
  const messageSessionTime = document.getElementById("message-session-time");

  const errorContent = {
    athlete_qr_expired: { title: "QR-код истёк", text: "Попросите спортсмена открыть «Мой QR» снова." },
    athlete_qr_invalid: { title: "QR не распознан", text: "Не удалось распознать QR спортсмена." },
    athlete_not_found: { title: "Спортсмен не найден", text: "Проверьте QR-код и попробуйте снова." },
    telegram_init_data_invalid: { title: "Сессия Telegram устарела", text: "Закройте сканер и откройте его из меню бота снова." },
    telegram_init_data_expired: { title: "Сессия Telegram устарела", text: "Закройте сканер и откройте его из меню бота снова." },
    scanner_forbidden: { title: "Нет доступа", text: "У вас нет доступа к сканеру." },
    no_active_subscription: { title: "Нет активного абонемента", text: "Необходимо оформить новый через «Выдать абонемент»." },
    subscription_expired: { title: "Абонемент истёк", text: "Необходимо оформить новый абонемент через «Выдать абонемент»." },
    visits_exhausted: { title: "Посещения закончились", text: "Необходимо выдать новый абонемент." },
    no_training_session: { title: "Сегодня нет тренировки", text: "Сегодня для этой группы нет тренировки." },
    training_session_cancelled: { title: "Сегодняшняя тренировка отменена", text: "Отметить посещение нельзя." },
    attendance_already_exists: { title: "Посещение уже отмечено", text: "Повторно отмечать посещение не нужно." },
    training_session_not_allowed: { title: "Тренировка недоступна", text: "Выбранную тренировку нельзя использовать для этого абонемента." },
    training_session_ambiguous: { title: "Не удалось определить тренировку", text: "Для группы найдено несколько тренировок на сегодня. Невозможно однозначно определить занятие." },
  };

  let requestInFlight = false;
  let scanResultHandled = false;
  let currentQrToken = null;
  let selectedSessionId = null;
  let primaryAction = "scan";

  function showPanel(name) {
    Object.entries(panels).forEach(([panelName, panel]) => {
      panel.hidden = panelName !== name;
    });
  }

  function setBusy(isBusy) {
    requestInFlight = isBusy;
    scanButton.disabled = isBusy || (primaryAction === "confirm" && selectedSessionId === null);
    closeButton.disabled = isBusy;
    scanButton.setAttribute("aria-busy", String(isBusy));
  }

  function setPrimaryAction(action, label, enabled = true) {
    primaryAction = action;
    scanButton.textContent = label;
    scanButton.hidden = false;
    scanButton.disabled = requestInFlight || !enabled;
  }

  function notifyHaptic(type) {
    try {
      telegram?.HapticFeedback?.notificationOccurred(type);
    } catch (_error) {
      // Haptics are optional and must never block Attendance.
    }
  }

  function formatBirthDate(value) {
    if (!value) return "Дата рождения не указана";
    const [year, month, day] = value.split("-");
    return year && month && day ? `${day}.${month}.${year}` : "Дата рождения не указана";
  }

  function formatTime(value) {
    const localTime = typeof value === "string" ? value.match(/T(\d{2}):(\d{2})/) : null;
    return localTime ? `${localTime[1]}:${localTime[2]}` : "";
  }

  function renderMessageContext(details) {
    const athlete = details?.athlete;
    const session = details?.session;
    messageAthleteName.textContent = athlete?.full_name || "";
    messageSessionName.textContent = session ? `${session.sport_direction_name} · ${session.group_name}` : "";
    messageSessionTime.textContent = session ? formatTime(session.starts_at) : "";
    messageContext.hidden = !athlete?.full_name;
  }

  function showMessage(code, fallbackText, details = {}) {
    const content = errorContent[code] || { title: "Не удалось отметить посещение", text: fallbackText || "Попробуйте ещё раз." };
    messageTitle.textContent = content.title;
    messageText.textContent = content.text;
    renderMessageContext(details);
    showPanel("message");
    if (["telegram_init_data_invalid", "telegram_init_data_expired", "scanner_forbidden"].includes(code)) {
      scanButton.hidden = true;
    } else {
      setPrimaryAction("scan", "Сканировать следующий");
    }
    notifyHaptic("error");
  }

  function renderSuccess(data) {
    athleteName.textContent = data.athlete.full_name;
    athleteBirthDate.textContent = formatBirthDate(data.athlete.birth_date);
    successSessionName.textContent = data.session ? `${data.session.sport_direction_name} · ${data.session.group_name}` : "";
    successSessionTime.textContent = data.session ? formatTime(data.session.starts_at) : "";
    remainingVisits.textContent = Number.isInteger(data.remaining_visits) ? `Осталось посещений: ${data.remaining_visits}` : "";
    remainingVisits.hidden = !Number.isInteger(data.remaining_visits) || data.subscription_finished;
    lastVisitNote.hidden = !data.subscription_finished;
    showPanel("success");
    setPrimaryAction("scan", "Сканировать следующий");
    notifyHaptic("success");
  }

  function selectSession(button, sessionId) {
    if (requestInFlight) return;
    sessionList.querySelectorAll(".session-row").forEach((row) => {
      row.classList.remove("session-row--selected");
      row.setAttribute("aria-checked", "false");
    });
    button.classList.add("session-row--selected");
    button.setAttribute("aria-checked", "true");
    selectedSessionId = sessionId;
    setPrimaryAction("confirm", "Отметить посещение");
  }

  function renderSessionSelection(data) {
    selectionAthleteName.textContent = data.athlete.full_name;
    selectionAthleteBirthDate.textContent = formatBirthDate(data.athlete.birth_date);
    sessionList.replaceChildren();
    selectedSessionId = null;
    data.sessions.forEach((session) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "session-row";
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", "false");
      button.disabled = !session.selectable;
      if (!session.selectable) button.classList.add("session-row--cancelled");

      const sessionTime = document.createElement("span");
      sessionTime.className = "session-time";
      sessionTime.textContent = formatTime(session.starts_at);
      const identity = document.createElement("span");
      identity.className = "session-identity";
      const direction = document.createElement("strong");
      direction.textContent = session.sport_direction_name;
      const group = document.createElement("span");
      group.textContent = session.group_name;
      identity.append(direction, group);
      button.append(sessionTime, identity);
      if (!session.selectable) {
        const label = document.createElement("span");
        label.className = "session-status";
        label.textContent = "Отменена";
        button.append(label);
      } else {
        button.addEventListener("click", () => selectSession(button, session.training_session_id));
      }
      sessionList.append(button);
    });
    noSelectableSessions.hidden = data.sessions.some((session) => session.selectable);
    showPanel("selection");
    setPrimaryAction("confirm", "Отметить посещение", false);
  }

  async function submitAttendance(token, trainingSessionId = null) {
    if (requestInFlight) return;
    setBusy(true);
    showPanel("loading");
    try {
      const response = await fetch("/api/webapp/scanner/attendance", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": telegram.initData },
        body: JSON.stringify({ token, training_session_id: trainingSessionId }),
      });
      let data = null;
      try { data = await response.json(); } catch (_error) { data = null; }
      if (!response.ok) {
        showMessage(data?.code, data?.message, data?.details);
      } else if (data.state === "session_selection_required") {
        currentQrToken = token;
        renderSessionSelection(data);
      } else if (data.state === "confirmed") {
        renderSuccess(data);
      } else {
        showMessage(null, "Сервер вернул неизвестный результат.");
      }
    } catch (_error) {
      showMessage(null, "Нет связи с сервером. Попробуйте ещё раз.");
    } finally {
      setBusy(false);
    }
  }

  function scannerSupported() {
    return Boolean(telegram && typeof telegram.showScanQrPopup === "function" && typeof telegram.closeScanQrPopup === "function" && typeof telegram.isVersionAtLeast === "function" && telegram.isVersionAtLeast("6.4"));
  }

  function startScan() {
    if (requestInFlight) return;
    if (!scannerSupported()) {
      showMessage(null, "Сканирование QR недоступно в этой версии Telegram. Обновите приложение.");
      return;
    }
    currentQrToken = null;
    selectedSessionId = null;
    scanResultHandled = false;
    try {
      telegram.showScanQrPopup({ text: "Наведите камеру на QR спортсмена" }, (qrText) => {
        if (!qrText || scanResultHandled || requestInFlight) return false;
        scanResultHandled = true;
        currentQrToken = qrText;
        telegram.closeScanQrPopup();
        void submitAttendance(qrText);
        return true;
      });
    } catch (_error) {
      showMessage(null, "Сканирование QR недоступно в этой версии Telegram. Обновите приложение.");
    }
  }

  scanButton.addEventListener("click", () => {
    if (primaryAction === "confirm" && currentQrToken && selectedSessionId) {
      void submitAttendance(currentQrToken, selectedSessionId);
    } else {
      startScan();
    }
  });
  closeButton.addEventListener("click", () => {
    if (telegram && typeof telegram.close === "function") telegram.close(); else window.close();
  });

  const previewParameters = new URLSearchParams(window.location.search);
  const previewState = previewParameters.get("preview");
  const previewTheme = previewParameters.get("theme");
  const isLocalPreview = ["localhost", "127.0.0.1"].includes(window.location.hostname) && ["idle", "loading", "success", "selection", "error"].includes(previewState);
  if (isLocalPreview) {
    if (["light", "dark"].includes(previewTheme)) document.documentElement.classList.add(`preview-${previewTheme}`);
    if (previewState === "loading") { setBusy(true); showPanel("loading"); }
    else if (previewState === "success") renderSuccess({ athlete: { full_name: "Иван Иванов", birth_date: "1991-12-27" }, session: { sport_direction_name: "Кикбоксинг", group_name: "Взрослые #1", starts_at: "2026-09-01T19:00:00+03:00" }, remaining_visits: 7, subscription_finished: false });
    else if (previewState === "selection") {
      currentQrToken = "preview-token";
      renderSessionSelection({ athlete: { full_name: "Иван Иванов", birth_date: "1991-12-27" }, sessions: [
        { training_session_id: 1, starts_at: "2026-09-01T08:30:00+03:00", sport_direction_name: "Кикбоксинг", group_name: "Взрослые", selectable: true },
        { training_session_id: 2, starts_at: "2026-09-01T18:45:00+03:00", sport_direction_name: "Кикбоксинг", group_name: "Девушки", selectable: false },
        { training_session_id: 3, starts_at: "2026-09-01T20:00:00+03:00", sport_direction_name: "MMA", group_name: "Взрослые", selectable: true },
      ] });
    } else if (previewState === "error") showMessage("subscription_expired", null, { athlete: { full_name: "Иван Иванов" } });
    else showPanel("idle");
    return;
  }

  if (telegram) { telegram.ready(); telegram.expand(); }
  if (!telegram || !telegram.initData) {
    showMessage(null, "Откройте сканер из меню бота в Telegram.");
    scanButton.hidden = true;
    return;
  }
  if (!scannerSupported()) {
    showMessage(null, "Сканирование QR недоступно в этой версии Telegram. Обновите приложение.");
    scanButton.hidden = true;
  }
})();
