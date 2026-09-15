const STATUS_LABELS = {
  working: "Работает",
  needs_repair: "Требует ремонта",
  stopped: "Остановлено",
  maintenance: "На обслуживании",
};

if (!API.token()) {
  window.location.href = "/";
}

document.getElementById("whoami").textContent =
  `${API.fullName() || ""} (${API.role() || ""})`;

document.getElementById("logoutBtn").addEventListener("click", () => {
  API.clearSession();
  window.location.href = "/";
});

// --- вкладки ---
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll("section[id^='tab-']").forEach((s) => s.classList.add("hidden"));
    document.getElementById(`tab-${btn.dataset.tab}`).classList.remove("hidden");
  });
});

async function loadSummary() {
  const s = await API.get("/api/dashboard/summary");
  const grid = document.getElementById("statsGrid");
  grid.innerHTML = `
    <div class="stat"><div class="num">${s.total_equipment}</div><div class="label">Всего оборудования</div></div>
    <div class="stat ok"><div class="num">${s.working}</div><div class="label">Работает</div></div>
    <div class="stat warn"><div class="num">${s.needs_repair}</div><div class="label">Требует ремонта</div></div>
    <div class="stat danger"><div class="num">${s.stopped}</div><div class="label">Остановлено</div></div>
    <div class="stat"><div class="num">${s.open_incidents}</div><div class="label">Открытых инцидентов</div></div>
    <div class="stat danger"><div class="num">${s.critical_open_incidents}</div><div class="label">Критичных</div></div>
  `;
}

async function loadEquipment() {
  const items = await API.get("/api/equipment");
  const grid = document.getElementById("equipmentGrid");
  grid.innerHTML = items.map((e) => `
    <div class="equipment-card">
      <div class="name">${e.name}</div>
      <div class="meta">${e.workshop || "—"} · ${e.equipment_type || "—"}</div>
      <span class="badge ${e.status}">${STATUS_LABELS[e.status] || e.status}</span>
    </div>
  `).join("") || "<p style='color:var(--text-dim)'>Оборудование пока не добавлено.</p>";
}

async function loadIncidents() {
  const items = await API.get("/api/incidents");
  const body = document.getElementById("incidentsBody");
  body.innerHTML = items.map((i) => `
    <tr>
      <td>#${i.id}</td>
      <td>${i.equipment_id}</td>
      <td>${i.description}</td>
      <td>${i.severity}</td>
      <td>${i.status}</td>
      <td>${new Date(i.created_at).toLocaleString("ru-RU")}</td>
      <td>${i.status !== "resolved" ? `<button data-id="${i.id}" class="resolve-btn secondary">Закрыть</button>` : ""}</td>
    </tr>
  `).join("") || "<tr><td colspan='7' style='color:var(--text-dim)'>Инцидентов нет.</td></tr>";

  body.querySelectorAll(".resolve-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await API.post(`/api/incidents/${btn.dataset.id}/resolve`, {});
      await Promise.all([loadIncidents(), loadSummary(), loadEquipment()]);
    });
  });
}

async function loadWorkers() {
  const [workers, incidents] = await Promise.all([
    API.get("/api/workers"),
    API.get("/api/incidents?status_filter=open"),
  ]);
  const body = document.getElementById("workersBody");
  body.innerHTML = workers.map((w) => {
    const openCount = incidents.filter((i) => i.assigned_to_id === w.id).length;
    return `
      <tr>
        <td>${w.full_name}</td>
        <td>${w.position || "—"}</td>
        <td>${w.workshop || "—"}</td>
        <td>${openCount}</td>
        <td>${w.is_active ? "Активен" : "Уволен"}</td>
      </tr>
    `;
  }).join("") || "<tr><td colspan='5' style='color:var(--text-dim)'>Сотрудников пока нет.</td></tr>";
}

async function loadAll() {
  try {
    await Promise.all([loadSummary(), loadEquipment(), loadIncidents(), loadWorkers()]);
  } catch (err) {
    console.error(err);
  }
}

loadAll();
// автообновление каждые 30 секунд — чтобы данные всегда были свежими
setInterval(loadAll, 30000);
