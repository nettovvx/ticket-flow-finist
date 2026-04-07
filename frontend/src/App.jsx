import { useEffect, useMemo, useState } from "react";

const INITIAL_FILTERS = {
  q: "",
  view: "active",
  status_filter: "",
  date_from: "",
  date_to: "",
};

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

function buildQuery(filters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

function formatDate(value) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("ru-RU");
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

function TicketCards({ listing, onOpenDocument }) {
  const ticketCases = Array.isArray(listing?.ticket_cases) ? listing.ticket_cases : [];
  const orphanRealizations = Array.isArray(listing?.orphan_realizations) ? listing.orphan_realizations : [];

  return (
    <section className="cards-grid">
      {ticketCases.map((caseItem) => (
        <article key={caseItem.ticket.id} className="card">
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
      ))}

      {orphanRealizations.map((item) => (
        <article key={item.realization.id} className="card orphan">
          <HeaderBlock
            title={item.realization.payload?.mom_number || item.realization.title || item.realization.file_name}
            subtitle={item.realization.payload?.client_name || "Контрагент не найден"}
            right={<StatusPill status={item.realization.status} />}
          />
          <div className="row-actions">
            <small>PNR: {item.realization.payload?.pnr || "—"}</small>
            <button className="ghost" onClick={() => onOpenDocument(item.realization.id)} type="button">
              Открыть
            </button>
          </div>
        </article>
      ))}
    </section>
  );
}

function PaymentCards({ listing, onOpenDocument }) {
  const rows = Array.isArray(listing?.rows) ? listing.rows : [];
  return (
    <section className="cards-grid">
      {rows.map((row) => (
        <article key={row.document.id} className="card">
          <HeaderBlock
            title={row.document.title || row.document.file_name}
            subtitle={`${row.document.payload?.payment_number || "без номера"} · ${row.document.payload?.client_name || "без контрагента"}`}
            right={<StatusPill status={row.document.status} />}
          />
          <div className="row-actions">
            <small>
              MOM: {row.document.payload?.mom_number || "—"} · Сумма: {row.document.payload?.amount ?? "—"}{" "}
              {row.document.payload?.currency || ""}
            </small>
            <button className="ghost" onClick={() => onOpenDocument(row.document.id)} type="button">
              Детали
            </button>
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

              <select
                value={item.role}
                onChange={(event) => onRoleChange(item.id, event.target.value)}
                disabled={busyUserId === item.id}
              >
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
  const [error, setError] = useState("");

  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [adminUsers, setAdminUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [adminMessage, setAdminMessage] = useState("");

  const currentPage = getPathPage(pagePath, user?.role);
  const counters = useMemo(() => listing?.counters ?? {}, [listing]);

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

  useEffect(() => {
    if (!user || currentPage !== "monitor") {
      return;
    }

    const endpoint = activeTab === "tickets" ? "/api/documents/tickets" : "/api/documents/payments";
    setLoading(true);
    setError("");
    setListing(null);

    api(`${endpoint}${buildQuery(filters)}`)
      .then((data) => setListing(data))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [user, currentPage, activeTab, filters]);

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
      .catch((e) => setAdminMessage(e.message))
      .finally(() => setUsersLoading(false));
  }, [user, currentPage]);

  async function refreshCurrentList() {
    if (currentPage !== "monitor") {
      return;
    }
    const endpoint = activeTab === "tickets" ? "/api/documents/tickets" : "/api/documents/payments";
    const data = await api(`${endpoint}${buildQuery(filters)}`);
    setListing(data);
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
    } catch (e) {
      setAuthError(e.message);
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
    } catch (e) {
      setError(e.message);
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
    } catch (e) {
      setAdminMessage(e.message);
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
    } catch (e) {
      setAdminMessage(e.message);
    }
  }

  async function deleteUser(userId) {
    if (window.confirm("Удалить пользователя?")) {
      try {
        await api(`/api/admin/users/${userId}`, { method: "DELETE" });
        setAdminUsers((prev) => prev.filter((item) => item.id !== userId));
        setAdminMessage("Пользователь удален");
      } catch (e) {
        setAdminMessage(e.message);
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
              <input
                value={login.username}
                onChange={(event) => setLogin((prev) => ({ ...prev, username: event.target.value }))}
                required
              />
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
        <div>
          <h1>TicketFlow</h1>
          <p>Система мониторинга документного обмена</p>
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
            </div>
            <div className="filters">
              <input
                placeholder="Поиск"
                value={filters.q}
                onChange={(event) => setFilters((prev) => ({ ...prev, q: event.target.value }))}
              />
              <select value={filters.view} onChange={(event) => setFilters((prev) => ({ ...prev, view: event.target.value }))}>
                <option value="active">В работе + ошибки</option>
                <option value="errors">Только ошибки</option>
                <option value="success">Только успешные</option>
                <option value="hidden">Скрытые</option>
                <option value="all">Все</option>
              </select>
              <select
                value={filters.status_filter}
                onChange={(event) => setFilters((prev) => ({ ...prev, status_filter: event.target.value }))}
              >
                <option value="">Все статусы</option>
                <option value="in_progress">В работе</option>
                <option value="error">Ошибка</option>
                <option value="success">Успешно</option>
              </select>
              <input
                type="date"
                value={filters.date_from}
                onChange={(event) => setFilters((prev) => ({ ...prev, date_from: event.target.value }))}
              />
              <input
                type="date"
                value={filters.date_to}
                onChange={(event) => setFilters((prev) => ({ ...prev, date_to: event.target.value }))}
              />
            </div>
          </section>

          {error && <div className="error-box">{error}</div>}
          {loading && <div className="loading">Обновляем список...</div>}

          {activeTab === "tickets" && listing && <TicketCards listing={listing} onOpenDocument={openDocument} />}
          {activeTab === "payments" && listing && <PaymentCards listing={listing} onOpenDocument={openDocument} />}
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

      <DetailModal
        user={user}
        detail={detail}
        loading={detailLoading}
        onClose={() => setDetail(null)}
        onHide={hideDocument}
        onUnhide={unhideDocument}
      />
    </main>
  );
}
