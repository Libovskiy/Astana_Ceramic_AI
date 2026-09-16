/*
 * Переписка между людьми.
 *
 * Новые сообщения забираются опросом, как и всё остальное в системе.
 * Два разных интервала: список переписок раз в 8 секунд (там меняется
 * только счётчик непрочитанного), открытая переписка раз в 3 секунды —
 * в ней ждут ответа прямо сейчас.
 *
 * Опрос тянет только новое (after_id), поэтому длинная переписка не
 * перекачивается каждые три секунды по заводскому Wi-Fi.
 */
(function () {
"use strict";

const ROLE_LABELS = {
  admin: 'Администратор', director: 'Директор',
  chief_engineer: 'Гл. инженер', engineer: 'Инженер',
  worker: 'Рабочий', shift_supervisor: 'Мастер смены',
  chief_mechanic: 'Гл. механик', mechanic: 'Механик',
  chief_electrician: 'Гл. электрик', electrician: 'Электрик',
  analyst: 'Аналитик', technologist: 'Технолог',
  lab_technician: 'Лаборант',
};

let me = null;
let conversations = [];
let contacts = [];
let current = null;       // {id, kind, title, members}
let lastMessageId = 0;   // самое новое показанное — от него идёт опрос
let oldestMessageId = 0; // самое старое показанное — от него грузится история
let hasMore = false;     // есть ли что грузить выше
let loadingOlder = false;
let listTimer = null;
let threadTimer = null;

const $ = (id) => document.getElementById(id);


// ── Список переписок ──────────────────────────────────────

async function loadList(silent) {
  try {
    const r = await ACAI.get('/api/messenger/conversations');
    conversations = r.conversations || [];
    renderList();
  } catch (e) {
    if (!silent) $('mgItems').innerHTML = '<div class="mg-empty">Не удалось загрузить</div>';
  }
}

function renderList() {
  const q = ($('mgSearch')?.value || '').toLowerCase().trim();

  const shown = conversations.filter(c =>
    !q || (c.title || '').toLowerCase().includes(q)
  );

  if (!shown.length) {
    $('mgItems').innerHTML = conversations.length
      ? '<div class="mg-empty">Ничего не нашлось</div>'
      : '<div class="mg-empty">Пока никому не писали.<br>Нажмите ✎, чтобы начать.</div>';
    return;
  }

  $('mgItems').innerHTML = shown.map(c => {
    const last = c.last_message;
    const preview = last
      ? (last.user_id === me.id ? 'Вы: ' : '') + oneLine(last.body)
      : 'Нет сообщений';
    const active = current && current.id === c.id ? ' active' : '';
    const icon = c.kind === 'group' ? '👥' : ACAI.initials(c.title);
    const color = c.kind === 'group' ? 'var(--text-dim)' : ACAI.avatarColor(c.title);

    return `<button class="mg-item${active}" onclick="openConversation(${c.id})">
      <div class="mg-avatar" style="background:${color}">${icon}</div>
      <div class="mg-item-body">
        <div class="mg-item-top">
          <span class="mg-name">${esc(c.title)}</span>
          <span class="mg-time">${last ? ACAI.shortTime(last.created_at) : ''}</span>
        </div>
        <div class="mg-last">${esc(preview)}</div>
      </div>
      ${c.unread > 0 ? `<span class="mg-unread">${c.unread}</span>` : ''}
    </button>`;
  }).join('');
}


// ── Открытая переписка ────────────────────────────────────

async function openConversation(id) {
  if (current && current.id === id) { showThread(); return; }

  current = { id };
  lastMessageId = 0;
  oldestMessageId = 0;
  hasMore = false;
  $('mgMessages').innerHTML = '<div class="mg-empty">Загрузка…</div>';
  $('mgHead').style.display = 'flex';
  $('mgComposer').style.display = 'flex';
  showThread();

  await pullMessages(true);
  startThreadPolling();
}

async function pullMessages(first) {
  if (!current) return;

  let data;
  try {
    const query = lastMessageId ? `after_id=${lastMessageId}` : 'limit=50';
    data = await ACAI.get(`/api/messenger/conversations/${current.id}/messages?${query}`);
  } catch {
    return;
  }

  current = Object.assign({}, current, data.conversation);
  renderHead();

  const list = data.messages || [];

  if (first) $('mgMessages').innerHTML = '';

  if (!list.length) {
    if (first) $('mgMessages').innerHTML = '<div class="mg-empty">Сообщений пока нет — напишите первым</div>';
    return;
  }

  // Прокручиваем вниз, только если человек и так был внизу: иначе
  // чтение старой переписки будет дёргать к последнему сообщению.
  const box = $('mgMessages');
  const wasAtBottom = first || (box.scrollHeight - box.scrollTop - box.clientHeight < 80);

  if (first) box.innerHTML = '';

  list.forEach(m => {
    box.insertAdjacentHTML('beforeend', bubble(m));
    lastMessageId = Math.max(lastMessageId, m.id);
    if (!oldestMessageId || m.id < oldestMessageId) oldestMessageId = m.id;
  });

  if (first) {
    hasMore = !!data.has_more;
    updateOlderMarker();
  }

  if (wasAtBottom) box.scrollTop = box.scrollHeight;

  await markRead();
}

// ── История: подгрузка при прокрутке вверх ────────────────
//
// Переписка хранится целиком и никогда не обрезается. Открываем
// хвостом в 50 сообщений, остальное догружаем, когда человек листает
// вверх — как в привычных мессенджерах. Иначе открытие годовой ленты
// на телефоне занимало бы минуту.

function updateOlderMarker() {
  const box = $('mgMessages');
  let marker = document.getElementById('mgOlder');

  if (!hasMore) { marker?.remove(); return; }

  if (!marker) {
    marker = document.createElement('div');
    marker.id = 'mgOlder';
    marker.className = 'mg-older';
    marker.textContent = 'Показать более ранние';
    marker.onclick = loadOlder;
    box.insertBefore(marker, box.firstChild);
  }
}

async function loadOlder() {
  if (!current || !hasMore || loadingOlder || !oldestMessageId) return;

  loadingOlder = true;

  const box = $('mgMessages');
  const marker = document.getElementById('mgOlder');
  if (marker) marker.textContent = 'Загружаю…';

  // Запоминаем, насколько лента длиннее видимой части: после вставки
  // сверху восстановим положение, чтобы экран не прыгнул.
  const before = box.scrollHeight - box.scrollTop;

  try {
    const data = await ACAI.get(
      `/api/messenger/conversations/${current.id}/messages?before_id=${oldestMessageId}&limit=50`
    );

    const list = data.messages || [];

    // Вставляем снизу вверх, каждое перед предыдущим — так порядок
    // сохраняется без перерисовки всей ленты.
    let anchorNode = marker ? marker.nextSibling : box.firstChild;

    list.forEach(m => {
      const wrap = document.createElement('div');
      wrap.innerHTML = bubble(m);
      const node = wrap.firstElementChild;
      box.insertBefore(node, anchorNode);
      anchorNode = node.nextSibling;
      if (!oldestMessageId || m.id < oldestMessageId) oldestMessageId = m.id;
    });

    hasMore = !!data.has_more;
    box.scrollTop = box.scrollHeight - before;

    if (marker) {
      if (hasMore) marker.textContent = 'Показать более ранние';
      else marker.remove();
    }

  } catch {
    if (marker) marker.textContent = 'Не загрузилось, нажмите ещё раз';
  } finally {
    loadingOlder = false;
  }
}

function renderHead() {
  $('mgHeadTitle').textContent = current.title || '';
  $('mgHeadAvatar').textContent = current.kind === 'group' ? '👥' : ACAI.initials(current.title || '');
  $('mgHeadAvatar').style.background = current.kind === 'group'
    ? 'var(--text-dim)' : ACAI.avatarColor(current.title || '');

  if (current.kind === 'group') {
    $('mgHeadSub').textContent = `${current.members_count} участников`;
    $('mgGroupBtn').style.display = '';
  } else {
    const other = (current.members || []).find(m => m.id !== me.id);
    $('mgHeadSub').textContent = other ? (ROLE_LABELS[other.role] || other.role) : '';
    $('mgGroupBtn').style.display = 'none';
  }
}

function humanSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return n + ' Б';
  if (n < 1024 * 1024) return Math.round(n / 1024) + ' КБ';
  return (n / 1024 / 1024).toFixed(1).replace('.0', '') + ' МБ';
}

function fileIcon(name) {
  const ext = String(name || '').split('.').pop().toLowerCase();
  if (['pdf'].includes(ext)) return '📕';
  if (['doc', 'docx', 'rtf', 'odt'].includes(ext)) return '📘';
  if (['xls', 'xlsx', 'csv', 'ods'].includes(ext)) return '📗';
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext)) return '🗜️';
  if (['dwg', 'dxf'].includes(ext)) return '📐';
  return '📎';
}

function attachmentHtml(a) {
  if (!a) return '';

  if (a.kind === 'image') {
    // Показываем уменьшенную копию, по нажатию открывается оригинал.
    // Пропорции задаём заранее, чтобы лента не прыгала при загрузке.
    const ratio = (a.width && a.height) ? `aspect-ratio:${a.width}/${a.height};` : '';
    return `<a class="mg-photo" href="${a.url}" target="_blank" rel="noopener"
              title="Открыть оригинал">
      <img src="${a.has_preview ? a.preview_url : a.url}" alt="${esc(a.original_name)}"
           loading="lazy" style="${ratio}">
    </a>`;
  }

  if (a.kind === 'video') {
    return `<video class="mg-video" controls preload="metadata" src="${a.url}"></video>`;
  }

  return `<a class="mg-file" href="${a.url}" download>
    <span class="mg-file-icon">${fileIcon(a.original_name)}</span>
    <span class="mg-file-body">
      <span class="mg-file-name">${esc(a.original_name)}</span>
      <span class="mg-file-size">${humanSize(a.size_bytes)}</span>
    </span>
    <span class="mg-file-dl">↓</span>
  </a>`;
}

function bubble(m) {
  // Признак «моё» считает сервер — он знает, кто прислал запрос.
  // Сверка по id оставлена запасным вариантом.
  const mine = (m.mine !== undefined) ? m.mine : (m.user_id === me.id);
  const who = (!mine && current.kind === 'group')
    ? `<div class="mg-who">${esc(m.full_name || m.username)}</div>` : '';
  const del = (mine && !m.deleted_at)
    ? `<button class="mg-del" onclick="removeMessage(${m.id})" title="Удалить">✕</button>` : '';

  const media = attachmentHtml(m.attachment);

  // У файла подпись не обязательна — чаще фото отправляют молча,
  // и пустой абзац под ним выглядел бы как опечатка.
  const text = m.body ? `<div class="mg-text">${esc(m.body)}</div>` : '';

  return `<div class="mg-row ${mine ? 'mine' : ''}" data-id="${m.id}">
    <div class="mg-bubble${m.deleted_at ? ' deleted' : ''}${media ? ' has-media' : ''}">
      ${who}
      ${media}
      ${text}
      <div class="mg-meta">${ACAI.shortTime(m.created_at)}${del}</div>
    </div>
  </div>`;
}

// Доскроллил почти до верха — подгружаем, не дожидаясь нажатия.
function onScroll() {
  const box = $('mgMessages');
  if (box.scrollTop < 120) loadOlder();
}

async function markRead() {
  if (!current || !lastMessageId) return;
  try {
    await ACAI.post(`/api/messenger/conversations/${current.id}/read`, { message_id: lastMessageId });
    const c = conversations.find(x => x.id === current.id);
    if (c) { c.unread = 0; renderList(); }
  } catch {}
}

async function send() {
  const input = $('mgInput');
  const text = (input.value || '').trim();
  if (!text || !current) return;

  input.value = '';
  input.style.height = 'auto';

  try {
    const r = await ACAI.post(`/api/messenger/conversations/${current.id}/messages`, { text });
    const box = $('mgMessages');
    if (box.querySelector('.mg-empty')) box.innerHTML = '';
    box.insertAdjacentHTML('beforeend', bubble(r.message));
    lastMessageId = Math.max(lastMessageId, r.message.id);
    box.scrollTop = box.scrollHeight;
    loadList(true);
  } catch (e) {
    // Текст возвращаем в поле: потерять набранное сообщение обиднее,
    // чем увидеть ошибку.
    input.value = text;
    ACAI.toast(e.message || 'Не отправилось', 'danger');
  }
}

// ── Отправка файлов ───────────────────────────────────────

const MAX_FILE_BYTES = 50 * 1024 * 1024;

function pickFile() {
  if (!current) return;
  $('mgFile').click();
}

async function onFilePicked(input) {
  const files = [...(input.files || [])];
  input.value = '';   // иначе тот же файл второй раз не выберется

  // Подпись из поля ввода уходит с ПЕРВЫМ файлом: писать её к каждому
  // из пяти снимков человек не собирался.
  let caption = ($('mgInput').value || '').trim();

  for (const file of files) {
    if (file.size > MAX_FILE_BYTES) {
      ACAI.toast(`«${file.name}» больше 50 МБ`, 'danger');
      continue;
    }
    await uploadFile(file, caption);
    caption = '';
  }

  $('mgInput').value = '';
  $('mgInput').style.height = 'auto';
}

function uploadFile(file, caption) {
  return new Promise((resolve) => {
    const box = $('mgMessages');
    if (box.querySelector('.mg-empty')) box.innerHTML = '';

    // Пока файл идёт — временная плашка с полосой. По заводскому
    // Wi-Fi 50 МБ едут заметно, и без неё непонятно, работает ли.
    const holder = document.createElement('div');
    holder.className = 'mg-row mine';
    holder.innerHTML = `<div class="mg-bubble mg-uploading">
      <div class="mg-up-name">${esc(file.name)}</div>
      <div class="mg-up-bar"><div class="mg-up-fill"></div></div>
      <div class="mg-up-pct">0%</div>
    </div>`;
    box.appendChild(holder);
    box.scrollTop = box.scrollHeight;

    const fill = holder.querySelector('.mg-up-fill');
    const pct = holder.querySelector('.mg-up-pct');

    const form = new FormData();
    form.append('file', file);
    form.append('caption', caption || '');

    // XMLHttpRequest, а не fetch: только он сообщает ход отправки.
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/messenger/conversations/${current.id}/attachments`);
    xhr.withCredentials = true;

    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const p = Math.round(e.loaded * 100 / e.total);
      fill.style.width = p + '%';
      pct.textContent = p + '%';
    };

    xhr.onload = () => {
      holder.remove();
      if (xhr.status === 200) {
        try {
          const d = JSON.parse(xhr.responseText);
          box.insertAdjacentHTML('beforeend', bubble(d.message));
          lastMessageId = Math.max(lastMessageId, d.message.id);
          box.scrollTop = box.scrollHeight;
          loadList(true);
        } catch { ACAI.toast('Странный ответ сервера', 'danger'); }
      } else {
        let detail = 'Не отправилось';
        try { detail = JSON.parse(xhr.responseText).detail || detail; } catch {}
        ACAI.toast(detail, 'danger');
      }
      resolve();
    };

    xhr.onerror = () => {
      holder.remove();
      ACAI.toast('Обрыв связи при отправке', 'danger');
      resolve();
    };

    xhr.send(form);
  });
}

async function removeMessage(id) {
  if (!confirm('Удалить сообщение? Собеседник увидит пометку «сообщение удалено».')) return;
  try {
    const r = await fetch(`/api/messenger/messages/${id}`, { method: 'DELETE', credentials: 'include' });
    if (!r.ok) throw new Error();
    const row = document.querySelector(`.mg-row[data-id="${id}"] .mg-bubble`);
    if (row) {
      row.classList.add('deleted');
      row.querySelector('.mg-text').textContent = 'сообщение удалено';
      row.querySelector('.mg-del')?.remove();
    }
    loadList(true);
  } catch {
    ACAI.toast('Не удалось удалить', 'danger');
  }
}


// ── Новая переписка ───────────────────────────────────────

function openNew() {
  const people = contacts.map(c => personRow(c)).join('');

  ACAI.showModal(`
    <h3>Кому написать</h3>
    <input class="input" id="mgPick" placeholder="🔍 Имя или должность"
           style="width:100%;margin:10px 0" oninput="filterPeople()">
    <div class="mg-picker" id="mgPeople">${people || '<div class="mg-empty">Некому писать</div>'}</div>
    <div class="modal-foot">
      <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
      <button class="btn primary" onclick="openGroupForm()">Собрать группу</button>
    </div>
  `);
}

function personRow(c, picked) {
  return `<button class="mg-person${picked ? ' picked' : ''}" data-id="${c.id}"
            data-search="${esc((c.full_name || '') + ' ' + (ROLE_LABELS[c.role] || c.role))}"
            onclick="startDm(${c.id})">
    <div class="mg-avatar" style="background:${ACAI.avatarColor(c.full_name)};width:32px;height:32px;font-size:12px">
      ${ACAI.initials(c.full_name)}
    </div>
    <div style="flex:1;min-width:0">
      <div class="mg-name">${esc(c.full_name || c.username)}</div>
      <div class="mg-person-role">${esc(ROLE_LABELS[c.role] || c.role)}</div>
    </div>
  </button>`;
}

function filterPeople() {
  const q = ($('mgPick')?.value || '').toLowerCase().trim();
  document.querySelectorAll('#mgPeople .mg-person').forEach(el => {
    el.style.display = !q || (el.dataset.search || '').toLowerCase().includes(q) ? '' : 'none';
  });
}

async function startDm(userId) {
  try {
    const r = await ACAI.post('/api/messenger/conversations/dm', { user_id: userId });
    ACAI.closeModal();
    await loadList(true);
    openConversation(r.conversation_id);
  } catch (e) {
    ACAI.toast(e.message || 'Не получилось', 'danger');
  }
}

function openGroupForm() {
  const people = contacts.map(c => `
    <button class="mg-person" data-id="${c.id}"
            data-search="${esc((c.full_name || '') + ' ' + (ROLE_LABELS[c.role] || c.role))}"
            onclick="togglePick(this)">
      <div class="mg-avatar" style="background:${ACAI.avatarColor(c.full_name)};width:32px;height:32px;font-size:12px">
        ${ACAI.initials(c.full_name)}
      </div>
      <div style="flex:1;min-width:0">
        <div class="mg-name">${esc(c.full_name || c.username)}</div>
        <div class="mg-person-role">${esc(ROLE_LABELS[c.role] || c.role)}</div>
      </div>
      <span class="mg-tick">＋</span>
    </button>`).join('');

  ACAI.showModal(`
    <h3>Новая группа</h3>
    <div class="field" style="margin:10px 0">
      <label>Название</label>
      <input class="input" id="mgGroupTitle" placeholder="Например: Смена А — упаковка" style="width:100%">
    </div>
    <input class="input" id="mgPick" placeholder="🔍 Кого добавить"
           style="width:100%;margin-bottom:8px" oninput="filterPeople()">
    <div class="mg-picker" id="mgPeople">${people}</div>
    <div id="mgGroupErr" style="color:var(--danger);font-size:12px;min-height:16px;margin-top:6px"></div>
    <div class="modal-foot">
      <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
      <button class="btn primary" onclick="submitGroup()">Создать</button>
    </div>
  `);
}

function togglePick(el) {
  el.classList.toggle('picked');
  el.querySelector('.mg-tick').textContent = el.classList.contains('picked') ? '✓' : '＋';
}

async function submitGroup() {
  const title = ($('mgGroupTitle')?.value || '').trim();
  const ids = [...document.querySelectorAll('#mgPeople .mg-person.picked')]
    .map(el => parseInt(el.dataset.id, 10));

  const err = $('mgGroupErr');

  if (!title) { err.textContent = 'Напишите название группы'; return; }
  if (!ids.length) { err.textContent = 'Отметьте хотя бы одного человека'; return; }

  try {
    const r = await ACAI.post('/api/messenger/conversations/group', { title, member_ids: ids });
    ACAI.closeModal();
    await loadList(true);
    openConversation(r.conversation_id);
  } catch (e) {
    err.textContent = e.message || 'Не получилось';
  }
}


// ── Участники группы ──────────────────────────────────────

function openGroupSettings() {
  if (!current || current.kind !== 'group') return;

  const inGroup = new Set((current.members || []).map(m => m.id));

  const rows = (current.members || []).map(m => `
    <div class="mg-person" style="cursor:default">
      <div class="mg-avatar" style="background:${ACAI.avatarColor(m.full_name)};width:32px;height:32px;font-size:12px">
        ${ACAI.initials(m.full_name)}
      </div>
      <div style="flex:1;min-width:0">
        <div class="mg-name">${esc(m.full_name || m.username)}${m.id === me.id ? ' (вы)' : ''}</div>
        <div class="mg-person-role">${esc(ROLE_LABELS[m.role] || m.role)}${m.is_active ? '' : ' · доступ закрыт'}</div>
      </div>
      ${m.id !== me.id ? `<button class="btn secondary sm" onclick="kick(${m.id})">Убрать</button>` : ''}
    </div>`).join('');

  const canAdd = contacts.filter(c => !inGroup.has(c.id)).map(c => `
    <button class="mg-person" data-id="${c.id}" onclick="invite(${c.id})">
      <div class="mg-avatar" style="background:${ACAI.avatarColor(c.full_name)};width:32px;height:32px;font-size:12px">
        ${ACAI.initials(c.full_name)}
      </div>
      <div style="flex:1;min-width:0">
        <div class="mg-name">${esc(c.full_name || c.username)}</div>
        <div class="mg-person-role">${esc(ROLE_LABELS[c.role] || c.role)}</div>
      </div>
      <span style="opacity:.6">＋</span>
    </button>`).join('');

  ACAI.showModal(`
    <h3>${esc(current.title)}</h3>
    <div class="field" style="margin:10px 0">
      <label>Название</label>
      <div style="display:flex;gap:8px">
        <input class="input" id="mgNewTitle" value="${esc(current.title)}" style="flex:1">
        <button class="btn secondary sm" onclick="saveTitle()">Сохранить</button>
      </div>
    </div>
    <div style="font-size:12px;color:var(--text-dim);margin:12px 0 6px">Участники</div>
    <div class="mg-picker">${rows}</div>
    <div style="font-size:12px;color:var(--text-dim);margin:12px 0 6px">Добавить</div>
    <div class="mg-picker">${canAdd || '<div class="mg-empty">Все уже здесь</div>'}</div>
    <div class="modal-foot">
      <button class="btn danger" onclick="leaveGroup()">Выйти из группы</button>
      <button class="btn secondary" onclick="ACAI.closeModal()">Закрыть</button>
    </div>
  `);
}

async function invite(userId) {
  try {
    const r = await ACAI.post(`/api/messenger/conversations/${current.id}/members`, { user_ids: [userId] });
    current.members = r.members;
    current.members_count = r.members.length;
    renderHead();
    openGroupSettings();
  } catch (e) { ACAI.toast(e.message || 'Не получилось', 'danger'); }
}

async function kick(userId) {
  if (!confirm('Убрать человека из группы?')) return;
  try {
    const r = await fetch(`/api/messenger/conversations/${current.id}/members/${userId}`,
                          { method: 'DELETE', credentials: 'include' });
    if (!r.ok) throw new Error();
    const d = await r.json();
    current.members = d.members;
    current.members_count = d.members.length;
    renderHead();
    openGroupSettings();
  } catch { ACAI.toast('Не удалось убрать', 'danger'); }
}

async function saveTitle() {
  const title = ($('mgNewTitle')?.value || '').trim();
  try {
    const r = await fetch(`/api/messenger/conversations/${current.id}/title`, {
      method: 'PUT', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '');
    current.title = d.title;
    renderHead();
    ACAI.toast('Название изменено');
    loadList(true);
  } catch (e) { ACAI.toast(e.message || 'Не получилось', 'danger'); }
}

async function leaveGroup() {
  if (!confirm('Выйти из группы? Переписка пропадёт из списка.')) return;
  try {
    await ACAI.post(`/api/messenger/conversations/${current.id}/leave`, {});
    ACAI.closeModal();
    current = null;
    stopThreadPolling();
    $('mgHead').style.display = 'none';
    $('mgComposer').style.display = 'none';
    $('mgMessages').innerHTML = '<div class="mg-empty">Выберите переписку слева</div>';
    showList();
    loadList();
  } catch (e) { ACAI.toast(e.message || 'Не получилось', 'danger'); }
}


// ── Переключение экранов на телефоне ──────────────────────

// Высота переписки на телефоне: от низа шапки до верха нижней
// панели. Считаем по факту, а не константой — шапка переносится на
// вторую строку, а у панели свой запас под полосу «домой».
function fitHeight() {
  const wrap = document.querySelector('.mg-wrap');
  if (!wrap) return;

  if (window.innerWidth > 768) {
    document.documentElement.style.removeProperty('--mg-height');
    return;
  }

  const top = wrap.getBoundingClientRect().top;
  const nav = document.querySelector('.bottom-nav');
  const navHeight = nav ? nav.getBoundingClientRect().height : 0;
  const height = Math.max(240, window.innerHeight - top - navHeight);

  document.documentElement.style.setProperty('--mg-height', height + 'px');
}

window.addEventListener('resize', fitHeight);
window.addEventListener('orientationchange', () => setTimeout(fitHeight, 200));

function showThread() { document.body.dataset.screen = 'thread'; }
function showList()   { document.body.dataset.screen = 'list'; }


// ── Опрос ─────────────────────────────────────────────────

function startThreadPolling() {
  stopThreadPolling();
  threadTimer = setInterval(() => pullMessages(false), 3000);
}

function stopThreadPolling() {
  if (threadTimer) { clearInterval(threadTimer); threadTimer = null; }
}

// Во вкладке, которую не смотрят, опрашивать незачем — это экономит
// и батарею телефона, и заводской Wi-Fi.
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopThreadPolling();
    if (listTimer) { clearInterval(listTimer); listTimer = null; }
  } else {
    if (current) { pullMessages(false); startThreadPolling(); }
    if (!listTimer) listTimer = setInterval(() => loadList(true), 8000);
    loadList(true);
  }
});


// ── Мелочи ────────────────────────────────────────────────

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function oneLine(s) {
  return String(s || '').replace(/\s+/g, ' ').trim();
}


// ── Запуск ────────────────────────────────────────────────

async function boot() {
  await initLayout();

  try {
    const r = await ACAI.get('/auth/me');
    me = r?.user || r;
  } catch { return; }

  try {
    const c = await ACAI.get('/api/messenger/contacts');
    contacts = c.contacts || [];
  } catch {}

  await loadList();
  listTimer = setInterval(() => loadList(true), 8000);

  // Нижняя панель навигации появляется чуть позже (её рисует
  // mobile_nav_v2 после сайдбара) — пересчитываем, когда она есть.
  fitHeight();
  setTimeout(fitHeight, 400);
  setTimeout(fitHeight, 1200);

  const input = $('mgInput');

  input.addEventListener('keydown', (e) => {
    // Enter отправляет, Shift+Enter — перенос строки. На телефоне
    // Enter всегда переносит: там нет Shift под рукой.
    if (e.key === 'Enter' && !e.shiftKey && window.innerWidth > 768) {
      e.preventDefault();
      send();
    }
  });

  $('mgMessages').addEventListener('scroll', onScroll);

  // Перетаскивание файла прямо в переписку — на компьютере так быстрее.
  const thread = $('mgThread');
  ['dragenter', 'dragover'].forEach(ev =>
    thread.addEventListener(ev, e => { e.preventDefault(); thread.classList.add('mg-drop'); }));
  ['dragleave', 'drop'].forEach(ev =>
    thread.addEventListener(ev, e => { e.preventDefault(); thread.classList.remove('mg-drop'); }));
  thread.addEventListener('drop', e => {
    if (!current || !e.dataTransfer?.files?.length) return;
    onFilePicked({ files: e.dataTransfer.files, value: '' });
  });

  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 120) + 'px';
  });
}

// Наружу — на них ссылаются onclick в разметке.
window.openConversation = openConversation;
window.openNew = openNew;
window.openGroupForm = openGroupForm;
window.submitGroup = submitGroup;
window.togglePick = togglePick;
window.filterPeople = filterPeople;
window.startDm = startDm;
window.send = send;
window.removeMessage = removeMessage;
window.openGroupSettings = openGroupSettings;
window.invite = invite;
window.kick = kick;
window.saveTitle = saveTitle;
window.leaveGroup = leaveGroup;
window.showList = showList;
window.pickFile = pickFile;
window.onFilePicked = onFilePicked;
window.loadOlder = loadOlder;
window.renderList = renderList;

boot();

})();
