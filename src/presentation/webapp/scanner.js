(() => {
  "use strict";

  const telegram = window.Telegram?.WebApp;
  const panels = {
    idle: document.getElementById("idle-state"),
    loading: document.getElementById("loading-state"),
    success: document.getElementById("success-state"),
    message: document.getElementById("message-state"),
  };
  const scanButton = document.getElementById("scan-button");
  const closeButton = document.getElementById("close-button");
  const athleteName = document.getElementById("athlete-name");
  const athleteBirthDate = document.getElementById("athlete-birth-date");
  const messageTitle = document.getElementById("message-title");
  const messageText = document.getElementById("message-text");

  const errorMessages = {
    athlete_qr_expired:
      "QR-код истёк. Попросите спортсмена открыть «Мой QR» снова.",
    athlete_qr_invalid: "Не удалось распознать QR спортсмена.",
    athlete_not_found: "Спортсмен не найден.",
    telegram_init_data_invalid:
      "Сессия Telegram устарела. Закройте сканер и откройте его из меню бота снова.",
    telegram_init_data_expired:
      "Сессия Telegram устарела. Закройте сканер и откройте его из меню бота снова.",
    scanner_forbidden: "У вас нет доступа к сканеру.",
  };

  let requestInFlight = false;
  let scanResultHandled = false;

  function showPanel(name) {
    Object.entries(panels).forEach(([panelName, panel]) => {
      panel.hidden = panelName !== name;
    });
  }

  function setBusy(isBusy) {
    requestInFlight = isBusy;
    scanButton.disabled = isBusy;
    closeButton.disabled = isBusy;
    scanButton.setAttribute("aria-busy", String(isBusy));
  }

  function setScanAction(label, enabled = true) {
    scanButton.textContent = label;
    scanButton.hidden = false;
    scanButton.disabled = !enabled;
  }

  function notifyHaptic(type) {
    try {
      telegram?.HapticFeedback?.notificationOccurred(type);
    } catch (_error) {
      // Haptics are optional and must never block the scanner flow.
    }
  }

  function showMessage(title, text, canRetry) {
    messageTitle.textContent = title;
    messageText.textContent = text;
    showPanel("message");
    if (canRetry) {
      setScanAction("Попробовать снова");
    } else {
      scanButton.hidden = true;
    }
    notifyHaptic("error");
  }

  function formatBirthDate(value) {
    if (!value) {
      return "Дата рождения не указана";
    }
    const [year, month, day] = value.split("-");
    if (!year || !month || !day) {
      return "Дата рождения не указана";
    }
    return `${day}.${month}.${year}`;
  }

  function renderSuccess(data) {
    athleteName.textContent = data.full_name;
    athleteBirthDate.textContent = formatBirthDate(data.birth_date);
    showPanel("success");
    setScanAction("Сканировать следующий");
    notifyHaptic("success");
  }

  async function resolveQr(token) {
    if (requestInFlight) {
      return;
    }
    setBusy(true);
    showPanel("loading");

    try {
      const response = await fetch("/api/webapp/scanner/resolve", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Telegram-Init-Data": telegram.initData,
        },
        body: JSON.stringify({ token }),
      });
      let data = null;
      try {
        data = await response.json();
      } catch (_error) {
        data = null;
      }

      if (!response.ok) {
        const code = data?.code;
        const text = errorMessages[code];
        if (text) {
          const canRetry = ![
            "telegram_init_data_invalid",
            "telegram_init_data_expired",
            "scanner_forbidden",
          ].includes(code);
          showMessage("Не удалось проверить QR", text, canRetry);
        } else {
          showMessage(
            "Нет связи с сервером",
            "Нет связи с сервером. Попробуйте ещё раз.",
            true,
          );
        }
        return;
      }
      renderSuccess(data);
    } catch (_error) {
      showMessage(
        "Нет связи с сервером",
        "Нет связи с сервером. Попробуйте ещё раз.",
        true,
      );
    } finally {
      setBusy(false);
    }
  }

  function scannerSupported() {
    return Boolean(
      telegram &&
        typeof telegram.showScanQrPopup === "function" &&
        typeof telegram.closeScanQrPopup === "function" &&
        typeof telegram.isVersionAtLeast === "function" &&
        telegram.isVersionAtLeast("6.4"),
    );
  }

  function startScan() {
    if (requestInFlight) {
      return;
    }
    if (!scannerSupported()) {
      showMessage(
        "Сканирование недоступно",
        "Сканирование QR недоступно в этой версии Telegram. Обновите приложение.",
        false,
      );
      return;
    }

    scanResultHandled = false;
    try {
      telegram.showScanQrPopup(
        { text: "Наведите камеру на QR спортсмена" },
        (qrText) => {
          if (!qrText || scanResultHandled || requestInFlight) {
            return false;
          }
          scanResultHandled = true;
          telegram.closeScanQrPopup();
          void resolveQr(qrText);
          return true;
        },
      );
    } catch (_error) {
      showMessage(
        "Сканирование недоступно",
        "Сканирование QR недоступно в этой версии Telegram. Обновите приложение.",
        false,
      );
    }
  }

  scanButton.addEventListener("click", startScan);
  closeButton.addEventListener("click", () => {
    if (telegram && typeof telegram.close === "function") {
      telegram.close();
    } else {
      window.close();
    }
  });

  const previewParameters = new URLSearchParams(window.location.search);
  const previewState = previewParameters.get("preview");
  const previewTheme = previewParameters.get("theme");
  const isLocalPreview =
    ["localhost", "127.0.0.1"].includes(window.location.hostname) &&
    ["idle", "loading", "success", "error"].includes(previewState);
  if (isLocalPreview) {
    if (["light", "dark"].includes(previewTheme)) {
      document.documentElement.classList.add(`preview-${previewTheme}`);
    }
    if (previewState === "loading") {
      setBusy(true);
      showPanel("loading");
    } else if (previewState === "success") {
      renderSuccess({
        full_name: "Иван Иванов",
        birth_date: "1991-12-27",
      });
    } else if (previewState === "error") {
      showMessage(
        "Не удалось проверить QR",
        errorMessages.athlete_qr_expired,
        true,
      );
    } else {
      showPanel("idle");
    }
    return;
  }

  if (telegram) {
    telegram.ready();
    telegram.expand();
  }

  if (!telegram || !telegram.initData) {
    showMessage(
      "Откройте в Telegram",
      "Откройте сканер из меню бота в Telegram.",
      false,
    );
    return;
  }

  if (!scannerSupported()) {
    showMessage(
      "Сканирование недоступно",
      "Сканирование QR недоступно в этой версии Telegram. Обновите приложение.",
      false,
    );
  }
})();
