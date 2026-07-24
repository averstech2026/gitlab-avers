/* MFC fast create — Avers UX */

const state = {
  catalogs: null,
  rows: [],
  isTasks: [],
  objectsCache: [],
  companiesCache: [],
  employeesCache: [],
  appliedFingerprint: null,
  submitting: false,
  health: null,
  companyId: null,
  assigneeId: null,
  companyName: "",
  assigneeName: "",
};

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data.detail || data.error || res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "className") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k === "value") node.value = v;
    else if (typeof v === "boolean") {
      if (v) node.setAttribute(k, "");
      else node.removeAttribute(k);
    } else if (typeof v === "function") {
      node.addEventListener(k.replace(/^on/, "").toLowerCase(), v);
    } else if (v !== null && v !== undefined) {
      node.setAttribute(k, v);
    }
  }
  for (const c of children) {
    if (c != null) node.append(c);
  }
  return node;
}

function toast(message, type = "") {
  const node = document.getElementById("toast");
  node.hidden = false;
  node.className = "toast" + (type ? ` is-${type}` : "");
  node.textContent = message;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    node.hidden = true;
  }, 4200);
}

function fingerprint(text) {
  const s = (text || "").trim().replace(/\r\n/g, "\n");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return `${s.length}:${h}`;
}

function setStatusBadge(el, status, label, detail) {
  el.className = `cloud-status-badge cloud-status-badge--${status}`;
  el.title = detail || label;
  const dot = el.querySelector(".status-dot");
  if (dot) {
    dot.classList.toggle("pulsing", status === "checking" || status === "connected");
  }
  const text = el.querySelector(".status-text");
  if (text) text.textContent = label;
}

function setStep1Collapsed(collapsed) {
  const section = document.getElementById("step-input");
  const btn = document.getElementById("btn-toggle-step1");
  const summary = document.getElementById("step1-summary");
  const action = document.getElementById("step1-toggle-label");
  section.classList.toggle("is-collapsed", collapsed);
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (action) action.textContent = collapsed ? "Развернуть" : "Свернуть";
  if (collapsed && state.rows.length) {
    summary.hidden = false;
    summary.textContent = `разобрано: ${state.rows.length}`;
  } else if (!collapsed) {
    summary.hidden = true;
  }
}

function setActiveNav(step) {
  document.getElementById("nav-step-1").classList.toggle("is-active", step === 1);
  document.getElementById("nav-step-2").classList.toggle("is-active", step === 2);
}

function statusLabelRu(status) {
  if (status === "connected") return "Подключено";
  if (status === "error") return "Ошибка";
  if (status === "checking") return "Проверка…";
  return "Не настроено";
}

function openStatusModal(kind) {
  const modal = document.getElementById("status-modal");
  const title = document.getElementById("status-modal-title");
  const body = document.getElementById("status-modal-body");
  const h = state.health || {};
  const data = kind === "okdesk" ? h.okdesk || {} : h.intraservice || {};
  const status = data.status || "offline";

  if (kind === "okdesk") {
    title.textContent = "Интеграция Okdesk";
    body.innerHTML = `
      <div class="modal__status-line">
        <span class="status-dot" style="background:${status === "connected" ? "#10b981" : status === "error" ? "#f59e0b" : "#94a3b8"}"></span>
        ${statusLabelRu(status)}
      </div>
      <p>Okdesk — куда создаются и закрываются заявки. Сейчас: <strong>${escapeHtml(state.companyName || "—")}</strong> → <strong>${escapeHtml(state.assigneeName || "—")}</strong> (id ${state.companyId ?? "—"} / ${state.assigneeId ?? "—"}).</p>
      <p>Токен берётся из серверного <code>.env</code> (<code>OKDESK_DOMAIN</code>, <code>OKDESK_API_TOKEN</code>) и в браузер не попадает.</p>
      <dl class="modal__dl">
        <dt>Статус</dt><dd>${statusLabelRu(status)}</dd>
        <dt>Детали</dt><dd>${data.detail || "—"}</dd>
        <dt>Домен</dt><dd>${state.catalogs?.okdesk_domain || data.detail || "—"}</dd>
      </dl>
    `;
  } else {
    title.textContent = "Интеграция IntraService";
    body.innerHTML = `
      <div class="modal__status-line">
        <span class="status-dot" style="background:${status === "connected" ? "#10b981" : status === "error" ? "#f59e0b" : "#94a3b8"}"></span>
        ${statusLabelRu(status)}
      </div>
      <p>IntraService (<code>help.ucg.ru</code>) — внешний Service Desk MFC/UCG. Нужен, чтобы по ссылке подтянуть тему и описание заявки или выбрать тикеты из каталога.</p>
      <p>Учётка только на сервере: <code>INTRASERVICE_USER</code> / <code>INTRASERVICE_PASSWORD</code>.</p>
      <dl class="modal__dl">
        <dt>Статус</dt><dd>${statusLabelRu(status)}</dd>
        <dt>Хост</dt><dd>${data.detail || "help.ucg.ru"}</dd>
        <dt>Проверка</dt><dd>${data.sample != null ? "тестовая заявка #" + data.sample : "—"}</dd>
      </dl>
    `;
  }
  modal.hidden = false;
}

function closeStatusModal() {
  document.getElementById("status-modal").hidden = true;
}

async function refreshHealth() {
  const okBadge = document.getElementById("badge-okdesk");
  const isBadge = document.getElementById("badge-intraservice");
  setStatusBadge(okBadge, "checking", "Okdesk…", "Проверка");
  setStatusBadge(isBadge, "checking", "IntraService…", "Проверка");
  try {
    const h = await api("/api/mfc/health");
    state.health = h;
    const ok = h.okdesk || {};
    const is = h.intraservice || {};
    const okLabel =
      ok.status === "connected"
        ? "Okdesk подключён"
        : ok.status === "error"
          ? "Ошибка Okdesk"
          : "Okdesk не настроен";
    const isLabel =
      is.status === "connected"
        ? "IntraService подключён"
        : is.status === "error"
          ? "Ошибка IntraService"
          : "IntraService не настроен";
    setStatusBadge(okBadge, ok.status || "offline", okLabel, ok.detail || "Нажмите для подробностей");
    setStatusBadge(isBadge, is.status || "offline", isLabel, is.detail || "Нажмите для подробностей");
  } catch (e) {
    state.health = {
      okdesk: { status: "error", detail: String(e.message || e) },
      intraservice: { status: "error", detail: String(e.message || e) },
    };
    setStatusBadge(okBadge, "error", "Ошибка Okdesk", String(e.message || e));
    setStatusBadge(isBadge, "error", "Ошибка IntraService", String(e.message || e));
  }
}

function fillSelect(select, options, selected) {
  select.innerHTML = "";
  select.append(el("option", { value: "", text: "— выбрать —" }));
  for (const opt of options) {
    const o = el("option", { value: opt, text: opt });
    o.title = opt;
    if (opt === selected) o.selected = true;
    select.append(o);
  }
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function objectsApiUrl(q = "", limit = 500) {
  const cid = state.companyId || state.catalogs?.company_id || 9;
  const params = new URLSearchParams({
    q: q || "",
    limit: String(limit),
    company_id: String(cid),
  });
  return `/api/mfc/objects?${params}`;
}

function normalizeQuery(q) {
  return String(q || "")
    .trim()
    .toLowerCase()
    .replace(/ё/g, "е");
}

function filterNamedItems(items, q, limit = 40) {
  const nq = normalizeQuery(q);
  const all = items || [];
  if (!nq) return all.slice(0, limit);
  return all
    .filter((x) => {
      const name = normalizeQuery(x.name);
      return name.includes(nq) || String(x.id) === nq;
    })
    .slice(0, limit);
}

/**
 * Searchable combobox for company / assignee.
 */
function mountSearchCombo(root, opts) {
  root.innerHTML = "";
  root.classList.add("combo", "context-combo__inner");

  let selected = opts.selected ? { ...opts.selected } : null;

  const input = el("input", {
    type: "text",
    className: "input input--sm combo__input",
    placeholder: opts.placeholder || "Поиск…",
    autocomplete: "off",
    spellcheck: "false",
  });
  if (selected?.name) input.value = selected.name;

  const clearBtn = el("button", {
    type: "button",
    className: "combo__clear",
    title: "Очистить поиск",
    text: "×",
    hidden: true,
  });

  const chevron = el("span", {
    className: "combo__chevron",
    "aria-hidden": "true",
  });

  const list = el("div", { className: "combo__list", hidden: true });
  document.body.appendChild(list);

  function placeList() {
    const rect = input.getBoundingClientRect();
    list.classList.add("is-fixed");
    list.style.position = "fixed";
    list.style.left = `${rect.left}px`;
    list.style.width = `${Math.max(rect.width, 280)}px`;
    list.style.top = `${rect.bottom + 4}px`;
    list.style.right = "auto";
    const spaceBelow = window.innerHeight - rect.bottom;
    if (spaceBelow < 200 && rect.top > 220) {
      list.style.top = "auto";
      list.style.bottom = `${window.innerHeight - rect.top + 4}px`;
      list.style.maxHeight = "240px";
    } else {
      list.style.bottom = "auto";
      list.style.maxHeight = "280px";
    }
  }

  function closeList() {
    list.hidden = true;
    root.classList.remove("is-open");
  }

  function pick(item) {
    selected = { id: item.id, name: item.name };
    input.value = item.name;
    clearBtn.hidden = true;
    root.classList.remove("is-open");
    closeList();
    opts.onSelect(selected);
  }

  function renderList(items) {
    list.innerHTML = "";
    if (!items.length) {
      list.append(el("div", { className: "combo__empty", text: "Ничего не найдено" }));
      placeList();
      list.hidden = false;
      return;
    }
    for (const item of items) {
      const btn = el("button", {
        type: "button",
        className:
          "combo__option" +
          (selected && String(selected.id) === String(item.id) ? " is-active" : ""),
        text: item.name,
      });
      btn.title = `${item.name} (id ${item.id})`;
      btn.addEventListener("mousedown", (e) => {
        e.preventDefault();
        pick(item);
      });
      list.append(btn);
    }
    placeList();
    list.hidden = false;
  }

  async function openSearch(q) {
    root.classList.add("is-open");
    let items = filterNamedItems(opts.getItems(), q, 80);
    if (opts.searchRemote && (q.trim().length >= 1 || !items.length)) {
      try {
        const remote = await opts.searchRemote(q.trim());
        if (remote?.length) {
          const byId = new Map();
          for (const x of [...items, ...remote]) byId.set(String(x.id), x);
          items = filterNamedItems([...byId.values()], q, 80);
        }
      } catch (_) {}
    }
    if (!items.length && !q.trim() && opts.searchRemote) {
      try {
        items = (await opts.searchRemote("")) || [];
      } catch (_) {}
    }
    renderList(items);
  }

  let timer;
  input.addEventListener("focus", () => {
    if (selected && input.value === selected.name) input.select();
    openSearch(input.value.trim() === selected?.name ? "" : input.value.trim());
  });
  input.addEventListener("input", () => {
    clearBtn.hidden = !input.value;
    clearTimeout(timer);
    timer = setTimeout(() => openSearch(input.value.trim()), 160);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (selected) input.value = selected.name;
      closeList();
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const first = list.querySelector(".combo__option");
      if (first) first.dispatchEvent(new Event("mousedown"));
    }
  });
  input.addEventListener("blur", () => {
    setTimeout(() => {
      closeList();
      if (selected) input.value = selected.name;
    }, 150);
  });
  clearBtn.addEventListener("click", () => {
    input.value = "";
    clearBtn.hidden = true;
    input.focus();
    openSearch("");
  });
  chevron.addEventListener("mousedown", (e) => {
    e.preventDefault();
    input.focus();
  });

  root.append(input, clearBtn, chevron);
}

function isMfcCompany() {
  const mfcId = state.catalogs?.company_id ?? 9;
  return Number(state.companyId) === Number(mfcId);
}

function syncIntraserviceUi() {
  const mfc = isMfcCompany();
  const credsOk = !!state.catalogs?.intraservice_enrich_available;
  const show = mfc && credsOk;

  document.querySelectorAll(".mfc-only").forEach((n) => {
    n.hidden = !mfc;
  });

  const enrich = document.getElementById("enrich");
  if (enrich) {
    if (!show) {
      enrich.checked = false;
      enrich.disabled = true;
    } else {
      enrich.disabled = false;
      if (!enrich.dataset.userTouched) enrich.checked = true;
    }
  }

  const btnIs = document.getElementById("btn-is-optional");
  if (btnIs) {
    btnIs.disabled = !show;
    btnIs.title = !mfc
      ? "Каталог help.ucg.ru доступен только для клиента MFC"
      : !credsOk
        ? "Нужны INTRASERVICE_USER / PASSWORD в .env"
        : "Открыть список заявок с help.ucg.ru";
  }

  if (!mfc) {
    const panel = document.getElementById("is-panel");
    if (panel) panel.hidden = true;
    const details = document.getElementById("is-details");
    if (details) details.open = false;
  }
}

function syncMetaFooter() {
  const meta = document.getElementById("meta");
  if (!meta || !state.catalogs) return;
  meta.innerHTML =
    `${escapeHtml(state.companyName)} · id ${state.companyId}<br>` +
    `${escapeHtml(state.assigneeName)} · id ${state.assigneeId}<br>` +
    `status ${state.catalogs.status_codes.join("→")}`;
}

async function reloadObjectsCache() {
  try {
    const data = await api(objectsApiUrl("", 500));
    state.objectsCache = data.items || [];
  } catch (_) {
    state.objectsCache = [];
  }
}

function clearRowObjectsForCompanyChange() {
  for (const r of state.rows) {
    if (r.status === "ok") continue;
    r.object_id = null;
    r.object_name = null;
    r.object_query = "";
  }
  if (state.rows.length) renderTable();
}

async function initContextBar() {
  const companyRoot = document.getElementById("combo-company");
  const assigneeRoot = document.getElementById("combo-assignee");
  if (!companyRoot || !assigneeRoot || !state.catalogs) return;

  state.companyId = state.catalogs.company_id;
  state.assigneeId = state.catalogs.assignee_id;
  state.companyName = state.catalogs.company_name || `Компания #${state.companyId}`;
  state.assigneeName = state.catalogs.assignee_name || `Сотрудник #${state.assigneeId}`;
  state.companiesCache = [...(state.catalogs.companies || [])];
  state.employeesCache = [...(state.catalogs.employees || [])];
  syncMetaFooter();

  try {
    const [cData, eData] = await Promise.all([
      api("/api/mfc/companies"),
      api("/api/mfc/employees"),
    ]);
    if (cData.items?.length) state.companiesCache = cData.items;
    if (eData.items?.length) state.employeesCache = eData.items;
  } catch (_) {}

  mountSearchCombo(companyRoot, {
    placeholder: "Поиск клиента…",
    getItems: () => state.companiesCache,
    searchRemote: async (q) => {
      const data = await api(`/api/mfc/companies?q=${encodeURIComponent(q)}`);
      if (data.items?.length) {
        const byId = new Map(state.companiesCache.map((x) => [String(x.id), x]));
        for (const x of data.items) byId.set(String(x.id), x);
        state.companiesCache = [...byId.values()];
      }
      return data.items || [];
    },
    selected: { id: state.companyId, name: state.companyName },
    onSelect: async (item) => {
      const changed = String(item.id) !== String(state.companyId);
      state.companyId = item.id;
      state.companyName = item.name;
      syncMetaFooter();
      syncIntraserviceUi();
      if (changed) {
        clearRowObjectsForCompanyChange();
        toast("Клиент сменён — выберите объекты заново.", "");
        await reloadObjectsCache();
      }
    },
  });

  mountSearchCombo(assigneeRoot, {
    placeholder: "Поиск инженера…",
    getItems: () => state.employeesCache,
    searchRemote: async (q) => {
      const data = await api(`/api/mfc/employees?q=${encodeURIComponent(q)}`);
      if (data.items?.length) {
        const byId = new Map(state.employeesCache.map((x) => [String(x.id), x]));
        for (const x of data.items) byId.set(String(x.id), x);
        state.employeesCache = [...byId.values()];
      }
      return data.items || [];
    },
    selected: { id: state.assigneeId, name: state.assigneeName },
    onSelect: (item) => {
      state.assigneeId = item.id;
      state.assigneeName = item.name;
      syncMetaFooter();
    },
  });
}

function complicationOk(r) {
  const level = (r.complication_level || "").trim();
  const text = (r.complication || "").trim();
  if (!level && !text) return true;
  return !!(level && text);
}

function rowErrors(r) {
  if (!r.selected) return [];
  if (r.status === "ok") return [];
  const errs = [];
  if (!r.object_id) errs.push("object");
  if (!(r.typical || "").trim()) errs.push("typical");
  if (!(r.solution || "").trim()) errs.push("solution");
  if (!complicationOk(r)) errs.push("complication");
  if ((r.object_count || "") && !/^\d+$/.test(String(r.object_count).trim())) errs.push("n");
  return errs;
}

function selectedRows() {
  return state.rows.filter((r) => r.selected);
}

function updateSubmitState() {
  const selected = selectedRows();
  const pending = selected.filter((r) => r.status !== "ok");
  const invalid = pending.filter((r) => rowErrors(r).length);
  const btn = document.getElementById("btn-submit");
  const hint = document.getElementById("ready-hint");
  const ready = pending.length > 0 && invalid.length === 0 && !state.submitting;

  btn.disabled = !ready;
  if (!selected.length) {
    hint.textContent = "Отметьте хотя бы одну строку.";
  } else if (!pending.length) {
    hint.textContent = "Все отмеченные строки уже созданы в Okdesk.";
  } else if (invalid.length) {
    hint.textContent = `Не готово: ${invalid.length} из ${pending.length}. Нужны объект, typical, способ; для осложнения — и уровень, и пояснение.`;
  } else {
    hint.textContent = `Готово к отправке: ${pending.length} заявк(и).`;
  }

  document.getElementById("stats").innerHTML =
    `Строк: <b>${state.rows.length}</b> · отмечено: <b>${selected.length}</b> · к созданию: <b>${pending.length}</b> · ` +
    `<span class="stats-invalid" title="Нет объекта, типовой, способа; или осложнение без пояснения; или N не число">${
      invalid.length
        ? `с ошибками заполнения: <b>${invalid.length}</b>`
        : `с ошибками заполнения: <b>0</b>`
    }</span>`;

  const note = document.getElementById("stats-note");
  if (note) {
    note.hidden = false;
    if (invalid.length) {
      note.classList.add("is-warn");
    } else {
      note.classList.remove("is-warn");
    }
  }
}

function clearInvalidMarks() {
  document.querySelectorAll(".is-invalid, .is-invalid-row").forEach((n) => {
    n.classList.remove("is-invalid", "is-invalid-row");
  });
}

function highlightInvalid() {
  clearInvalidMarks();
  let first = null;
  for (const row of selectedRows()) {
    const errs = rowErrors(row);
    if (!errs.length) continue;
    const tr = document.querySelector(`tr[data-idx="${row._idx}"]`);
    if (!tr) continue;
    tr.classList.add("is-invalid-row");
    if (!first) first = tr;
    for (const key of errs) {
      tr.querySelectorAll(`[data-field="${key}"]`).forEach((n) => n.classList.add("is-invalid"));
    }
  }
  if (first) first.scrollIntoView({ behavior: "smooth", block: "center" });
}

function statusBadge(row) {
  if (row.status === "ok") {
    const wrap = el("div", {});
    if (row.dry_run) {
      wrap.append(el("span", { className: "badge badge--ok", text: "dry-run OK" }));
      return wrap;
    }
    wrap.append(el("span", { className: "badge badge--ok", text: "создано" }));
    if (row.issue_id) {
      const domain =
        (state.catalogs && state.catalogs.okdesk_domain) || "https://avers.okdesk.ru";
      const base = String(domain).replace(/\/$/, "");
      wrap.append(
        el("div", { className: "cell-meta", style: "margin-top:6px" }, [
          el("a", {
            href: `${base}/issues/${row.issue_id}`,
            target: "_blank",
            rel: "noopener",
            text: `Okdesk #${row.issue_id}`,
          }),
        ])
      );
    }
    return wrap;
  }
  if (row.status === "error") {
    const wrap = el("div", {});
    wrap.append(el("span", { className: "badge badge--err", text: "ошибка" }));
    if (row.status_error) {
      wrap.append(
        el("div", {
          className: "cell-meta",
          text: String(row.status_error).slice(0, 140),
        })
      );
    }
    return wrap;
  }
  if (row.status === "running") {
    return el("span", {
      className: "badge badge--run",
      text: "…",
      title: "Создание…",
    });
  }
  return el("span", {
    className: "badge badge--wait",
    text: "ожид.",
    title: "Ожидает заполнения / отправки",
  });
}

function renderTable() {
  // remove previous row object combo portals (not context-bar combos)
  document.querySelectorAll(".combo__list--row").forEach((n) => n.remove());

  const tbody = document.querySelector("#grid tbody");
  tbody.innerHTML = "";
  const typicals = state.catalogs.typical;
  const solutions = state.catalogs.solution_method;
  const levels = state.catalogs.complication_levels || ["+15", "+30"];

  for (const row of state.rows) {
    const tr = el("tr", {
      className: [
        row.object_id ? "" : "",
        row.status === "ok" ? "is-done" : "",
      ]
        .filter(Boolean)
        .join(" "),
    });
    tr.dataset.idx = String(row._idx);

    const cb = el("input", { type: "checkbox" });
    cb.checked = row.selected;
    cb.disabled = row.status === "ok" || state.submitting;
    cb.addEventListener("change", () => {
      row.selected = cb.checked;
      updateSubmitState();
    });

    const themeCell = el("td", { className: "col-theme" });
    themeCell.append(el("div", { className: "cell-theme-title", text: row.title }));
    if (row.external_url) {
      themeCell.append(
        el("div", { className: "cell-meta" }, [
          el("a", {
            href: row.external_url,
            target: "_blank",
            rel: "noopener",
            text: `UCG #${row.external_id || "ссылка"}`,
          }),
        ])
      );
    }

    // Object — searchable combobox
    const objWrap = el("div", { className: "obj-wrap" });
    if (row.suggested_object && !row.object_id) {
      row.object_id = row.suggested_object.id;
      row.object_name = row.suggested_object.name;
    }

    const combo = el("div", { className: "combo" });
    const objSearch = el("input", {
      type: "text",
      className: "input input--sm combo__input",
      "data-field": "object",
      placeholder: row.object_id
        ? row.object_name
        : row.object_hint
          ? `Искали: ${row.object_hint}`
          : "Поиск объекта MFC…",
      value: row.object_id
        ? row.object_name || ""
        : row.object_query || "",
      disabled: row.status === "ok",
      autocomplete: "off",
    });
    const list = el("div", { className: "combo__list combo__list--row", hidden: true });
    const clearBtn = el("button", {
      type: "button",
      className: "combo__clear",
      text: "×",
      title: "Сбросить",
      hidden: !row.object_id || row.status === "ok",
    });

    function closeList() {
      list.hidden = true;
      list.classList.remove("is-fixed");
    }

    function placeList() {
      const rect = objSearch.getBoundingClientRect();
      list.classList.add("is-fixed");
      list.style.position = "fixed";
      list.style.left = `${rect.left}px`;
      list.style.width = `${Math.max(rect.width, 260)}px`;
      list.style.top = `${rect.bottom + 4}px`;
      list.style.right = "auto";
      // если снизу мало места — вверх
      const spaceBelow = window.innerHeight - rect.bottom;
      if (spaceBelow < 180 && rect.top > 220) {
        list.style.top = "auto";
        list.style.bottom = `${window.innerHeight - rect.top + 4}px`;
        list.style.maxHeight = "220px";
      } else {
        list.style.bottom = "auto";
        list.style.maxHeight = "240px";
      }
    }

    function setObject(id, name) {
      row.object_id = id;
      row.object_name = name;
      row.object_query = "";
      objSearch.value = name || "";
      objSearch.placeholder = name || "Поиск объекта MFC…";
      clearBtn.hidden = !id || row.status === "ok";
      closeList();
      updateSubmitState();
    }

    function filterLocal(q) {
      const nq = (q || "").trim().toLowerCase().replace(/ё/g, "е");
      const all = state.objectsCache || [];
      if (!nq) return all.slice(0, 80);
      return all
        .filter((o) => String(o.name || "").toLowerCase().replace(/ё/g, "е").includes(nq))
        .slice(0, 80);
    }

    function renderList(items) {
      list.innerHTML = "";
      if (!items.length) {
        list.append(el("div", { className: "combo__empty", text: "Ничего не найдено" }));
        placeList();
        list.hidden = false;
        return;
      }
      for (const item of items) {
        const btn = el("button", {
          type: "button",
          className:
            "combo__option" +
            (row.object_id === item.id ? " is-active" : ""),
          text: item.name,
        });
        btn.addEventListener("mousedown", (e) => {
          e.preventDefault();
          setObject(item.id, item.name);
        });
        list.append(btn);
      }
      placeList();
      list.hidden = false;
    }

    async function ensureCache() {
      if (state.objectsCache.length) return;
      const data = await api(objectsApiUrl("", 500));
      state.objectsCache = data.items || [];
    }

    async function openSearch(q) {
      try {
        await ensureCache();
        let items = filterLocal(q);
        // если локально пусто — спросить API
        if (!items.length && q) {
          const data = await api(objectsApiUrl(q, 80));
          items = data.items || [];
        }
        renderList(items);
      } catch (e) {
        list.innerHTML = "";
        list.append(el("div", { className: "combo__empty", text: String(e.message || e) }));
        list.hidden = false;
      }
    }

    let timer;
    objSearch.addEventListener("focus", () => {
      if (row.status === "ok") return;
      // при фокусе на выбранном — искать заново
      if (row.object_id && objSearch.value === row.object_name) {
        objSearch.select();
      }
      openSearch(objSearch.value.trim() === row.object_name ? "" : objSearch.value.trim());
    });
    objSearch.addEventListener("input", () => {
      row.object_query = objSearch.value;
      // пользователь меняет текст — сбрасываем выбор, пока не кликнет из списка
      if (row.object_id && objSearch.value !== row.object_name) {
        row.object_id = null;
        row.object_name = null;
        clearBtn.hidden = true;
        updateSubmitState();
      }
      clearTimeout(timer);
      timer = setTimeout(() => openSearch(objSearch.value.trim()), 150);
    });
    objSearch.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeList();
      if (e.key === "Enter") {
        e.preventDefault();
        const first = list.querySelector(".combo__option");
        if (first) first.dispatchEvent(new Event("mousedown"));
      }
    });
    objSearch.addEventListener("blur", () => {
      setTimeout(closeList, 150);
    });
    clearBtn.addEventListener("click", () => {
      setObject(null, null);
      objSearch.value = "";
      objSearch.placeholder = row.object_hint
        ? `Искали: ${row.object_hint}`
        : "Поиск объекта MFC…";
      objSearch.focus();
      openSearch("");
    });

    combo.append(objSearch, clearBtn);
    // list portals to body so table scroll doesn't clip it
    document.body.appendChild(list);
    objWrap.append(combo);
    // cleanup when row re-renders: remove orphaned lists for this row
    list.dataset.rowIdx = String(row._idx);

    const typ = el("select", {
      className: "input input--sm",
      "data-field": "typical",
      disabled: row.status === "ok",
    });
    fillSelect(typ, typicals, row.typical || "");
    typ.title = row.typical || "Типовая проблема";
    typ.addEventListener("change", () => {
      row.typical = typ.value;
      typ.title = typ.value || "Типовая проблема";
      updateSubmitState();
    });
    row.typical = typ.value;

    const sol = el("select", {
      className: "input input--sm",
      "data-field": "solution",
      disabled: row.status === "ok",
    });
    fillSelect(sol, solutions, row.solution || "");
    sol.title = row.solution || "Способ решения";
    sol.addEventListener("change", () => {
      row.solution = sol.value;
      sol.title = sol.value || "Способ решения";
      updateSubmitState();
    });
    row.solution = sol.value;

    const nInput = el("input", {
      type: "text",
      inputmode: "numeric",
      className: "input input--sm input--n",
      "data-field": "n",
      placeholder: "1",
      title: "N — число объектов в пакете (точки/кассы). Баллы = база × N. Для разовой заявки — 1 или пусто",
      value: row.object_count || "",
      disabled: row.status === "ok",
    });
    nInput.addEventListener("input", () => {
      row.object_count = nInput.value.trim();
      updateSubmitState();
    });

    const level = el("select", {
      className: "input input--sm",
      "data-field": "complication",
      disabled: row.status === "ok",
    });
    fillSelect(level, levels, row.complication_level || "");

    const compDesc = el("textarea", {
      className: "input input--area input--comp-note",
      "data-field": "complication",
      placeholder: "почему +15 / +30",
      rows: "2",
      disabled: row.status === "ok",
    });
    compDesc.value = row.complication || "";
    compDesc.hidden = !row.complication_level;

    level.addEventListener("change", () => {
      row.complication_level = level.value;
      if (!level.value) {
        row.complication = "";
        compDesc.value = "";
        compDesc.hidden = true;
      } else {
        compDesc.hidden = false;
        compDesc.focus();
      }
      updateSubmitState();
    });
    compDesc.addEventListener("input", () => {
      row.complication = compDesc.value;
      updateSubmitState();
    });

    const compStack = el("div", { className: "comp-stack" }, [level, compDesc]);

    const desc = el("textarea", {
      className: "input input--area input--desc",
      placeholder: "описание; при N>1 — список объектов",
      rows: "6",
      disabled: row.status === "ok",
    });
    desc.value = row.description || "";
    desc.addEventListener("input", () => {
      row.description = desc.value;
    });

    tr.append(
      el("td", { className: "col-check" }, [cb]),
      el("td", { className: "col-status" }, [statusBadge(row)]),
      themeCell,
      el("td", { className: "col-object" }, [objWrap]),
      el("td", { className: "col-typical" }, [typ]),
      el("td", { className: "col-solution" }, [sol]),
      el("td", { className: "col-n" }, [nInput]),
      el("td", { className: "col-comp" }, [compStack]),
      el("td", { className: "col-desc" }, [desc])
    );
    tbody.append(tr);
  }
  updateSubmitState();
}

function applyParsedRows(dataRows, { fingerprintValue } = {}) {
  // Deduplicate by external_id / title against existing pending rows
  const existingKeys = new Set(
    state.rows.map((r) => r.external_id || `t:${r.title}`)
  );
  const incoming = [];
  let skipped = 0;
  for (const r of dataRows || []) {
    const key = r.external_id || `t:${r.title}`;
    if (existingKeys.has(key) && state.rows.length) {
      skipped += 1;
      continue;
    }
    existingKeys.add(key);
    incoming.push(r);
  }

  const base = state.rows.length;
  const mapped = incoming.map((r, i) => ({
    ...r,
    _idx: base + i,
    selected: true,
    object_id: r.suggested_object?.id || null,
    object_name: r.suggested_object?.name || null,
    typical: r.suggested_typical || "",
    solution: "",
    object_count: "",
    complication_level: "",
    complication: "",
    description: r.description || r.external_description || "",
    status: "pending",
    issue_id: null,
    status_error: null,
  }));

  // Re-index if replacing
  if (!state.rows.length) {
    state.rows = mapped.map((r, i) => ({ ...r, _idx: i }));
  } else {
    state.rows = [...state.rows, ...mapped].map((r, i) => ({ ...r, _idx: i }));
  }

  if (fingerprintValue) state.appliedFingerprint = fingerprintValue;

  document.getElementById("step-table").hidden = false;
  setActiveNav(2);
  setStep1Collapsed(true);
  renderTable();

  if (skipped) {
    toast(`Пропущено дублей: ${skipped}. Добавлено: ${mapped.length}.`, "");
  } else {
    toast(`В таблице ${state.rows.length} строк(и).`, "ok");
  }
  syncApplyEnabled({ updateHint: false });
}

function syncApplyEnabled({ updateHint = true } = {}) {
  const paste = document.getElementById("paste");
  const btn = document.getElementById("btn-apply");
  const clearBtn = document.getElementById("btn-clear-list");
  const hint = document.getElementById("apply-hint");
  if (!paste || !btn) return;
  const hasText = !!paste.value.trim();
  const hasRows = (state.rows || []).length > 0;
  if (!btn.classList.contains("is-busy")) {
    btn.disabled = !hasText;
  }
  if (clearBtn && !clearBtn.classList.contains("is-busy")) {
    clearBtn.disabled = !hasText && !hasRows;
  }
  if (updateHint && hint && !btn.classList.contains("is-busy")) {
    hint.textContent = hasText
      ? "Можно нажать «Применить»."
      : "Вставьте список — кнопка «Применить» станет активной.";
  }
}

function clearPasteAndTable() {
  const paste = document.getElementById("paste");
  if (paste) paste.value = "";
  state.rows = [];
  state.appliedFingerprint = null;
  state.isTasks = [];
  const stepTable = document.getElementById("step-table");
  if (stepTable) stepTable.hidden = true;
  const tbody = document.querySelector("#grid tbody");
  if (tbody) tbody.innerHTML = "";
  document.querySelectorAll(".combo__list--row").forEach((n) => n.remove());
  setStep1Collapsed(false);
  setActiveNav(1);
  const summary = document.getElementById("step1-summary");
  if (summary) {
    summary.hidden = true;
    summary.textContent = "";
  }
  const applyStatus = document.getElementById("apply-status");
  if (applyStatus) applyStatus.hidden = true;
  const meta = document.getElementById("meta");
  if (meta && state.catalogs) {
    /* keep catalogs meta */
  }
  syncApplyEnabled();
  updateSubmitState();
  toast("Список очищен.", "ok");
}

function setApplyBusy(busy, message) {
  const btn = document.getElementById("btn-apply");
  const status = document.getElementById("apply-status");
  const statusText = document.getElementById("apply-status-text");
  const hint = document.getElementById("apply-hint");
  if (btn) {
    btn.classList.toggle("is-busy", busy);
    if (busy) btn.disabled = true;
    else syncApplyEnabled({ updateHint: false });
  }
  if (status) status.hidden = !busy;
  if (statusText && message) statusText.textContent = message;
  if (hint && busy) hint.textContent = "";
}

async function applyPasteList() {
  const paste = document.getElementById("paste");
  const text = paste?.value || "";
  if (!text.trim()) {
    toast("Вставьте список задач в поле ввода.", "error");
    paste?.classList.add("is-invalid");
    syncApplyEnabled();
    return;
  }
  paste.classList.remove("is-invalid");

  const fp = fingerprint(text);
  if (state.appliedFingerprint === fp && state.rows.length) {
    const ok = window.confirm(
      "Этот список уже применён. Применить ещё раз и заменить таблицу?"
    );
    if (!ok) return;
    state.rows = [];
  }

  const enrichOn = isMfcCompany() && !!document.getElementById("enrich")?.checked;
  let resultHint = "";
  setApplyBusy(
    true,
    enrichOn
      ? "Разбор списка и подтягивание данных с help.ucg.ru…"
      : "Разбор списка…"
  );

  try {
    if (state.appliedFingerprint !== fp) {
      state.rows = [];
    }
    const data = await api("/api/mfc/parse", {
      method: "POST",
      body: JSON.stringify({
        text,
        enrich: enrichOn,
        company_id: state.companyId || undefined,
      }),
    });
    if (!data.rows?.length) {
      toast("Парсер не нашёл строк.", "error");
      resultHint = "Строк не найдено — проверьте формат списка.";
      return;
    }
    applyParsedRows(data.rows, { fingerprintValue: fp });
    resultHint =
      `Применено ${data.rows.length} строк. IntraService enrich: ${data.enriched ? "да" : "нет"}.`;
  } catch (e) {
    toast(String(e.message || e), "error");
    resultHint = "Ошибка применения — см. уведомление.";
  } finally {
    setApplyBusy(false);
    const hint = document.getElementById("apply-hint");
    if (hint && resultHint) hint.textContent = resultHint;
  }
}

const SIDEBAR_KEY = "mfc-sidebar-collapsed";

function isMobileNav() {
  return window.matchMedia("(max-width: 960px)").matches;
}

function syncSidebarUi() {
  const shell = document.getElementById("app-shell");
  const toggle = document.getElementById("btn-sidebar-toggle");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (!shell || !toggle) return;

  const collapsed = shell.classList.contains("is-sidebar-collapsed");
  const open = shell.classList.contains("is-sidebar-open");

  if (isMobileNav()) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.title = open ? "Закрыть меню" : "Открыть меню";
    if (backdrop) backdrop.hidden = !open;
  } else {
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.title = collapsed ? "Развернуть меню" : "Свернуть меню";
    shell.classList.remove("is-sidebar-open");
    if (backdrop) backdrop.hidden = true;
  }
}

function setSidebarCollapsed(collapsed) {
  const shell = document.getElementById("app-shell");
  if (!shell) return;
  shell.classList.toggle("is-sidebar-collapsed", collapsed);
  try {
    localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  } catch (_) {}
  syncSidebarUi();
}

function setSidebarOpen(open) {
  const shell = document.getElementById("app-shell");
  if (!shell) return;
  shell.classList.toggle("is-sidebar-open", open);
  syncSidebarUi();
}

function initSidebar() {
  const shell = document.getElementById("app-shell");
  const toggle = document.getElementById("btn-sidebar-toggle");
  const openBtn = document.getElementById("btn-menu-open");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (!shell || !toggle) return;

  let collapsed = false;
  try {
    collapsed = localStorage.getItem(SIDEBAR_KEY) === "1";
  } catch (_) {}
  shell.classList.toggle("is-sidebar-collapsed", collapsed);
  syncSidebarUi();

  toggle.addEventListener("click", () => {
    if (isMobileNav()) {
      setSidebarOpen(!shell.classList.contains("is-sidebar-open"));
    } else {
      setSidebarCollapsed(!shell.classList.contains("is-sidebar-collapsed"));
    }
  });

  openBtn?.addEventListener("click", () => setSidebarOpen(true));
  backdrop?.addEventListener("click", () => setSidebarOpen(false));

  document.getElementById("nav-step-1")?.addEventListener("click", () => {
    if (isMobileNav()) setSidebarOpen(false);
  });
  document.getElementById("nav-step-2")?.addEventListener("click", () => {
    if (isMobileNav()) setSidebarOpen(false);
  });

  window.addEventListener("resize", () => syncSidebarUi());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && shell.classList.contains("is-sidebar-open")) {
      setSidebarOpen(false);
    }
  });
}

async function init() {
  initSidebar();

  const pasteEl = document.getElementById("paste");
  const applyBtn = document.getElementById("btn-apply");
  const clearListBtn = document.getElementById("btn-clear-list");
  pasteEl?.addEventListener("input", syncApplyEnabled);
  pasteEl?.addEventListener("change", syncApplyEnabled);
  pasteEl?.addEventListener("paste", () => setTimeout(syncApplyEnabled, 0));
  applyBtn?.addEventListener("click", () => {
    applyPasteList().catch((e) => toast(String(e.message || e), "error"));
  });
  clearListBtn?.addEventListener("click", () => {
    if (!pasteEl?.value.trim() && !(state.rows || []).length) return;
    if ((state.rows || []).length && !confirm("Очистить поле списка и таблицу?")) return;
    clearPasteAndTable();
  });
  syncApplyEnabled();

  try {
    state.catalogs = await api("/api/mfc/catalogs");
  } catch (e) {
    toast(`Каталоги не загрузились: ${e.message || e}`, "error");
    return;
  }
  document.getElementById("enrich")?.addEventListener("change", () => {
    document.getElementById("enrich").dataset.userTouched = "1";
  });

  await initContextBar();
  syncIntraserviceUi();
  refreshHealth();

  document.getElementById("badge-okdesk").addEventListener("click", () => openStatusModal("okdesk"));
  document.getElementById("badge-intraservice").addEventListener("click", () => openStatusModal("intraservice"));
  document.getElementById("status-modal-close").addEventListener("click", closeStatusModal);
  document.getElementById("status-modal").addEventListener("mousedown", (e) => {
    if (e.target === e.currentTarget) closeStatusModal();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeStatusModal();
  });

  const dryRun = document.getElementById("dry-run");
  const dryChip = document.getElementById("dry-run-chip");
  function syncDryNote() {
    if (!dryRun || !dryChip) return;
    dryChip.title = dryRun.checked
      ? "Dry-run: без записи в Okdesk — только проверка"
      : "Осторожно: будет запись в Okdesk";
  }
  dryRun?.addEventListener("change", syncDryNote);
  syncDryNote();

  document.getElementById("btn-toggle-step1")?.addEventListener("click", () => {
    const collapsed = document.getElementById("step-input").classList.contains("is-collapsed");
    setStep1Collapsed(!collapsed);
    setActiveNav(1);
  });

  document.getElementById("nav-step-1")?.addEventListener("click", () => {
    setActiveNav(1);
    setStep1Collapsed(false);
  });
  document.getElementById("nav-step-2")?.addEventListener("click", (e) => {
    if (document.getElementById("step-table").hidden) {
      e.preventDefault();
      toast("Сначала примените список в разделе 1.", "error");
      return;
    }
    setActiveNav(2);
  });

  // preload objects for selected company
  reloadObjectsCache();

  // —— IntraService optional picker ——
  document.getElementById("btn-is-optional").addEventListener("click", () => {
    document.getElementById("is-panel").hidden = false;
    document.getElementById("btn-is-load").click();
  });
  document.getElementById("btn-is-close").addEventListener("click", () => {
    document.getElementById("is-panel").hidden = true;
  });

  function renderIsTasks() {
    const tbody = document.querySelector("#is-grid tbody");
    tbody.innerHTML = "";
    for (const t of state.isTasks) {
      const tr = el("tr");
      const cb = el("input", { type: "checkbox" });
      if (t._selected === undefined) t._selected = false;
      cb.checked = !!t._selected;
      cb.addEventListener("change", () => {
        t._selected = cb.checked;
      });
      tr.append(
        el("td", {}, [cb]),
        el("td", { text: String(t.id) }),
        el("td", { text: t.name }),
        el("td", { text: t.company || "—" }),
        el("td", {}, [
          el("a", {
            href: t.url,
            target: "_blank",
            rel: "noopener",
            text: "открыть",
          }),
        ])
      );
      tbody.append(tr);
    }
    document.getElementById("is-status").textContent =
      `Загружено: ${state.isTasks.length}. Отметьте нужные → «Вставить отмеченные в поле», затем «Применить».`;
  }

  document.getElementById("btn-is-load").addEventListener("click", async () => {
    const q = document.getElementById("is-q").value.trim();
    document.getElementById("is-status").textContent = "Загрузка…";
    try {
      const data = await api(
        `/api/mfc/intraservice/tasks?q=${encodeURIComponent(q)}&pagesize=40`
      );
      state.isTasks = (data.items || []).map((t) => ({ ...t, _selected: false }));
      renderIsTasks();
    } catch (e) {
      document.getElementById("is-status").textContent = `Ошибка: ${e.message || e}`;
    }
  });

  document.getElementById("btn-is-to-paste").addEventListener("click", () => {
    const selected = state.isTasks.filter((t) => t._selected);
    if (!selected.length) {
      toast("Отметьте заявки IntraService.", "error");
      return;
    }
    const urls = selected.map((t) => t.url).join("\n");
    const paste = document.getElementById("paste");
    paste.value = paste.value.trim() ? `${paste.value.trim()}\n${urls}` : urls;
    syncApplyEnabled();
    document.getElementById("is-panel").hidden = true;
    toast(`Вставлено ссылок: ${selected.length}. Нажмите «Применить».`, "ok");
  });

  // —— Submit ——
  document.getElementById("btn-submit").addEventListener("click", async () => {
    if (state.submitting) return;

    const pending = selectedRows().filter((r) => r.status !== "ok");
    const invalid = pending.filter((r) => rowErrors(r).length);
    if (invalid.length) {
      highlightInvalid();
      toast("Заполните все обязательные поля (подсвечены).", "error");
      return;
    }
    if (!pending.length) {
      toast("Нет строк для создания.", "error");
      return;
    }

    const dryRun = document.getElementById("dry-run").checked;
    if (!state.companyId || !state.assigneeId) {
      toast("Выберите клиента и ответственного в шапке.", "error");
      return;
    }
    if (!dryRun && !confirm(
      `Создать и закрыть ${pending.length} заявок в Okdesk?\n` +
      `Клиент: ${state.companyName}\nОтветственный: ${state.assigneeName}`
    )) return;

    state.submitting = true;
    updateSubmitState();
    for (const r of pending) r.status = "running";
    renderTable();

    const items = pending.map((r) => ({
      title: r.title,
      object_id: r.object_id,
      typical: r.typical,
      solution: r.solution,
      selected: true,
      external_url: r.external_url || null,
      description: (r.description || "").trim() || null,
      complication_level: (r.complication_level || "").trim() || null,
      complication: (r.complication || "").trim() || null,
      object_count: (r.object_count || "").trim() || null,
      _idx: r._idx,
    }));

    try {
      const data = await api("/api/mfc/batch", {
        method: "POST",
        body: JSON.stringify({
          items: items.map(({ _idx, ...rest }) => rest),
          batch_comment: document.getElementById("batch-comment").value || null,
          dry_run: dryRun,
          company_id: state.companyId,
          assignee_id: state.assigneeId,
        }),
      });

      for (const res of data.results || []) {
        const item = items[res.index];
        if (!item) continue;
        const row = state.rows.find((r) => r._idx === item._idx);
        if (!row) continue;
        if (res.skipped) continue;
        if (res.ok) {
          row.status = "ok";
          row.dry_run = !!data.dry_run;
          row.issue_id = res.issue_id || null;
          row.status_error = null;
        } else {
          row.status = "error";
          row.status_error = res.error || "ошибка";
        }
      }

      renderTable();
      const ok = data.ok || 0;
      const fail = data.failed || 0;
      toast(
        data.dry_run
          ? `Dry-run: проверено ${ok}, ошибок ${fail}.`
          : `Создано: ${ok}, ошибок: ${fail}.`,
        fail ? "error" : "ok"
      );
    } catch (e) {
      for (const r of pending) {
        if (r.status === "running") {
          r.status = "error";
          r.status_error = String(e.message || e);
        }
      }
      renderTable();
      toast(String(e.message || e), "error");
    } finally {
      state.submitting = false;
      updateSubmitState();
    }
  });
}

init().catch((e) => {
  document.getElementById("meta").textContent = `Ошибка: ${e.message || e}`;
  toast(String(e.message || e), "error");
});
