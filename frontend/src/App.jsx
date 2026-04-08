import { useEffect, useMemo, useRef, useState } from "react";

const PAGE_SIZE = 50;
const AUTO_REFRESH_MS = 15000;

const INITIAL_FILTERS = {
  q: "",
  status_preset: "active_plus_errors",
  date_from: "",
  date_to: "",
};

const HEADER_LOGOS = [
  { src: "/logo/hightek.png", alt: "Hightek", caption: "hightek" },
  { src: "/logo/nettovvx-studio.png", alt: "Nettovvx Studio", caption: "nettovvx-studio" },
  { src: "/logo/finist.png", alt: "Finist", caption: "finist" },
];

function getPathPage(pathname, role) {
  if (role === "admin" && pathname.startsWith("/users")) {
    return "users";
  }
  return "monitor";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    ...options,
  });

  if (response.status === 204) {
    return null;
  }

  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : null;
  if (response.ok === false) {
    throw new Error(payload?.detail ?? "Ошибка запроса");
  }
  return payload;
}

function buildQuery(params) {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      searchParams.set(key, String(value));
    }
  }
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

function mapStatusPresetToQuery(statusPreset) {
  switch (statusPreset) {
    case "in_progress":
      return { view: "active", status_filter: "in_progress" };
    case "success":
      return { view: "success", status_filter: "" };
    case "errors":
      return { view: "errors", status_filter: "" };
    case "all":
      return { view: "all", status_filter: "" };
    case "active_plus_errors":
    default:
      return { view: "active", status_filter: "" };
  }
}

function clampFutureDate(date) {
  const now = Date.now();
  if (date.getTime() > now) {
    return new Date(now);
  }
  return date;
}

function formatDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return clampFutureDate(date).toLocaleString("ru-RU");
}

function stepMeta(step) {
  const parts = [];
  parts.push(step.status || "pending");
  parts.push(step.occurred_at ? formatDate(step.occurred_at) : "время не зафиксировано");
  if (step.delta_human) {
    parts.push(`+${step.delta_human}`);
  }
  return parts.join(" · ");
}

function StatusPill({ status }) {
  return <span className={`pill status-${status}`}>{status}</span>;
}

function HeaderBlock({ title, subtitle, right }) {
  return (
    <div className="panel-head">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

function deriveTicketGroupsFromEntries(entries) {
  const ticketCases = [];
  for (const entry of entries) {
    if (entry.entry_type === "ticket_case" && entry.ticket_case) {
      ticketCases.push(entry.ticket_case);
    }
  }
  return { ticketCases, orphanRealizations: [] };
}

function mergeTicketListing(previous, next) {
  if (!previous) {
    return next;
  }
  const mergedEntries = [];
  const seen = new Set();
  for (const entry of [...previous.entries, ...next.entries]) {
    if (seen.has(entry.entry_id)) {
      continue;
    }
    seen.add(entry.entry_id);
    mergedEntries.push(entry);
  }
  const groups = deriveTicketGroupsFromEntries(mergedEntries);
  return {
    ...next,
    entries: mergedEntries,
    ticket_cases: groups.ticketCases,
    orphan_realizations: groups.orphanRealizations,
  };
}

function mergePaymentListing(previous, next) {
  if (!previous) {
    return next;
  }
  const mergedRows = [];
  const seen = new Set();
  for (const row of [...previous.rows, ...next.rows]) {
    const key = row.document.id;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    mergedRows.push(row);
  }
  return {
    ...next,
    rows: mergedRows,
  };
}

function getLoadedCount(listing, activeTab) {
  if (!listing) {
    return 0;
  }
  if (activeTab === "tickets") {
    return Array.isArray(listing.entries) ? listing.entries.length : 0;
  }
  return Array.isArray(listing.rows) ? listing.rows.length : 0;
}

function TicketCards({ listing, onOpenDocument }) {
  const entries = Array.isArray(listing?.entries) ? listing.entries : [];

  return (
    <section className="cards-grid">
      {entries.map((entry, index) => {
        if (entry.entry_type === "ticket_case" && entry.ticket_case) {
          const caseItem = entry.ticket_case;
          return (
            <article key={entry.entry_id} className="card animated-card" style={{ "--stagger": index }}>
              <HeaderBlock
                title={caseItem.ticket.payload?.passenger_name || caseItem.ticket.title || caseItem.ticket.file_name}
                subtitle={`Билет: ${caseItem.ticket.payload?.ticket_number || "—"} · PNR: ${caseItem.ticket.payload?.pnr || "—"}`}
                right={
                  <div className="row-actions">
                    <StatusPill status={caseItem.group_status} />
                    <button className="ghost" onClick={() => onOpenDocument(caseItem.ticket.id)} type="button">
                      Маршрут
                    </button>
                  </div>
                }
              />

              <div className="row-actions">
                <small>
                  {caseItem.realizations.length > 0
                    ? `Связанных реализаций: ${caseItem.realizations.length}`
                    : "Связанная реализация пока не найдена"}
                </small>
              </div>

              <div className="steps">
                {caseItem.steps.map((step) => (
                  <div key={step.code} className={`step status-${step.status}`}>
                    <strong>{step.label}</strong>
                    <small>{stepMeta(step)}</small>
                  </div>
                ))}
              </div>

              <div className="chips">
                {caseItem.realizations.map((item) => (
                  <button key={item.id} className="chip" onClick={() => onOpenDocument(item.id)} type="button">
                    {item.payload?.mom_number || item.title || item.file_name}
                  </button>
                ))}
              </div>

              <div className="row-actions">
                <small>Последняя активность: {formatDate(caseItem.last_activity_at)}</small>
              </div>
            </article>
          );
        }

        return null;
      })}
    </section>
  );
}

function PaymentCards({ listing, onOpenDocument }) {
  const rows = Array.isArray(listing?.rows) ? listing.rows : [];
  return (
    <section className="cards-grid">
      {rows.map((row, index) => {
        const entries = Array.isArray(row.document.payload?.extra_json?.entries) ? row.document.payload.extra_json.entries : [];
        return (
        <article key={row.document.id} className="card animated-card" style={{ "--stagger": index }}>
          <HeaderBlock
            title={row.document.title || row.document.file_name}
            subtitle={row.document.file_name}
            right={<StatusPill status={row.document.status} />}
          />
          <div className="row-actions">
            <small>
              MOM: {row.document.payload?.mom_number || "—"} · Сумма: {row.document.payload?.amount ?? "—"} {row.document.payload?.currency || ""}
            </small>
            <button className="ghost" onClick={() => onOpenDocument(row.document.id)} type="button">
              Детали
            </button>
          </div>

          {entries.length > 0 && (
            <div className="payment-lines">
              {entries.map((item, itemIndex) => (
                <small key={`${row.document.id}-entry-${itemIndex}`}>
                  #{item.number || "без номера"} · {item.direction || "unknown"} · {item.amount ?? "—"} · {item.mom_ref || "без MOM"}
                </small>
              ))}
            </div>
          )}
        </article>
      );
      })}
    </section>
  );
}

function ArchiveCards({ listing }) {
  const rows = Array.isArray(listing?.rows) ? listing.rows : [];
  return (
    <section className="cards-grid">
      {rows.map((row, index) => (
        <article key={row.document.id} className="card animated-card" style={{ "--stagger": index }}>
          <HeaderBlock
            title={row.document.title || row.document.file_name}
            subtitle={`${row.document.doc_type} · ${row.document.flow_group}`}
            right={<StatusPill status={row.document.status} />}
          />
          <div className="row-actions">
            <small>Архивировано: {formatDate(row.archived_at)}</small>
            <small>Файл: {row.document.file_name}</small>
          </div>
          <div className="row-actions">
            <small>PNR: {row.document.payload?.pnr || "—"} · MOM: {row.document.payload?.mom_number || "—"}</small>
            <small>Платежка: {row.document.payload?.payment_number || "—"}</small>
          </div>
        </article>
      ))}
    </section>
  );
}

function DetailModal({ user, detail, loading, onClose, onHide, onUnhide }) {
  if (!detail && !loading) {
    return null;
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-top">
          <h2>Детализация документа</h2>
          <button className="ghost" type="button" onClick={onClose}>
            Закрыть
          </button>
        </div>

        {loading && <p className="loading">Загружаем маршрут...</p>}

        {!loading && detail && (
          <>
            <div className="detail-headline">
              <h3>{detail.root_ticket.title || detail.root_ticket.file_name}</h3>
              <StatusPill status={detail.document.status} />
            </div>

            <div className="steps">
              {detail.steps.map((step) => (
                <div key={step.code} className={`step status-${step.status}`}>
                  <strong>{step.label}</strong>
                  <small>{stepMeta(step)}</small>
                </div>
              ))}
            </div>

            {user.role === "admin" && (
              <div className="row-actions">
                <small>Админ-действие для корневого билета</small>
                {detail.root_ticket_state?.is_hidden ? (
                  <button className="ghost" onClick={() => onUnhide(detail.root_ticket.id)} type="button">
                    Вернуть билет в оперативный список
                  </button>
                ) : (
                  <button className="ghost warn" onClick={() => onHide(detail.root_ticket.id)} type="button">
                    Скрыть билет из оперативного списка
                  </button>
                )}
              </div>
            )}

            <div className="timeline">
              {(detail.document.events || []).map((event) => (
                <div key={event.id} className="timeline-row">
                  <StatusPill status={event.status} />
                  <div>
                    <strong>{event.step_code}</strong>
                    <p>{event.message || "Без комментария"}</p>
                    <small>{formatDate(event.occurred_at)}</small>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function UsersPage({ currentUser, users, loading, message, onCreate, onRoleChange, onDelete }) {
  const [form, setForm] = useState({ username: "", password: "", role: "user" });
  const [busyUserId, setBusyUserId] = useState("");

  async function submitCreate(event) {
    event.preventDefault();
    const created = await onCreate(form);
    if (created) {
      setForm({ username: "", password: "", role: "user" });
    }
  }

  return (
    <section className="users-page">
      <article className="admin-panel">
        <HeaderBlock title="Создать пользователя" subtitle="Доступно только администраторам" />
        <form className="inline-form" onSubmit={submitCreate}>
          <input
            placeholder="Логин"
            value={form.username}
            onChange={(event) => setForm((prev) => ({ ...prev, username: event.target.value }))}
            required
          />
          <input
            placeholder="Пароль"
            type="password"
            value={form.password}
            onChange={(event) => setForm((prev) => ({ ...prev, password: event.target.value }))}
            required
          />
          <select value={form.role} onChange={(event) => setForm((prev) => ({ ...prev, role: event.target.value }))}>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <button type="submit">Создать</button>
        </form>
      </article>

      <article className="admin-panel">
        <HeaderBlock title="Пользователи" subtitle="Изменение ролей и удаление учетных записей" />
        {message && <p className="muted-line">{message}</p>}
        {loading && <p className="loading">Загружаем пользователей...</p>}
        <div className="user-list">
          {users.map((item) => (
            <div key={item.id} className="user-row expanded">
              <div>
                <strong>{item.username}</strong>
                <small>{item.is_active ? "active" : "inactive"} · последний вход: {formatDate(item.last_login_at)}</small>
              </div>

              <select value={item.role} onChange={(event) => onRoleChange(item.id, event.target.value)} disabled={busyUserId === item.id}>
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>

              <button
                className="ghost warn"
                type="button"
                disabled={item.id === currentUser.id || busyUserId === item.id}
                onClick={async () => {
                  setBusyUserId(item.id);
                  try {
                    await onDelete(item.id);
                  } finally {
                    setBusyUserId("");
                  }
                }}
              >
                Удалить
              </button>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");
  const [pagePath, setPagePath] = useState(window.location.pathname);

  const [login, setLogin] = useState({ username: "admin", password: "admin123" });
  const [activeTab, setActiveTab] = useState("tickets");
  const [filters, setFilters] = useState(INITIAL_FILTERS);

  const [listing, setListing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [adminUsers, setAdminUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [adminMessage, setAdminMessage] = useState("");

  const loadMoreRef = useRef(null);
  const requestIdRef = useRef(0);

  const currentPage = getPathPage(pagePath, user?.role);
  const counters = useMemo(() => listing?.counters ?? {}, [listing]);
  const filteredCount = listing?.filtered_count ?? 0;
  const totalCount = listing?.total_count ?? 0;

  useEffect(() => {
    const handler = () => setPagePath(window.location.pathname);
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);

  useEffect(() => {
    api("/api/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  function navigate(path) {
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
    setPagePath(path);
  }

  useEffect(() => {
    if (!user) {
      return;
    }
    if (user.role !== "admin" && currentPage === "users") {
      navigate("/");
    }
  }, [user, currentPage]);

  async function fetchMonitorListing({ offset = 0, limit = PAGE_SIZE, append = false, silent = false } = {}) {
    if (!user || currentPage !== "monitor") {
      return;
    }

    const requestId = ++requestIdRef.current;
    const endpoint =
      activeTab === "tickets"
        ? "/api/documents/tickets"
        : activeTab === "payments"
          ? "/api/documents/payments"
          : "/api/documents/archive";
    const { status_preset, ...baseFilters } = filters;
    const statusQuery = mapStatusPresetToQuery(status_preset);
    const query = buildQuery({ ...baseFilters, ...statusQuery, offset, limit });

    if (append) {
      setLoadingMore(true);
    } else if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const data = await api(`${endpoint}${query}`);
      if (requestId !== requestIdRef.current) {
        return;
      }
      setError("");
      setListing((prev) => {
        if (!append) {
          return data;
        }
        return activeTab === "tickets" ? mergeTicketListing(prev, data) : mergePaymentListing(prev, data);
      });
    } catch (eventError) {
      if (requestId === requestIdRef.current) {
        setError(eventError.message);
      }
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
        setLoadingMore(false);
        setRefreshing(false);
      }
    }
  }

  useEffect(() => {
    if (!user || currentPage !== "monitor") {
      return;
    }
    setDetail(null);
    fetchMonitorListing({ offset: 0, limit: PAGE_SIZE });
  }, [user, currentPage, activeTab, filters]);

  useEffect(() => {
    if (!user || currentPage !== "monitor") {
      return;
    }
    const intervalId = window.setInterval(() => {
      const currentLimit = Math.max(getLoadedCount(listing, activeTab), PAGE_SIZE);
      fetchMonitorListing({ offset: 0, limit: currentLimit, silent: true });
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(intervalId);
  }, [user, currentPage, activeTab, filters, listing]);

  useEffect(() => {
    if (!user || currentPage !== "monitor" || !loadMoreRef.current) {
      return undefined;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const firstEntry = entries[0];
        if (!firstEntry?.isIntersecting || loading || loadingMore || !listing?.has_more) {
          return;
        }
        fetchMonitorListing({
          offset: getLoadedCount(listing, activeTab),
          limit: PAGE_SIZE,
          append: true,
          silent: true,
        });
      },
      { rootMargin: "320px 0px" },
    );

    observer.observe(loadMoreRef.current);
    return () => observer.disconnect();
  }, [user, currentPage, activeTab, listing, loading, loadingMore, filters]);

  useEffect(() => {
    if (!user || user.role !== "admin" || currentPage !== "users") {
      return;
    }
    setUsersLoading(true);
    api("/api/admin/users")
      .then((data) => {
        setAdminUsers(data);
        setAdminMessage("");
      })
      .catch((eventError) => setAdminMessage(eventError.message))
      .finally(() => setUsersLoading(false));
  }, [user, currentPage]);

  async function refreshCurrentList() {
    if (currentPage !== "monitor") {
      return;
    }
    const currentLimit = Math.max(getLoadedCount(listing, activeTab), PAGE_SIZE);
    await fetchMonitorListing({ offset: 0, limit: currentLimit, silent: true });
  }

  async function onLogin(event) {
    event.preventDefault();
    setAuthError("");
    try {
      const me = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify(login),
      });
      setUser(me);
      navigate("/");
    } catch (loginError) {
      setAuthError(loginError.message);
    }
  }

  async function onLogout() {
    await api("/api/auth/logout", { method: "POST" });
    setUser(null);
    setListing(null);
    setDetail(null);
  }

  async function openDocument(documentId) {
    setDetailLoading(true);
    try {
      const data = await api(`/api/documents/${documentId}`);
      setDetail(data);
    } catch (detailError) {
      setError(detailError.message);
    } finally {
      setDetailLoading(false);
    }
  }

  async function hideDocument(documentId) {
    await api(`/api/documents/${documentId}/hide`, {
      method: "POST",
      body: JSON.stringify({ reason: "Просмотрено оператором" }),
    });
    await refreshCurrentList();
    if (detail?.document?.id) {
      await openDocument(detail.document.id);
    }
  }

  async function unhideDocument(documentId) {
    await api(`/api/documents/${documentId}/unhide`, { method: "POST" });
    await refreshCurrentList();
    if (detail?.document?.id) {
      await openDocument(detail.document.id);
    }
  }

  async function createUser(payload) {
    try {
      const account = await api("/api/admin/users", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAdminUsers((prev) => [account, ...prev]);
      setAdminMessage("Пользователь создан");
      return true;
    } catch (createError) {
      setAdminMessage(createError.message);
      return false;
    }
  }

  async function changeUserRole(userId, role) {
    try {
      const account = await api(`/api/admin/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      });
      setAdminUsers((prev) => prev.map((item) => (item.id === userId ? account : item)));
      setAdminMessage("Роль обновлена");
    } catch (changeError) {
      setAdminMessage(changeError.message);
    }
  }

  async function deleteUser(userId) {
    if (window.confirm("Удалить пользователя?")) {
      try {
        await api(`/api/admin/users/${userId}`, { method: "DELETE" });
        setAdminUsers((prev) => prev.filter((item) => item.id !== userId));
        setAdminMessage("Пользователь удален");
      } catch (deleteError) {
        setAdminMessage(deleteError.message);
      }
    }
  }

  if (authLoading) {
    return <div className="splash">Загружаем TicketFlow...</div>;
  }

  if (!user) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <div className="brand">TF</div>
          <h1>TicketFlow</h1>
          <p>Операционная панель по цепочке ticket → realization → payment.</p>
          <form onSubmit={onLogin} className="auth-form">
            <label>
              Логин
              <input value={login.username} onChange={(event) => setLogin((prev) => ({ ...prev, username: event.target.value }))} required />
            </label>
            <label>
              Пароль
              <input
                type="password"
                value={login.password}
                onChange={(event) => setLogin((prev) => ({ ...prev, password: event.target.value }))}
                required
              />
            </label>
            <button type="submit">Войти</button>
            {authError && <div className="error-box">{authError}</div>}
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="topbar-brand">
          <div className="logo-strip">
            {HEADER_LOGOS.map((logo) => (
              <div key={logo.alt} className="logo-badge">
                <img src={logo.src} alt={logo.alt} />
                <span>{logo.caption}</span>
              </div>
            ))}
          </div>
          <div>
            <h1>TicketFlow</h1>
            <p>Система мониторинга документного обмена</p>
          </div>
        </div>
        <div className="topbar-actions">
          <span className="user-chip">
            {user.username} · {user.role}
          </span>
          <button className="ghost" onClick={onLogout} type="button">
            Выйти
          </button>
        </div>
      </header>

      <section className="page-tabs">
        <button className={currentPage === "monitor" ? "active" : ""} type="button" onClick={() => navigate("/")}>
          Мониторинг
        </button>
        {user.role === "admin" && (
          <button className={currentPage === "users" ? "active" : ""} type="button" onClick={() => navigate("/users")}>
            Пользователи
          </button>
        )}
      </section>

      {currentPage === "monitor" && (
        <>
          <section className="stats-row">
            <article>
              <small>В работе</small>
              <strong>{counters.in_progress ?? 0}</strong>
            </article>
            <article>
              <small>Ошибка</small>
              <strong>{counters.error ?? 0}</strong>
            </article>
            <article>
              <small>Успешно</small>
              <strong>{counters.success ?? 0}</strong>
            </article>
            <article>
              <small>Скрыто</small>
              <strong>{counters.hidden ?? 0}</strong>
            </article>
          </section>

          <section className="toolbar">
            <div className="tabs">
              <button className={activeTab === "tickets" ? "active" : ""} onClick={() => setActiveTab("tickets")} type="button">
                Билеты и реализации
              </button>
              <button className={activeTab === "payments" ? "active" : ""} onClick={() => setActiveTab("payments")} type="button">
                Платежки
              </button>
              <button
                className={activeTab === "archive" ? "active" : ""}
                onClick={() => {
                  setActiveTab("archive");
                  setFilters((prev) => ({ ...prev, status_preset: "all" }));
                }}
                type="button"
              >
                Архив
              </button>
            </div>

            <div className="filters">
              <input placeholder="Поиск" value={filters.q} onChange={(event) => setFilters((prev) => ({ ...prev, q: event.target.value }))} />
              <select value={filters.status_preset} onChange={(event) => setFilters((prev) => ({ ...prev, status_preset: event.target.value }))}>
                <option value="active_plus_errors">В работе + ошибки</option>
                <option value="in_progress">В работе</option>
                <option value="success">Успешные</option>
                <option value="errors">Ошибки</option>
                <option value="all">Все</option>
              </select>
              <input type="date" value={filters.date_from} onChange={(event) => setFilters((prev) => ({ ...prev, date_from: event.target.value }))} />
              <input type="date" value={filters.date_to} onChange={(event) => setFilters((prev) => ({ ...prev, date_to: event.target.value }))} />
            </div>

            <div className="results-meta">
              <span>Найдено: {filteredCount}</span>
              <span>Всего в разделе: {totalCount}</span>
              {refreshing && <span>Обновляем…</span>}
            </div>
          </section>

          {error && <div className="error-box">{error}</div>}
          {loading && <div className="loading">Обновляем список...</div>}

          {activeTab === "tickets" && listing && <TicketCards listing={listing} onOpenDocument={openDocument} />}
          {activeTab === "payments" && listing && <PaymentCards listing={listing} onOpenDocument={openDocument} />}
          {activeTab === "archive" && listing && <ArchiveCards listing={listing} />}

          <div ref={loadMoreRef} className="list-end">
            {loadingMore && <span>Подгружаем еще...</span>}
            {!loadingMore && listing?.has_more && <span>Прокрутите ниже, чтобы загрузить еще 50</span>}
            {!listing?.has_more && filteredCount > 0 && <span>Все результаты загружены</span>}
          </div>
        </>
      )}

      {currentPage === "users" && user.role === "admin" && (
        <UsersPage
          currentUser={user}
          users={adminUsers}
          loading={usersLoading}
          message={adminMessage}
          onCreate={createUser}
          onRoleChange={changeUserRole}
          onDelete={deleteUser}
        />
      )}

      <DetailModal user={user} detail={detail} loading={detailLoading} onClose={() => setDetail(null)} onHide={hideDocument} onUnhide={unhideDocument} />
    </main>
  );
}
