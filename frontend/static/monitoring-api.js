/**
 * monitoring-api.js
 * Обёртка API для модуля мониторинга — работает независимо от основного ACAI.
 * Хранит токен под своим ключом (m_token), чтобы не конфликтовать.
 */
const MAPI = {
  _key: { token: "m_token", role: "m_role", name: "m_name" },

  token: () => localStorage.getItem("m_token"),
  role:  () => localStorage.getItem("m_role"),
  name:  () => localStorage.getItem("m_name"),

  setSession(token, role, name) {
    localStorage.setItem("m_token", token);
    localStorage.setItem("m_role", role);
    localStorage.setItem("m_name", name);
  },

  clearSession() {
    Object.values(this._key).forEach(k => localStorage.removeItem(k));
  },

  can(...roles) { return roles.includes(this.role()); },

  async req(path, opts = {}) {
    const headers = opts.headers || {};
    const t = this.token();
    if (t) headers["Authorization"] = `Bearer ${t}`;
    if (opts.body && typeof opts.body === "object") {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
      this.clearSession();
      window.location.href = "/monitoring/login";
      throw new Error("401");
    }
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.detail || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  },

  get:   (p)    => MAPI.req(p, { method: "GET" }),
  post:  (p, b) => MAPI.req(p, { method: "POST",  body: b || {} }),
  patch: (p, b) => MAPI.req(p, { method: "PATCH", body: b || {} }),

  async login(username, password) {
    const form = new URLSearchParams();
    form.set("username", username);
    form.set("password", password);
    const res = await fetch("/api/auth/login", { method: "POST", body: form });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      throw new Error(j.detail || "Неверный логин или пароль");
    }
    return res.json();
  },
};
