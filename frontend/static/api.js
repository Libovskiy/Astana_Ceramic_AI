// Простая обёртка над fetch: подставляет токен, редиректит на логин при 401.
const API = {
  base: "",

  token() {
    return localStorage.getItem("acai_token");
  },

  setSession(token, role, fullName) {
    localStorage.setItem("acai_token", token);
    localStorage.setItem("acai_role", role);
    localStorage.setItem("acai_full_name", fullName);
  },

  clearSession() {
    localStorage.removeItem("acai_token");
    localStorage.removeItem("acai_role");
    localStorage.removeItem("acai_full_name");
  },

  role() {
    return localStorage.getItem("acai_role");
  },

  fullName() {
    return localStorage.getItem("acai_full_name");
  },

  async request(path, options = {}) {
    const headers = options.headers || {};
    const token = this.token();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    if (options.body && !(options.body instanceof URLSearchParams)) {
      headers["Content-Type"] = "application/json";
    }

    const res = await fetch(this.base + path, { ...options, headers });

    if (res.status === 401) {
      this.clearSession();
      window.location.href = "/";
      throw new Error("Не авторизован");
    }
    if (!res.ok) {
      let detail = "Ошибка запроса";
      try {
        const data = await res.json();
        detail = data.detail || detail;
      } catch (e) {}
      throw new Error(detail);
    }
    if (res.status === 204) return null;
    return res.json();
  },

  get(path) {
    return this.request(path, { method: "GET" });
  },
  post(path, body) {
    return this.request(path, { method: "POST", body: JSON.stringify(body || {}) });
  },
  patch(path, body) {
    return this.request(path, { method: "PATCH", body: JSON.stringify(body || {}) });
  },

  async login(username, password) {
    const form = new URLSearchParams();
    form.set("username", username);
    form.set("password", password);
    const res = await fetch("/api/auth/login", { method: "POST", body: form });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Неверный логин или пароль");
    }
    return res.json();
  },
};
