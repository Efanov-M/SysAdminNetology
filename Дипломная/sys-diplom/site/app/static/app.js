function formatObservationLabel(timestamp) {
  return new Date(timestamp).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getCookie(name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = document.cookie.match(new RegExp(`(?:^|; )${escaped}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

function getCsrfToken() {
  const metaToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
  return metaToken || getCookie("csrf_token");
}

function appendCsrfField(form) {
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  const token = getCsrfToken();
  if (!token) {
    return;
  }
  let field = form.querySelector('input[name="csrf_token"]');
  if (!(field instanceof HTMLInputElement)) {
    field = document.createElement("input");
    field.type = "hidden";
    field.name = "csrf_token";
    form.appendChild(field);
  }
  field.value = token;
}

function registerCopyButtons(root) {
  const scope = root instanceof Element ? root : document;
  const buttons = scope.matches?.(".js-copy-trigger")
    ? [scope]
    : Array.from(scope.querySelectorAll(".js-copy-trigger"));

  buttons.forEach((button) => {
    if (!(button instanceof HTMLButtonElement) || button.dataset.copyBound === "true") {
      return;
    }
    button.dataset.copyBound = "true";
    button.addEventListener("click", async () => {
      const text = button.dataset.copyText || "";
      if (!text) {
        return;
      }
      const originalText = button.textContent || "Скопировать";
      try {
        await navigator.clipboard.writeText(text);
        button.textContent = "Скопировано";
      } catch (error) {
        button.textContent = "Не удалось скопировать";
      }
      window.setTimeout(() => {
        button.textContent = originalText;
      }, 1600);
    });
  });
}

function formatLiveClockValue(locale = "ru-RU") {
  return new Date().toLocaleString(locale, {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function initLiveClocks(root) {
  const scope = root instanceof Element ? root : document;
  const clocks = scope.matches?.("[data-live-clock='true']")
    ? [scope]
    : Array.from(scope.querySelectorAll("[data-live-clock='true']"));

  clocks.forEach((clock) => {
    if (!(clock instanceof HTMLElement)) {
      return;
    }

    const locale = clock.dataset.liveClockLocale || "ru-RU";
    const render = () => {
      clock.textContent = formatLiveClockValue(locale);
    };

    render();

    if (clock.dataset.liveClockBound === "true") {
      return;
    }

    clock.dataset.liveClockBound = "true";
    const timerId = window.setInterval(render, 1000 * 30);
    clock.dataset.liveClockTimerId = String(timerId);
  });
}

const OFFLINE_DB_NAME = "family-phr-offline";
const OFFLINE_DB_VERSION = 1;
const OFFLINE_STORE_NAME = "offline_queue";
let syncInProgress = false;

function generateClientId() {
  if (window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function openOfflineDb() {
  return new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) {
      reject(new Error("IndexedDB unavailable"));
      return;
    }
    const request = window.indexedDB.open(OFFLINE_DB_NAME, OFFLINE_DB_VERSION);
    request.onerror = () => reject(request.error || new Error("IndexedDB open failed"));
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(OFFLINE_STORE_NAME)) {
        const store = db.createObjectStore(OFFLINE_STORE_NAME, { keyPath: "id" });
        store.createIndex("synced", "synced", { unique: false });
        store.createIndex("created_at", "created_at", { unique: false });
      }
    };
    request.onsuccess = () => resolve(request.result);
  });
}

async function withOfflineStore(mode, callback) {
  const db = await openOfflineDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(OFFLINE_STORE_NAME, mode);
    const store = transaction.objectStore(OFFLINE_STORE_NAME);
    let result;
    transaction.oncomplete = () => {
      db.close();
      resolve(result);
    };
    transaction.onerror = () => {
      db.close();
      reject(transaction.error || new Error("IndexedDB transaction failed"));
    };
    try {
      result = callback(store, transaction);
    } catch (error) {
      db.close();
      reject(error);
    }
  });
}

function requestToPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("IndexedDB request failed"));
  });
}

async function addOfflineQueueItem(item) {
  await withOfflineStore("readwrite", (store) => {
    store.put(item);
  });
}

async function listOfflineQueueItems() {
  return withOfflineStore("readonly", async (store) => {
    const items = await requestToPromise(store.getAll());
    return items.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  });
}

async function deleteOfflineQueueItem(id) {
  await withOfflineStore("readwrite", (store) => {
    store.delete(id);
  });
}

function getSyncBannerElements() {
  return {
    banner: document.getElementById("sync-status-banner"),
    text: document.getElementById("sync-status-text"),
    count: document.getElementById("sync-status-count"),
  };
}

async function updateSyncBanner(messageOverride) {
  const { banner, text, count } = getSyncBannerElements();
  if (!(banner instanceof HTMLElement) || !(text instanceof HTMLElement) || !(count instanceof HTMLElement)) {
    return;
  }
  const pendingItems = await listOfflineQueueItems().catch(() => []);
  const pendingCount = pendingItems.filter((item) => item.synced === false).length;
  banner.classList.remove("hidden");

  if (!window.navigator.onLine) {
    text.textContent = "Нет интернета";
  } else if (messageOverride) {
    text.textContent = messageOverride;
  } else if (pendingCount > 0) {
    text.textContent = "Ожидает отправки";
  } else {
    text.textContent = "Синхронизировано";
  }

  if (pendingCount > 0) {
    count.textContent = `${pendingCount}`;
    count.classList.remove("hidden");
  } else {
    count.textContent = "";
    count.classList.add("hidden");
  }
}

function setOfflineFormStatus(form, message, tone = "slate") {
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  const status = form.querySelector(".js-live-status");
  if (!(status instanceof HTMLElement)) {
    return;
  }
  status.textContent = message;
  const baseClass = status.dataset.baseClass || status.className;
  status.dataset.baseClass = baseClass;
  const colorClass =
    tone === "emerald" ? "text-emerald-600" :
    tone === "amber" ? "text-amber-600" :
    tone === "rose" ? "text-rose-600" :
    "text-slate-500";
  status.className = `${baseClass} ${colorClass}`;
}

function buildOfflinePayload(form) {
  const formData = new FormData(form);
  let clientId = `${formData.get("client_id") || ""}`.trim();
  if (!clientId) {
    clientId = generateClientId();
    formData.set("client_id", clientId);
  }
  const fields = {};
  formData.forEach((value, key) => {
    if (fields[key] !== undefined) {
      if (Array.isArray(fields[key])) {
        fields[key].push(value);
      } else {
        fields[key] = [fields[key], value];
      }
      return;
    }
    fields[key] = value;
  });
  return {
    id: clientId,
    type: form.dataset.offlineForm || "event",
    payload: {
      endpoint: form.getAttribute("action") || window.location.pathname,
      method: (form.getAttribute("method") || "post").toUpperCase(),
      fields,
    },
    created_at: new Date().toISOString(),
    synced: false,
  };
}

async function queueOfflineForm(form, message = "Сохранено локально, будет отправлено позже") {
  const queueItem = buildOfflinePayload(form);
  await addOfflineQueueItem(queueItem);
  if ("serviceWorker" in navigator && "SyncManager" in window) {
    navigator.serviceWorker.ready
      .then((registration) => registration.sync.register("offline-sync"))
      .catch(() => {});
  }
  setLiveFormState(form, "success-lock");
  setOfflineFormStatus(form, message, "amber");
  await updateSyncBanner("Ожидает отправки");
  return queueItem;
}

async function syncOfflineQueue() {
  if (syncInProgress || !window.navigator.onLine) {
    return;
  }
  syncInProgress = true;
  try {
    const items = await listOfflineQueueItems();
    for (const item of items) {
      if (item.synced !== false) {
        continue;
      }
      const formData = new FormData();
      Object.entries(item.payload.fields || {}).forEach(([key, rawValue]) => {
        if (Array.isArray(rawValue)) {
          rawValue.forEach((value) => formData.append(key, value));
        } else {
          formData.append(key, rawValue);
        }
      });
      const response = await fetch(item.payload.endpoint, {
        method: item.payload.method || "POST",
        body: formData,
        headers: {
          "X-Requested-With": "offline-sync",
          "X-CSRF-Token": getCsrfToken(),
        },
        credentials: "same-origin",
      });
      if (!response.ok) {
        throw new Error(`Sync failed with status ${response.status}`);
      }
      await deleteOfflineQueueItem(item.id);
    }
    await updateSyncBanner("Синхронизировано");
  } catch (error) {
    await updateSyncBanner("Ожидает отправки");
  } finally {
    syncInProgress = false;
  }
}

function registerOfflineForms(root) {
  const scope = root instanceof Element ? root : document;
  const forms = scope.matches?.("form[data-offline-form]")
    ? [scope]
    : Array.from(scope.querySelectorAll("form[data-offline-form]"));

  forms.forEach((form) => {
    if (!(form instanceof HTMLFormElement) || form.dataset.offlineBound === "true") {
      return;
    }
    form.dataset.offlineBound = "true";
    appendCsrfField(form);

    form.addEventListener("submit", async (event) => {
      if (window.navigator.onLine) {
        form.dataset.pendingOfflineSnapshot = JSON.stringify(buildOfflinePayload(form));
        return;
      }
      event.preventDefault();
      await queueOfflineForm(form);
    });
  });
}

function registerOfflineEventHandlers() {
  document.body.addEventListener("htmx:sendError", async (event) => {
    const form = event.target instanceof HTMLFormElement ? event.target : event.target?.closest?.("form[data-offline-form]");
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    const snapshotRaw = form.dataset.pendingOfflineSnapshot;
    if (!snapshotRaw) {
      return;
    }
    try {
      const snapshot = JSON.parse(snapshotRaw);
      await addOfflineQueueItem(snapshot);
      setLiveFormState(form, "success-lock");
      setOfflineFormStatus(form, "Сохранено локально, будет отправлено позже", "amber");
      await updateSyncBanner("Ожидает отправки");
    } catch (error) {
      setLiveFormState(form, "error");
      setOfflineFormStatus(form, "Не удалось сохранить локально", "rose");
    }
  });

  window.addEventListener("online", async () => {
    await updateSyncBanner("Синхронизируем...");
    await syncOfflineQueue();
  });

  window.addEventListener("offline", async () => {
    await updateSyncBanner("Нет интернета");
  });
}

document.addEventListener("DOMContentLoaded", () => {
  registerCopyButtons(document);
  document.body.addEventListener("htmx:configRequest", (event) => {
    const token = getCsrfToken();
    if (token) {
      event.detail.headers["X-CSRF-Token"] = token;
    }
  });
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  registerCopyButtons(event.target);
});

function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) {
    return;
  }
  navigator.serviceWorker.register("/sw.js").catch(() => {});
  navigator.serviceWorker.addEventListener("message", (event) => {
    if (event.data?.type === "offline-sync-requested") {
      syncOfflineQueue();
    }
  });
}

if (window.Chart && window.ChartZoom) {
  Chart.register(window.ChartZoom);
}

function setLiveFormState(form, state) {
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  const submit = form.querySelector(".js-live-submit");
  if (!(submit instanceof HTMLButtonElement)) {
    return;
  }
  const idle = submit.querySelector(".js-live-idle");
  const loading = submit.querySelector(".js-live-loading");
  const success = submit.querySelector(".js-live-success");
  const error = submit.querySelector(".js-live-error");
  const status = form.querySelector(".js-live-status");
  if (status instanceof HTMLElement && !status.dataset.baseClass) {
    status.dataset.baseClass = status.className;
  }

  [idle, loading, success, error].forEach((node) => {
    if (!(node instanceof HTMLElement)) {
      return;
    }
    node.classList.add("hidden");
    node.classList.remove("inline-flex");
  });

  submit.disabled = state === "loading" || state === "success-lock";
  form.dataset.liveState = state;

  if (state === "loading") {
    if (loading instanceof HTMLElement) {
      loading.classList.remove("hidden");
      loading.classList.add("inline-flex");
    }
    if (status instanceof HTMLElement) {
      status.textContent = "Запрос выполняется";
      status.className = `${status.dataset.baseClass || "js-live-status"} text-slate-500`;
    }
    return;
  }

  if (state === "success-lock") {
    if (success instanceof HTMLElement) {
      success.classList.remove("hidden");
      success.classList.add("inline-flex");
    }
    if (status instanceof HTMLElement) {
      status.textContent = "Сохранено";
      status.className = `${status.dataset.baseClass || "js-live-status"} text-emerald-600`;
    }
    return;
  }

  if (state === "error") {
    if (error instanceof HTMLElement) {
      error.classList.remove("hidden");
      error.classList.add("inline-flex");
    }
    if (status instanceof HTMLElement) {
      status.textContent = "Исправьте поля и повторите";
      status.className = `${status.dataset.baseClass || "js-live-status"} text-rose-600`;
    }
    return;
  }

  if (idle instanceof HTMLElement) {
    idle.classList.remove("hidden");
  }
  if (status instanceof HTMLElement) {
    status.textContent = "";
    status.className = `${status.dataset.baseClass || "js-live-status"} text-slate-500`;
  }
}

function initLiveForms(root) {
  const scope = root instanceof Element ? root : document;
  const forms = scope.matches?.("form[data-live-form='true']")
    ? [scope]
    : Array.from(scope.querySelectorAll("form[data-live-form='true']"));

  forms.forEach((form) => {
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    setLiveFormState(form, "idle");
    if (form.dataset.successState === "true") {
      setLiveFormState(form, "success-lock");
      window.setTimeout(() => {
        if (document.body.contains(form)) {
          setLiveFormState(form, "idle");
        }
      }, 1200);
    } else if (form.dataset.errorState === "true") {
      setLiveFormState(form, "error");
    }
  });
}

function getChartContainer(canvas) {
  return canvas.closest("#chart-block") || canvas.parentElement || document;
}

function getSelectedChartToggles(canvas) {
  const container = getChartContainer(canvas);
  const toggles = Array.from(container.querySelectorAll("[data-chart-toggle]"));
  const values = new Set(
    toggles
      .filter((toggle) => toggle.checked)
      .map((toggle) => toggle.dataset.chartToggle)
  );
  return values;
}

function getChartConfig(chartType, items, labTestName, selectedToggles = new Set()) {
  const filtered = items
    .filter((item) => item.type === chartType)
    .filter((item) => chartType !== "lab_result" || !labTestName || item.value.test_name === labTestName)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));

  const labels = filtered.map((item) => formatObservationLabel(item.created_at));

  if (chartType === "blood_pressure") {
    const sysDataset = {
      label: "Систолическое",
      data: filtered.map((item) => item.value.sys),
      borderColor: "#0f766e",
      backgroundColor: "rgba(15, 118, 110, 0.16)",
      tension: 0.25,
      fill: false,
      pointRadius: 4,
      pointHoverRadius: 6,
      pointBackgroundColor: "#0f766e",
      borderWidth: 3,
      hidden: selectedToggles.size > 0 && !selectedToggles.has("sys"),
    };
    const diaDataset = {
      label: "Диастолическое",
      data: filtered.map((item) => item.value.dia),
      borderColor: "#b45309",
      backgroundColor: "rgba(180, 83, 9, 0.12)",
      tension: 0.25,
      fill: false,
      pointRadius: 4,
      pointHoverRadius: 6,
      pointBackgroundColor: "#b45309",
      borderWidth: 3,
      hidden: selectedToggles.size > 0 && !selectedToggles.has("dia"),
    };
    const pulseDataset = {
      label: "Пульс",
      data: filtered.map((item) => item.value.pulse ?? null),
      borderColor: "#0284c7",
      backgroundColor: "rgba(2, 132, 199, 0.12)",
      tension: 0.25,
      fill: false,
      pointRadius: 4,
      pointHoverRadius: 6,
      pointBackgroundColor: "#0284c7",
      borderWidth: 3,
      yAxisID: "y1",
      hidden: selectedToggles.size > 0 && !selectedToggles.has("pulse"),
    };
    return {
      labels,
      datasets: [
        {
          label: "Нижняя граница нормы",
          data: filtered.map(() => 70),
          borderColor: "rgba(16, 185, 129, 0)",
          backgroundColor: "rgba(16, 185, 129, 0.08)",
          pointRadius: 0,
          pointHoverRadius: 0,
          borderWidth: 0,
          fill: false,
        },
        {
          label: "Верхняя граница нормы",
          data: filtered.map(() => 120),
          borderColor: "rgba(16, 185, 129, 0)",
          backgroundColor: "rgba(16, 185, 129, 0.14)",
          pointRadius: 0,
          pointHoverRadius: 0,
          borderWidth: 0,
          fill: "-1",
          order: 0,
        },
        sysDataset,
        diaDataset,
        pulseDataset,
      ],
    };
  }

  if (chartType === "lab_result") {
    const effectiveLabTestName = labTestName || filtered[0]?.value?.test_name || "";
    const labItems = filtered.filter((item) => !effectiveLabTestName || item.value.test_name === effectiveLabTestName);
    const referenceLow = labItems.find((item) => item.value.reference_low !== null && item.value.reference_low !== undefined)?.value?.reference_low;
    const referenceHigh = labItems.find((item) => item.value.reference_high !== null && item.value.reference_high !== undefined)?.value?.reference_high;
    const datasets = [
      {
        label: effectiveLabTestName || "Анализ",
        data: labItems.map((item) => item.value.value),
        borderColor: "#0f766e",
        backgroundColor: "transparent",
        tension: 0.25,
        fill: false,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBackgroundColor: "#0f766e",
        borderWidth: 3,
      },
    ];
    if (referenceLow !== undefined && referenceHigh !== undefined) {
      datasets.unshift(
        {
          label: "Нижняя граница",
          data: labItems.map(() => referenceLow),
          borderColor: "rgba(16, 185, 129, 0)",
          backgroundColor: "rgba(16, 185, 129, 0.08)",
          pointRadius: 0,
          pointHoverRadius: 0,
          borderWidth: 0,
          fill: false,
        },
        {
          label: "Верхняя граница",
          data: labItems.map(() => referenceHigh),
          borderColor: "rgba(16, 185, 129, 0)",
          backgroundColor: "rgba(16, 185, 129, 0.14)",
          pointRadius: 0,
          pointHoverRadius: 0,
          borderWidth: 0,
          fill: "-1",
          order: 0,
        },
      );
    }
    return {
      labels: labItems.map((item) => formatObservationLabel(item.created_at)),
      datasets,
    };
  }

  const titleMap = {
    blood_sugar: "Сахар",
    temperature: "Температура",
    weight: "Вес",
  };

  return {
    labels,
    datasets: [
      {
        label: titleMap[chartType] || "Показатель",
        data: filtered.map((item) => item.value.value),
        borderColor: "#0f766e",
        backgroundColor: "rgba(15, 118, 110, 0.16)",
        tension: 0.25,
        fill: false,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBackgroundColor: "#0f766e",
        borderWidth: 3,
      },
    ],
  };
}

async function loadObservationChart(canvas) {
  if (!canvas) {
    return;
  }

  const container = canvas.closest("#chart-block");
  const emptyState = container?.querySelector("[data-chart-empty-state='true']");

  const patientId = canvas.dataset.patientId;
  const chartType = canvas.dataset.chartType || "blood_pressure";
  const labTestName = canvas.dataset.chartLabTest || "";
  const dateFrom = canvas.dataset.dateFrom || "";
  const dateTo = canvas.dataset.dateTo || "";
  if (!patientId) {
    return;
  }

  const params = new URLSearchParams();
  if (chartType) {
    params.set("observation_type", chartType);
  }
  if (dateFrom) {
    params.set("date_from", `${dateFrom}T00:00:00`);
  }
  if (dateTo) {
    params.set("date_to", `${dateTo}T23:59:59`);
  }
  const response = await fetch(`/api/patients/${patientId}/history?${params.toString()}`);
  if (!response.ok) {
    if (emptyState) {
      emptyState.classList.remove("hidden");
      emptyState.style.display = "grid";
    }
    canvas.classList.add("hidden");
    return;
  }

  const items = await response.json();
  const chartData = getChartConfig(chartType, items, labTestName, getSelectedChartToggles(canvas));
  const hasDataset = chartData.labels.length > 0 && chartData.datasets.some((dataset) => Array.isArray(dataset.data) && dataset.data.length > 0);

  if (!hasDataset) {
    if (window.observationChartInstance) {
      window.observationChartInstance.destroy();
      window.observationChartInstance = null;
    }
    if (emptyState) {
      emptyState.classList.remove("hidden");
      emptyState.style.display = "grid";
    }
    canvas.classList.add("hidden");
    return;
  }

  if (emptyState) {
    emptyState.classList.add("hidden");
    emptyState.style.display = "none";
  }
  canvas.classList.remove("hidden");

  if (window.observationChartInstance) {
    window.observationChartInstance.destroy();
  }

  window.observationChartInstance = new Chart(canvas, {
    type: "line",
    data: {
      labels: chartData.labels,
      datasets: chartData.datasets,
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "top",
          labels: {
            usePointStyle: true,
            boxWidth: 10,
            color: "#334155",
            padding: 18,
            font: {
              size: 13,
              weight: "600",
            },
            filter(legendItem) {
              return !["Нижняя граница нормы", "Верхняя граница нормы", "Нижняя граница", "Верхняя граница"].includes(legendItem.text);
            },
          },
        },
        tooltip: {
          backgroundColor: "#134e4a",
          titleColor: "#f8fafc",
          bodyColor: "#e2e8f0",
          padding: 12,
          cornerRadius: 14,
          callbacks: {
            label(context) {
              const value = context.parsed.y;
              const suffix = context.dataset.label === "Пульс" ? " уд/мин" : "";
              return `${context.dataset.label}: ${value}${suffix}`;
            },
          },
        },
        zoom: {
          pan: {
            enabled: true,
            mode: "x",
          },
          zoom: {
            wheel: {
              enabled: true,
            },
            pinch: {
              enabled: true,
            },
            mode: "x",
          },
        },
      },
      scales: {
        x: {
          grid: {
            display: false,
          },
          ticks: {
            maxRotation: 0,
            autoSkip: true,
            color: "#64748b",
            font: {
              size: 12,
            },
          },
        },
        y: {
          grid: {
            color: "rgba(20, 78, 74, 0.12)",
          },
          ticks: {
            color: "#475569",
            font: {
              size: 12,
            },
          },
        },
        y1: {
          position: "right",
          grid: {
            drawOnChartArea: false,
          },
          ticks: {
            color: "#0369a1",
            font: {
              size: 12,
            },
          },
        },
      },
    },
  });
}

function initObservationCharts(root) {
  const scope = root instanceof Element ? root : document;
  const canvases = scope.matches?.("canvas[data-observation-chart='true']")
    ? [scope]
    : Array.from(scope.querySelectorAll("canvas[data-observation-chart='true']"));

  canvases.forEach((canvas) => {
    loadObservationChart(canvas).catch(() => {});
  });
}

function initChildCharts(root) {
  const scope = root instanceof Element ? root : document;
  const canvases = scope.matches?.("canvas[data-child-chart='growth']")
    ? [scope]
    : Array.from(scope.querySelectorAll("canvas[data-child-chart='growth']"));

  canvases.forEach((canvas) => {
    if (!(canvas instanceof HTMLCanvasElement) || !window.Chart) {
      return;
    }
    const raw = canvas.dataset.growthRecords || "[]";
    let items = [];
    try {
      items = JSON.parse(raw);
    } catch (_) {
      items = [];
    }
    if (!items.length) {
      return;
    }
    if (canvas._chartInstance) {
      canvas._chartInstance.destroy();
    }
    canvas._chartInstance = new Chart(canvas, {
      type: "line",
      data: {
        labels: items.map((item) => new Date(item.date).toLocaleDateString("ru-RU")),
        datasets: [
          {
            label: "Рост, см",
            data: items.map((item) => item.height),
            borderColor: "#0284c7",
            backgroundColor: "rgba(2,132,199,0.12)",
            tension: 0.25,
            spanGaps: true,
          },
          {
            label: "Вес, кг",
            data: items.map((item) => item.weight),
            borderColor: "#16a34a",
            backgroundColor: "rgba(22,163,74,0.12)",
            tension: 0.25,
            spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: "bottom",
          },
        },
      },
    });
  });
}

function initDrugAutocomplete(root) {
  const scope = root instanceof Element ? root : document;
  const inputs = scope.matches?.("[data-drug-suggest-url]")
    ? [scope]
    : Array.from(scope.querySelectorAll("[data-drug-suggest-url]"));

  inputs.forEach((input) => {
    if (!(input instanceof HTMLInputElement) || input.dataset.autocompleteReady === "true") {
      return;
    }
    input.dataset.autocompleteReady = "true";
    const datalistId = input.getAttribute("list");
    const datalist = datalistId ? document.getElementById(datalistId) : null;
    const suggestUrl = input.dataset.drugSuggestUrl;
    const autofillUrl = input.dataset.drugAutofillUrl;
    const instructionsTarget = input.dataset.drugInstructionsTarget
      ? document.querySelector(input.dataset.drugInstructionsTarget)
      : null;
    const notesTarget = input.dataset.drugNotesTarget
      ? document.querySelector(input.dataset.drugNotesTarget)
      : null;
    let timerId = 0;

    const loadSuggestions = async () => {
      if (!(datalist instanceof HTMLDataListElement) || !suggestUrl) {
        return;
      }
      const query = input.value.trim();
      if (query.length < 1) {
        datalist.innerHTML = "";
        return;
      }
      try {
        const response = await fetch(`${suggestUrl}?q=${encodeURIComponent(query)}`, {
          headers: { "X-Requested-With": "fetch" },
        });
        if (!response.ok) {
          return;
        }
        const payload = await response.json();
        datalist.replaceChildren();
        (payload.items || []).forEach((item) => {
          if (!item?.name) {
            return;
          }
          const option = document.createElement("option");
          option.value = item.name;
          datalist.appendChild(option);
        });
      } catch (_) {
        datalist.replaceChildren();
      }
    };

    const applyAutofill = async () => {
      if (!autofillUrl) {
        return;
      }
      const query = input.value.trim();
      if (!query) {
        return;
      }
      try {
        const response = await fetch(`${autofillUrl}?q=${encodeURIComponent(query)}`, {
          headers: { "X-Requested-With": "fetch" },
        });
        if (!response.ok) {
          return;
        }
        const payload = await response.json();
        const item = payload.item;
        if (!item) {
          return;
        }
        if (instructionsTarget instanceof HTMLTextAreaElement && !instructionsTarget.value.trim() && item.instructions) {
          instructionsTarget.value = item.instructions;
        }
        if (notesTarget instanceof HTMLTextAreaElement && !notesTarget.value.trim() && item.description) {
          notesTarget.value = item.description;
        }
        if (item.name) {
          input.value = item.name;
        }
      } catch (_) {
        // ignore network errors and keep manual input
      }
    };

    input.addEventListener("input", () => {
      window.clearTimeout(timerId);
      timerId = window.setTimeout(loadSuggestions, 180);
    });

    input.addEventListener("change", () => {
      applyAutofill().catch(() => {});
    });

    input.addEventListener("blur", () => {
      applyAutofill().catch(() => {});
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initLiveClocks(document);
  initObservationCharts(document);
  initChildCharts(document);
  initLiveForms(document);
  initDrugAutocomplete(document);
  registerOfflineForms(document);
  registerOfflineEventHandlers();
  registerServiceWorker();
  updateSyncBanner().catch(() => {});
  syncOfflineQueue().catch(() => {});
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.target instanceof Element) {
    event.target.classList.remove("live-flash");
    requestAnimationFrame(() => event.target.classList.add("live-flash"));
  }
  initLiveClocks(event.target);
  initObservationCharts(event.target);
  initChildCharts(event.target);
  initLiveForms(event.target);
  initDrugAutocomplete(event.target);
  registerOfflineForms(event.target);
  updateSyncBanner().catch(() => {});
});

document.body.addEventListener("change", (event) => {
  if (!(event.target instanceof HTMLInputElement)) {
    return;
  }
  if (!event.target.matches("[data-chart-toggle]")) {
    return;
  }
  const canvas = event.target.closest("#chart-block")?.querySelector("canvas[data-observation-chart='true']");
  if (canvas) {
    loadObservationChart(canvas).catch(() => {});
  }
});

document.body.addEventListener("submit", (event) => {
  const form = event.target;
  if (form instanceof HTMLFormElement) {
    appendCsrfField(form);
  }
});

document.body.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.dataset.liveForm !== "true") {
    return;
  }
  const now = Date.now();
  const lastSubmittedAt = Number(form.dataset.lastSubmittedAt || "0");
  if (form.dataset.liveState === "loading" || now - lastSubmittedAt < 700) {
    event.preventDefault();
    return;
  }
  form.dataset.lastSubmittedAt = String(now);
  setLiveFormState(form, "loading");
});

document.body.addEventListener("htmx:responseError", (event) => {
  const elt = event.detail?.elt;
  const form = elt instanceof HTMLFormElement ? elt : elt?.closest?.("form[data-live-form='true']");
  if (form instanceof HTMLFormElement) {
    setLiveFormState(form, "error");
  }
});

document.body.addEventListener("htmx:sendError", (event) => {
  const elt = event.detail?.elt;
  const form = elt instanceof HTMLFormElement ? elt : elt?.closest?.("form[data-live-form='true']");
  if (form instanceof HTMLFormElement) {
    setLiveFormState(form, "error");
  }
});

document.body.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.dataset.inviteForm !== "true") {
    return;
  }
  event.preventDefault();

  const fallbackNotice = document.getElementById("invite-form-fallback");
  const formData = new FormData(form);

  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: formData,
      headers: { "X-CSRF-Token": getCsrfToken() },
      credentials: "same-origin",
      redirect: "manual",
    });

    if (response.status >= 300 && response.status < 400) {
      const target = response.headers.get("Location") || "/family/users?message=Приглашение+отправлено&error=0";
      window.location.assign(target);
      return;
    }

    if (!response.ok) {
      throw new Error(`Invite failed with status ${response.status}`);
    }

    window.location.assign("/family/users?message=Приглашение+отправлено&error=0");
  } catch (error) {
    if (fallbackNotice instanceof HTMLElement) {
      fallbackNotice.classList.remove("hidden");
    }
    window.setTimeout(() => {
      window.location.assign("/family/users?message=Не+удалось+обработать+ответ+после+приглашения&error=1");
    }, 250);
  }
});
