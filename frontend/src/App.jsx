import { useEffect, useMemo, useRef, useState } from "react";
import iconAccounts from "./assets/icons/accounts.svg";
import iconArchive from "./assets/icons/archive.svg";
import iconClose from "./assets/icons/close.svg";
import iconPayments from "./assets/icons/payments.svg";
import iconSettings from "./assets/icons/settings.svg";
import iconTickets from "./assets/icons/tickets.svg";

const PAGE_SIZE = 50;
const AUTO_REFRESH_MS = 15000;

const INITIAL_FILTERS = {
  q: "",
  status_preset: "active_plus_errors",
  date_from: "",
  date_to: "",
};

const HEADER_LOGOS = [
  { src: "/logo/hightek.png", alt: "Hightek" },
  { src: "/logo/nettovvx-studio.png", alt: "Nettovvx Studio" },
  { src: "/logo/finist.png", alt: "Finist" },
];

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

function eventStatus(document, stepCode) {
  const events = Array.isArray(document?.events) ? document.events : [];
  const statuses = events.filter((event) => event.step_code === stepCode).map((event) => event.status);
  if (statuses.length === 0) {
    return "pending";
  }
  if (statuses.includes("error")) {
    return "error";
  }
  if (statuses.includes("success")) {
    return "success";
  }
  if (statuses.includes("in_progress")) {
    return "in_progress";
  }
  return statuses[statuses.length - 1] || "pending";
}

function eventOccurredAt(document, stepCode) {
  const events = Array.isArray(document?.events) ? document.events : [];
  const timestamps = events
    .filter((event) => event.step_code === stepCode && event.occurred_at)
    .map((event) => new Date(event.occurred_at).getTime())
    .filter((value) => Number.isFinite(value));
  if (timestamps.length === 0) {
    return null;
  }
  return new Date(Math.max(...timestamps)).toISOString();
}

function formatDelta(seconds) {
  if (seconds === null || seconds === undefined) {
    return null;
  }
  if (seconds < 60) {
    return `${seconds}с`;
  }
  const minutes = Math.floor(seconds / 60);
  const sec = seconds % 60;
  if (minutes < 60) {
    return `${minutes}м ${sec}с`;
  }
  const hours = Math.floor(minutes / 60);
  const min = minutes % 60;
  if (hours < 24) {
    return `${hours}ч ${min}м ${sec}с`;
  }
  const days = Math.floor(hours / 24);
  const hrs = hours % 24;
  return `${days}д ${hrs}ч ${min}м`;
}

function withStepDeltas(steps) {
  let previousMs = null;
  return steps.map((step) => {
    let deltaSeconds = null;
    const currentMs = step.occurred_at ? new Date(step.occurred_at).getTime() : null;
    if (Number.isFinite(previousMs) && Number.isFinite(currentMs)) {
      const raw = Math.floor((currentMs - previousMs) / 1000);
      if (raw >= 0) {
        deltaSeconds = raw;
      }
    }
    if (Number.isFinite(currentMs)) {
      previousMs = currentMs;
    }
    return {
      ...step,
      delta_seconds: deltaSeconds,
      delta_human: formatDelta(deltaSeconds),
    };
  });
}

function paymentFlowSteps(document) {
  return withStepDeltas([
    {
      code: "payment_received_from_1c",
      label: "Платежка сформирована",
      status: eventStatus(document, "payment_received_from_1c"),
      occurred_at: eventOccurredAt(document, "payment_received_from_1c"),
    },
    {
      code: "payment_copied_to_ftp",
      label: "Платежка перемещена на FTP",
      status: eventStatus(document, "payment_copied_to_ftp"),
      occurred_at: eventOccurredAt(document, "payment_copied_to_ftp"),
    },
    {
      code: "payment_seen_by_mom",
      label: "MOM обработал платежку",
      status: eventStatus(document, "payment_seen_by_mom"),
      occurred_at: eventOccurredAt(document, "payment_seen_by_mom"),
    },
  ]);
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

function IconLabel({ icon, alt, children }) {
  return (
    <span className="tab-button-content">
      <img src={icon} alt={alt} className="icon-inline" />
      <span>{children}</span>
    </span>
  );
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
        const steps = paymentFlowSteps(row.document);
        return (
          <article key={row.document.id} className="card animated-card" style={{ "--stagger": index }}>
            <HeaderBlock
              title={row.document.title || row.document.file_name}
              subtitle={row.document.file_name}
              right={<StatusPill status={row.document.status} />}
            />

            <div className="steps">
              {steps.map((step) => (
                <div key={step.code} className={`step status-${step.status}`}>
                  <strong>{step.label}</strong>
                  <small>{stepMeta(step)}</small>
                </div>
              ))}
            </div>

            <div className="row-actions">
              <small>
                MOM: {row.document.payload?.mom_number || "—"} · Сумма: {row.document.payload?.amount ?? "—"}{" "}
                {row.document.payload?.currency || ""}
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
          <button className="ghost icon-button" type="button" onClick={onClose}>
            <img src={iconClose} alt="Закрыть" className="icon-inline" />
            <span>Закрыть</span>
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
        <HeaderBlock title="Создать пользователя" subtitle="Администраторская операция" />
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
                <small>
                  {item.is_active ? "active" : "inactive"} · последний вход: {formatDate(item.last_login_at)}
                </small>
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

function SettingsModal({
  user,
  open,
  activeTab,
  setActiveTab,
  users,
  loading,
  message,
  onClose,
  onCreate,
  onRoleChange,
  onDelete,
}) {
  if (!open) {
    return null;
  }

  const tabs = [{ id: "accounts", label: "Управление учетными записями", icon: iconAccounts }];

  return (
    <div className="modal-backdrop settings-backdrop" onClick={onClose}>
      <section className="modal-card settings-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-top">
          <div className="modal-heading-icon">
            <img src={iconSettings} alt="Настройки" className="icon-inline" />
            <div>
              <h2>Настройки</h2>
              <p>Системные параметры и управление доступами</p>
            </div>
          </div>
          <button className="ghost icon-button" type="button" onClick={onClose}>
            <img src={iconClose} alt="Закрыть" className="icon-inline" />
            <span>Закрыть</span>
          </button>
        </div>

        <div className="settings-tabs" role="tablist" aria-label="Вкладки настроек">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={activeTab === tab.id ? "active" : ""}
              onClick={() => setActiveTab(tab.id)}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
            >
              <IconLabel icon={tab.icon} alt={tab.label}>
                {tab.label}
              </IconLabel>
            </button>
          ))}
        </div>

        <div className="settings-body">
          {user.role === "admin" && activeTab === "accounts" && (
            <UsersPage
              currentUser={user}
              users={users}
              loading={loading}
              message={message}
              onCreate={onCreate}
              onRoleChange={onRoleChange}
              onDelete={onDelete}
            />
          )}
        </div>
      </section>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");

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

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState("accounts");

  const [adminUsers, setAdminUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [adminMessage, setAdminMessage] = useState("");

  const loadMoreRef = useRef(null);
  const requestIdRef = useRef(0);

  const counters = useMemo(() => listing?.counters ?? {}, [listing]);
  const filteredCount = listing?.filtered_count ?? 0;
  const totalCount = listing?.total_count ?? 0;

  useEffect(() => {
    api("/api/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthLoading(false));
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }
    setDetail(null);
    fetchMonitorListing({ offset: 0, limit: PAGE_SIZE });
  }, [user, activeTab, filters]);

  useEffect(() => {
    if (!user) {
      return;
    }
    const intervalId = window.setInterval(() => {
      const currentLimit = Math.max(getLoadedCount(listing, activeTab), PAGE_SIZE);
      fetchMonitorListing({ offset: 0, limit: currentLimit, silent: true });
    }, AUTO_REFRESH_MS);
    return () => window.clearInterval(intervalId);
  }, [user, activeTab, filters, listing]);

  useEffect(() => {
    if (!user || !loadMoreRef.current) {
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
  }, [user, activeTab, listing, loading, loadingMore, filters]);

  useEffect(() => {
    if (!user || user.role !== "admin" || !settingsOpen || settingsTab !== "accounts") {
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
  }, [user, settingsOpen, settingsTab]);

  async function fetchMonitorListing({ offset = 0, limit = PAGE_SIZE, append = false, silent = false } = {}) {
    if (!user) {
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

  async function refreshCurrentList() {
    if (!user) {
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
    } catch (loginError) {
      setAuthError(loginError.message);
    }
  }

  async function onLogout() {
    await api("/api/auth/logout", { method: "POST" });
    setUser(null);
    setListing(null);
    setDetail(null);
    setSettingsOpen(false);
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
          <div className="brand-inline">
            <h1>TicketFlow</h1>
            <div className="logo-strip" aria-label="Логотипы партнеров">
              {HEADER_LOGOS.map((logo) => (
                <div key={logo.alt} className="logo-badge">
                  <img src={logo.src} alt={logo.alt} />
                </div>
              ))}
            </div>
          </div>
          <p>Система мониторинга документного обмена</p>
        </div>
        <div className="topbar-actions">
          <span className="user-chip">
            {user.username} · {user.role}
          </span>
          {user.role === "admin" && (
            <button
              className="ghost icon-button"
              onClick={() => {
                setSettingsTab("accounts");
                setSettingsOpen(true);
              }}
              type="button"
            >
              <img src={iconSettings} alt="Настройки" className="icon-inline" />
              <span>Настройки</span>
            </button>
          )}
          <button className="ghost" onClick={onLogout} type="button">
            Выйти
          </button>
        </div>
      </header>

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
            <IconLabel icon={iconTickets} alt="Билеты">
              Билеты и реализации
            </IconLabel>
          </button>
          <button className={activeTab === "payments" ? "active" : ""} onClick={() => setActiveTab("payments")} type="button">
            <IconLabel icon={iconPayments} alt="Платежки">
              Платежки
            </IconLabel>
          </button>
          <button
            className={activeTab === "archive" ? "active" : ""}
            onClick={() => {
              setActiveTab("archive");
              setFilters((prev) => ({ ...prev, status_preset: "all" }));
            }}
            type="button"
          >
            <IconLabel icon={iconArchive} alt="Архив">
              Архив
            </IconLabel>
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

      <DetailModal user={user} detail={detail} loading={detailLoading} onClose={() => setDetail(null)} onHide={hideDocument} onUnhide={unhideDocument} />

      <SettingsModal
        user={user}
        open={settingsOpen}
        activeTab={settingsTab}
        setActiveTab={setSettingsTab}
        users={adminUsers}
        loading={usersLoading}
        message={adminMessage}
        onClose={() => setSettingsOpen(false)}
        onCreate={createUser}
        onRoleChange={changeUserRole}
        onDelete={deleteUser}
      />
    </main>
  );
}
