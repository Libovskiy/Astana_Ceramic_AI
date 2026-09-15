(function () {
"use strict";

let structure = null;
let canEdit = false;
let canApprove = false;
let search = "";
let stageFilter = "";
let statusFilter = "";
let selectedEquipment = null;
let editingPart = null;

const esc = v => { const d=document.createElement("div"); d.textContent=v ?? ""; return d.innerHTML; };
const stageLabel = {mass:"Массоподготовка", forming:"Формовка", drying:"Сушка", kiln:"Печь", packaging:"Упаковка"};

function updateClock(){
  const n=new Date();
  const d=document.getElementById("currentDate"), t=document.getElementById("currentTime");
  if(d)d.textContent=n.toLocaleDateString("ru-RU",{day:"numeric",month:"long",year:"numeric"});
  if(t)t.textContent=n.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
}

async function api(url, options={}){
  const r=await fetch(url,options);
  let data={}; try{data=await r.json();}catch{}
  if(r.status===401){location.href="/login";throw new Error("auth");}
  if(!r.ok) throw new Error(data.detail||data.message||"Ошибка запроса");
  return data;
}

async function load() {
    const box = document.getElementById("equipmentStructure");

    if (!box) {
        console.error("ACAI: #equipmentStructure не найден");
        return;
    }

    box.innerHTML =
        '<div class="loading-state">Загрузка структуры...</div>';

    try {
        structure = await api("/api/structure");

        populateStageFilter();

        canEdit = !!structure.can_edit;

        const addEquipmentButton =
            document.getElementById("addEquipmentTop");

        if (addEquipmentButton) {
            addEquipmentButton.style.display =
                canEdit ? "inline-flex" : "none";
        }

        const addStageButton =
            document.getElementById("addStageTop");

        if (addStageButton) {
            addStageButton.style.display =
                canEdit ? "inline-flex" : "none";
        }

        const permissionHint =
            document.getElementById("structurePermissionHint");

        if (permissionHint) {
            permissionHint.textContent =
                canEdit
                    ? "Управление структурой доступно"
                    : "Только просмотр";
        }

        render();

    } catch (error) {
        console.error("ACAI: ошибка загрузки структуры", error);

        if (error.message !== "auth") {
            box.innerHTML =
                '<div class="empty-state error-state">' +
                'Не удалось загрузить оборудование.' +
                '</div>';
        }
    }
}

function allEquipment() { return (structure?.stages||[]).flatMap(s=>(s.equipment||[]).map(e=>({...e,stageName:s.name,stageKey:s.stage_key}))).concat(structure?.orphans||[]); }

function populateStageFilter(){

    const select =
        document.getElementById("stageFilter");

    if (!select) {
        return;
    }

    const currentValue = select.value;

    select.innerHTML =
        '<option value="">Все этапы</option>';

    for (const stage of (structure?.stages || [])) {

        const option =
            document.createElement("option");

        option.value = stage.stage_key;

        option.textContent = stage.name;

        select.appendChild(option);
    }

    if (
        [...select.options]
            .some(option => option.value === currentValue)
    ) {
        select.value = currentValue;
    }
}

function renderSummary(){
  const items=allEquipment();
  const parts=items.reduce((n,e)=>n+(e.parts_count||0),0);
  const docs=items.reduce((n,e)=>n+(e.docs_count||0),0);
  document.getElementById("equipmentSummary").innerHTML=`
    <div><span>Этапов</span><b>${structure?.stages?.length||0}</b></div>
    <div><span>Оборудования</span><b>${items.length}</b></div>
    <div><span>Частей</span><b>${parts}</b></div>
    <div><span>Документов</span><b>${docs}</b></div>`;
}

function equipmentSearchText(e) {
    return [
        e.name,
        e.type,
        e.inventory_number,
        e.location,
        e.discipline,
        e.stage,
        e.stageName,
        e.description,
    ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
}

function render(){

    renderSummary();

    const q = search.toLowerCase().trim();
    const selectedStage = stageFilter;
    const selectedStatus = statusFilter;
    const box = document.getElementById("equipmentStructure");
    const html = [];

    const stages = [...(structure.stages || [])].sort((a, b) => {
        const sortA = Number(a.sort_order ?? 9999);
        const sortB = Number(b.sort_order ?? 9999);

        if (sortA !== sortB) {
            return sortA - sortB;
        }

        return Number(a.id || 0) - Number(b.id || 0);
    });

    for (let index = 0; index < stages.length; index++) {

        const stage = stages[index];

        if (selectedStage && stage.stage_key !== selectedStage) {
            continue;
        }

        const items = (stage.equipment || []).filter(e => {

            const text = equipmentSearchText({
                ...e,
                stageName: stage.name,
            });

            const matchesSearch =
                !q || text.includes(q);

            const matchesStatus =
                !selectedStatus ||
                (e.status || "") === selectedStatus;

            return matchesSearch && matchesStatus;
        });

        if (!items.length) {
            continue;
        }

        const workingCount = items.filter(e => {
            const status = (e.status || "").toLowerCase();
            return status.includes("работ");
        }).length;

        const attentionCount = items.length - workingCount;

        html.push(`
            <section class="equipment-stage">

                <div class="equipment-stage-head">

                    <div>

                        <div class="equipment-stage-index">
                            ЭТАП ${String(index + 1).padStart(2, "0")}
                        </div>

                        <h3>
                            ${esc(stage.name)}
                        </h3>

                        <div class="equipment-stage-meta">
                            ${items.length} ед.
                            ${workingCount ? ` · ${workingCount} работает` : ""}
                            ${attentionCount ? ` · ${attentionCount} требуют внимания` : ""}
                        </div>

                    </div>

                    <div class="stage-actions">

                        ${
                            canEdit
                            ?
                            `
                            <button
                                class="icon-btn"
                                data-stage-edit="${stage.id}"
                                title="Изменить этап"
                            >
                                Изменить
                            </button>

                            <button
                                class="icon-btn"
                                data-stage-doc="${esc(stage.stage_key)}"
                                title="Добавить документ"
                            >
                                ＋ Документ
                            </button>

                            <button
                                class="icon-btn danger"
                                data-stage-del="${stage.id}"
                                title="Архивировать этап"
                            >
                                Архивировать
                            </button>
                            `
                            :
                            ""
                        }

                    </div>

                </div>

                <div class="equipment-grid">
                    ${items.map(card).join("")}
                </div>

            </section>
        `);
    }

    /*
     * Оборудование без этапа.
     * Показываем только если не выбран конкретный этап.
     */

    if (!selectedStage) {

        const orphan = (structure.orphans || []).filter(e => {

            const text =
                `${e.name || ""} ${e.type || ""} ${e.location || ""}`.toLowerCase();

            const matchesSearch =
                !q || text.includes(q);

            const matchesStatus =
                !selectedStatus ||
                (e.status || "") === selectedStatus;

            return matchesSearch && matchesStatus;
        });

        if (orphan.length) {

            html.push(`
                <section class="equipment-stage">

                    <div class="equipment-stage-head">

                        <div>

                            <div class="equipment-stage-index">
                                СТРУКТУРА
                            </div>

                            <h3>
                                Без этапа
                            </h3>

                            <div class="equipment-stage-meta">
                                ${orphan.length} ед.
                            </div>

                        </div>

                    </div>

                    <div class="equipment-grid">
                        ${orphan.map(card).join("")}
                    </div>

                </section>
            `);
        }
    }

    box.innerHTML =
        html.join("") ||
        '<div class="empty-state">По заданным параметрам ничего не найдено.</div>';

    bind();
}

function getStatusIcon(status) {
    const normalized = (status || "").toLowerCase();

    if (normalized.includes("крит")) {
        return "🔴";
    }

    if (normalized.includes("ошиб")) {
        return "🔴";
    }

    if (normalized.includes("вним")) {
        return "🟡";
    }

    if (normalized.includes("работ")) {
        return "🟢";
    }

    return "⚪";
}

function card(e) {
    const dot = getStatusIcon(e.status);

    return `
        <article class="equipment-object">

            <div class="equipment-object-top">

                <div class="equipment-object-icon">⚙</div>

                <div class="equipment-object-title">
                    <h4>${esc(e.name)}</h4>
                    <span>${esc(e.type || "Оборудование")}</span>
                </div>

                <div class="equipment-status">
                    ${dot} ${esc(e.status || "Нет данных")}
                </div>

            </div>

            <div class="equipment-object-meta">
                <span>${e.parts_count || 0} частей</span>
                <span>${e.docs_count || 0} документов</span>
                <span>${e.params_count || 0} параметров</span>
                ${
                    e.location
                        ? `<span class="equipment-location">Расположение: ${esc(e.location)}</span>`
                        : ""
                }
            </div>

            ${
                e.description
                    ? `<p class="equipment-object-desc">${esc(e.description)}</p>`
                    : ""
            }

            <div class="equipment-object-actions">

                <button
                    class="btn btn-primary btn-sm"
                    data-guide="${e.id}"
                >
                    📖 Руководство
                </button>

                <button
                    class="btn btn-secondary btn-sm"
                    data-parts="${e.id}"
                >
                    Части
                </button>

                <button
                    class="btn btn-secondary btn-sm"
                    data-docs="${e.id}"
                >
                    Документы
                </button>

                ${
                    canEdit
                        ? `
                            <button
                                class="btn btn-ghost btn-sm"
                                data-edit="${e.id}"
                            >
                                Изменить
                            </button>

                            <button
                                class="btn btn-ghost btn-sm"
                                data-move="${e.id}"
                            >
                                Переместить
                            </button>

                            <button
                                class="btn btn-danger-soft btn-sm"
                                data-del="${e.id}"
                            >
                                Архивировать
                            </button>
                        `
                        : ""
                }

            </div>

        </article>
    `;
}

function bind(){
  document.querySelectorAll("[data-guide]").forEach(b=>b.onclick=()=>openGuide(+b.dataset.guide));
  document.querySelectorAll("[data-parts]").forEach(b=>b.onclick=()=>openGuide(+b.dataset.parts,"parts"));
  document.querySelectorAll("[data-docs]").forEach(b=>b.onclick=()=>openGuide(+b.dataset.docs,"documents"));
  document.querySelectorAll("[data-edit]").forEach(b=>b.onclick=()=>equipmentForm(+b.dataset.edit));
  document.querySelectorAll("[data-del]").forEach(b=>b.onclick=()=>deleteEquipment(+b.dataset.del));
  document.querySelectorAll("[data-stage-del]").forEach(b=>b.onclick=()=>deleteStage(+b.dataset.stageDel));
  document.querySelectorAll("[data-stage-edit]").forEach(b=>b.onclick=()=>editStage(+b.dataset.stageEdit));
  document.querySelectorAll("[data-stage-doc]").forEach(b=>b.onclick=()=>stageDocument(b.dataset.stageDoc));
  document.querySelectorAll("[data-move]").forEach(b=>b.onclick=()=>moveEquipment(+b.dataset.move));
}

function modal(title, body, actions=""){
  let old=document.getElementById("equipmentModal"); if(old)old.remove();
  const m=document.createElement("div");m.id="equipmentModal";m.className="eq-modal";
  m.innerHTML=`<div class="eq-modal-box"><div class="eq-modal-head"><h2>${title}</h2><button class="eq-close">×</button></div><div class="eq-modal-body">${body}</div>${actions?`<div class="eq-modal-actions">${actions}</div>`:""}</div>`;
  document.body.appendChild(m);m.onclick=e=>{if(e.target===m)m.remove();};m.querySelector(".eq-close").onclick=()=>m.remove();return m;
}

async function equipmentForm(id=null){
  let item=null;
  if(id){ item=allEquipment().find(x=>Number(x.id)===id); }
  const stages=structure?.stages||[];
  const m=modal(id?"Изменить оборудование":"Добавить оборудование",`<div class="eq-form-grid">
    <label>Название<input id="efName" value="${esc(item?.name||"")}"></label>
    <label>Тип<input id="efType" value="${esc(item?.type||"")}"></label>
    <label>Этап<select id="efStage">${(item?.stage && !stages.some(s=>s.stage_key===item.stage))?`<option value="${esc(item.stage)}" selected>Текущий этап (неактивен)</option>`:""}${stages.map(s=>`<option value="${esc(s.stage_key)}" ${item?.stage===s.stage_key?"selected":""}>${esc(s.name)}</option>`).join("")}</select></label>
    <label>Дисциплина<select id="efDis"><option value="both" ${!item?.discipline || item.discipline==="both"?"selected":""}>Механика + электрика</option><option value="mechanics" ${item?.discipline==="mechanics"?"selected":""}>Механика</option><option value="electrical" ${item?.discipline==="electrical"?"selected":""}>Электрика</option></select></label>
    <label>Расположение<input id="efLocation" value="${esc(item?.location||"")}"></label>
    <label>Инвентарный номер<input id="efInv" value="${esc(item?.inventory_number||"")}"></label>
    <label class="full">Описание<textarea id="efDesc">${esc(item?.description||"")}</textarea></label>
  </div><div id="efError" class="form-error"></div>`,`<button class="btn btn-secondary eq-close-action">Отмена</button><button class="btn btn-primary" id="efSave">Сохранить</button>`);
  m.querySelector(".eq-close-action").onclick=()=>m.remove();
  m.querySelector("#efSave").onclick=async()=>{
    const body={name:m.querySelector("#efName").value.trim(),type:m.querySelector("#efType").value.trim(),stage:m.querySelector("#efStage").value,discipline:m.querySelector("#efDis").value,location:m.querySelector("#efLocation").value.trim(),inventory_number:m.querySelector("#efInv").value.trim(),description:m.querySelector("#efDesc").value.trim()};
    if(!body.name){m.querySelector("#efError").textContent="Укажите название.";return;}
    try{await api(id?`/api/structure/equipment/${id}`:"/api/structure/equipment",{method:id?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});m.remove();await load();}
    catch(e){m.querySelector("#efError").textContent=e.message;}
  };
}

async function deleteEquipment(id){
  const e=allEquipment().find(x=>+x.id===id);if(!e)return;
  if(!confirm(`Убрать «${e.name}» из активной структуры?\nИстория обращений и журнал сохранятся.`))return;
  try{await api(`/api/structure/equipment/${id}`,{method:"DELETE"});await load();}catch(e){alert(e.message);}
}

async function editStage(id){
  const stage=(structure?.stages||[]).find(x=>+x.id===id);
  if(!stage)return;
  const m=modal("Изменить этап",`<div class="eq-form-grid"><label>Название этапа<input id="stageEditName" value="${esc(stage.name||"")}"></label><label class="full">Описание<textarea id="stageEditDesc">${esc(stage.description||"")}</textarea></label><label class="full">Причина изменения<input id="stageEditReason" placeholder="Например: изменение производственного маршрута"></label></div><div id="stageEditError" class="form-error"></div>`,`<button class="btn btn-secondary eq-close-action">Отмена</button><button class="btn btn-primary" id="stageEditSave">Сохранить</button>`);
  m.querySelector(".eq-close-action").onclick=()=>m.remove();
  m.querySelector("#stageEditSave").onclick=async()=>{
    const name=m.querySelector("#stageEditName").value.trim();
    const description=m.querySelector("#stageEditDesc").value.trim()||null;
    const reason=m.querySelector("#stageEditReason").value.trim()||null;
    if(!name){m.querySelector("#stageEditError").textContent="Укажите название.";return;}
    try{await api(`/api/structure/stages/${id}`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,description,sort_order:stage.sort_order,reason})});m.remove();await load();}
    catch(e){m.querySelector("#stageEditError").textContent=e.message;}
  };
}

async function moveEquipment(id){
  const e=allEquipment().find(x=>+x.id===id);
  if(!e)return;
  const options=(structure?.stages||[]).map(st=>`<option value="${esc(st.stage_key)}" ${st.stage_key===e.stageKey?"selected":""}>${esc(st.name)}</option>`).join("");
  const m=modal("Переместить оборудование",`<div class="eq-form-grid"><label class="full">Оборудование<input value="${esc(e.name)}" disabled></label><label class="full">Новый этап<select id="moveStage">${options}</select></label><label class="full">Причина перемещения<textarea id="moveReason" placeholder="Почему оборудование меняет этап?"></textarea></label></div><div id="moveError" class="form-error"></div>`,`<button class="btn btn-secondary eq-close-action">Отмена</button><button class="btn btn-primary" id="moveSave">Переместить</button>`);
  m.querySelector(".eq-close-action").onclick=()=>m.remove();
  m.querySelector("#moveSave").onclick=async()=>{
    const new_stage=m.querySelector("#moveStage").value; const reason=m.querySelector("#moveReason").value.trim();
    if(!reason){m.querySelector("#moveError").textContent="Причина обязательна.";return;}
    try{await api(`/api/structure/equipment/${id}/move`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({new_stage,reason})});m.remove();await load();}
    catch(err){m.querySelector("#moveError").textContent=err.message;}
  };
}

async function deleteStage(id){
  if(!confirm("Убрать этап из активной структуры? Оборудование и история не удаляются."))return;
  try{await api(`/api/structure/stages/${id}`,{method:"DELETE"});await load();}catch(e){alert(e.message);}
}

async function addStage(){
  const m=modal("Добавить этап",`<label>Название этапа<input id="stageName" placeholder="Например, Подготовка сырья"></label><div id="stageError" class="form-error"></div>`,`<button class="btn btn-secondary eq-close-action">Отмена</button><button class="btn btn-primary" id="stageSave">Добавить</button>`);
  m.querySelector(".eq-close-action").onclick=()=>m.remove();m.querySelector("#stageSave").onclick=async()=>{const name=m.querySelector("#stageName").value.trim();if(!name){m.querySelector("#stageError").textContent="Укажите название.";return;}try{await api("/api/structure/stages",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})});m.remove();await load();}catch(e){m.querySelector("#stageError").textContent=e.message;}};
}

async function partsTab(id){
  const data=await api(`/api/structure/equipment/${id}/parts`); const item=allEquipment().find(x=>+x.id===id);
  const rows=(data.parts||[]).map(p=>`<div class="part-object"><div><b>${esc(p.name)}</b><span>${esc(p.part_number||"Без артикула")}</span>${p.description?`<p>${esc(p.description)}</p>`:""}</div><div class="part-actions">${canEdit?`<button class="btn btn-ghost btn-sm" data-edit-part="${p.id}">Изменить</button><button class="btn btn-danger-soft btn-sm" data-del-part="${p.id}">Удалить</button>`:""}<button class="btn btn-secondary btn-sm" data-part-doc="${p.id}">Документы</button></div></div>`).join("");
  const m=modal(`Части · ${item?.name||"Оборудование"}`,`<div class="modal-section-actions">${canEdit?`<button class="btn btn-primary btn-sm" id="addPart">＋ Добавить часть</button>`:""}</div><div class="parts-object-list">${rows||'<div class="empty-state">Частей пока нет.</div>'}</div>`);
  if(m.querySelector("#addPart"))m.querySelector("#addPart").onclick=()=>partForm(id,null);
  m.querySelectorAll("[data-edit-part]").forEach(b=>b.onclick=()=>partForm(id,+b.dataset.editPart));
  m.querySelectorAll("[data-del-part]").forEach(b=>b.onclick=()=>deletePart(+b.dataset.delPart,id));
  m.querySelectorAll("[data-part-doc]").forEach(b=>b.onclick=()=>partDocuments(+b.dataset.partDoc,id));
}

async function partForm(equipmentId, partId){
  let p=null;if(partId){const d=await api(`/api/structure/equipment/${equipmentId}/parts`);p=(d.parts||[]).find(x=>+x.id===partId);}
  const m=modal(partId?"Изменить часть":"Добавить часть",`<div class="eq-form-grid"><label>Название<input id="pfName" value="${esc(p?.name||"")}"></label><label>Артикул<input id="pfNum" value="${esc(p?.part_number||"")}"></label><label>Статус<input id="pfStatus" value="${esc(p?.status||"")}"></label><label class="full">Описание<textarea id="pfDesc">${esc(p?.description||"")}</textarea></label><label class="full">Примечание<textarea id="pfNote">${esc(p?.note||"")}</textarea></label></div><div id="pfError" class="form-error"></div>`,`<button class="btn btn-secondary eq-close-action">Отмена</button><button class="btn btn-primary" id="pfSave">Сохранить</button>`);
  m.querySelector(".eq-close-action").onclick=()=>m.remove();m.querySelector("#pfSave").onclick=async()=>{const body={name:m.querySelector("#pfName").value.trim(),part_number:m.querySelector("#pfNum").value.trim()||null,status:m.querySelector("#pfStatus").value.trim()||null,description:m.querySelector("#pfDesc").value.trim()||null,note:m.querySelector("#pfNote").value.trim()||null};if(!body.name){m.querySelector("#pfError").textContent="Укажите название.";return;}try{await api(partId?`/api/structure/parts/${partId}`:`/api/structure/equipment/${equipmentId}/parts`,{method:partId?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});m.remove();await partsTab(equipmentId);await load();}catch(e){m.querySelector("#pfError").textContent=e.message;}};
}

async function deletePart(id,equipmentId){if(!confirm("Убрать часть из активного списка? История сохранится."))return;try{await api(`/api/structure/parts/${id}`,{method:"DELETE"});await partsTab(equipmentId);await load();}catch(e){alert(e.message);}}

async function docsTab(equipmentId,partId=null){
  const data=await api(`/api/structure/documents?${partId?`part_id=${partId}`:`equipment_id=${equipmentId}`}`);
  const docs=data.documents||[];
  const canApprove=!!data.can_approve;
  const rows=docs.map(d=>{const status=d.status||"pending"; const ks=d.knowledge_status||"blocked"; const badge=status==="approved"?"🟢 Подтверждён":status==="rejected"?"🔴 Отклонён":"🟡 На проверке"; const ai=ks==="indexed"?"AI: 🟢 в базе знаний":ks==="error"?`AI: 🔴 ${esc(d.knowledge_error||"ошибка")}`:status==="approved"?"AI: 🟡 обрабатывается":"AI: ⚪ заблокирован"; return `<div class="document-object"><div class="doc-icon">📄</div><div class="doc-main"><b>${esc(d.title||d.name||"Документ")}</b><span>${esc(d.doc_type||"document")} · ${badge}</span><small>${d.exists?"Файл доступен":"Файл не найден"} · ${ai}</small></div><div class="doc-actions">${d.url?`<a class="btn btn-secondary btn-sm" target="_blank" href="${esc(d.url)}">Открыть</a>`:""}${canApprove&&status==="pending"?`<button class="btn btn-primary btn-sm" data-doc-approve="${d.id}">Подтвердить</button><button class="btn btn-danger-soft btn-sm" data-doc-reject="${d.id}">Отклонить</button>`:""}${canEdit?`<button class="btn btn-danger-soft btn-sm" data-doc-del="${d.id}">Удалить</button>`:""}</div></div>`;}).join("");
  const m=modal(partId?"Документы части":"Документы оборудования",`<div class="modal-section-actions">${canEdit?`<button class="btn btn-primary btn-sm" id="uploadDoc">＋ Добавить документ</button>`:""}</div><div class="documents-object-list">${rows||'<div class="empty-state">Документов пока нет.</div>'}</div>`);
  if(m.querySelector("#uploadDoc"))m.querySelector("#uploadDoc").onclick=()=>uploadDocument(equipmentId,partId);
  m.querySelectorAll("[data-doc-del]").forEach(b=>b.onclick=async()=>{if(!confirm("Архивировать документ?"))return;try{await api(`/api/structure/documents/${b.dataset.docDel}`,{method:"DELETE"});await docsTab(equipmentId,partId);}catch(e){alert(e.message);}});
  m.querySelectorAll("[data-doc-approve]").forEach(b=>b.onclick=async()=>{try{await api(`/api/structure/documents/${b.dataset.docApprove}/status`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:"approved"})});await docsTab(equipmentId,partId);}catch(e){alert(e.message);}});
  m.querySelectorAll("[data-doc-reject]").forEach(b=>b.onclick=async()=>{try{await api(`/api/structure/documents/${b.dataset.docReject}/status`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:"rejected"})});await docsTab(equipmentId,partId);}catch(e){alert(e.message);}});
}

async function uploadDocument(equipmentId,partId=null,stageKey=null){
  const m=modal("Добавить документ",`<div class="eq-form-grid"><label class="full">Файл<input id="docFile" type="file" accept=".pdf,.doc,.docx,.xls,.xlsx,.jpg,.jpeg,.png"></label><label>Название<input id="docTitle" placeholder="Название документа"></label><label>Тип<select id="docType"><option value="manual">Руководство</option><option value="scheme">Схема</option><option value="instruction">Инструкция</option><option value="passport">Технический документ</option><option value="other">Другое</option></select></label><label class="full">Примечание<textarea id="docNote"></textarea></label></div><div id="docError" class="form-error"></div>`,`<button class="btn btn-secondary eq-close-action">Отмена</button><button class="btn btn-primary" id="docSave">Загрузить</button>`);
  m.querySelector(".eq-close-action").onclick=()=>m.remove();m.querySelector("#docSave").onclick=async()=>{const f=m.querySelector("#docFile").files[0];if(!f){m.querySelector("#docError").textContent="Выберите файл.";return;}try{const content=await fileData(f);const body={filename:f.name,content,title:m.querySelector("#docTitle").value.trim()||null,doc_type:m.querySelector("#docType").value,note:m.querySelector("#docNote").value.trim()||null};if(partId)body.part_id=partId;if(stageKey)await api(`/api/structure/stages/${encodeURIComponent(stageKey)}/documents`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});else await api(`/api/structure/equipment/${equipmentId}/documents`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});m.remove();await load();if(partId)await docsTab(equipmentId,partId);else await docsTab(equipmentId);}catch(e){m.querySelector("#docError").textContent=e.message;}};
}
function fileData(file){return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result);r.onerror=rej;r.readAsDataURL(file);});}
async function stageDocument(stageKey){await uploadDocument(null,null,stageKey);}

async function openGuide(id,tab="overview"){
  selectedEquipment=id;
  const d=await api(`/api/equipment/${id}`);const item=d.equipment;const p=await api(`/api/structure/equipment/${id}/parts`);const docs=await api(`/api/structure/documents?equipment_id=${id}`);canApprove=!!docs.can_approve;const hist=await api(`/api/structure/history?target=equipment:${id}`);
  const tabs=["overview","parts","documents","history"];const labels={overview:"Обзор",parts:"Части",documents:"Документы",history:"История"};
  const body=`<div class="guide-hero">${item.photo_path?`<img src="${esc(item.photo_path)}">`:`<div class="guide-placeholder">⚙</div>`}<div><span class="guide-stage">${esc(item.stage||"")}</span><h3>${esc(item.name)}</h3><p>${esc(item.type||"Оборудование")}</p></div></div><div class="guide-tabs">${tabs.map(t=>`<button class="guide-tab ${tab===t?"active":""}" data-tab="${t}">${labels[t]}</button>`).join("")}</div><div id="guideBody">${guideContent(tab,item,p.parts||[],docs.documents||[],hist.events||[])}</div>`;
  const m=modal("Руководство",body);
  m.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{m.querySelectorAll("[data-tab]").forEach(x=>x.classList.remove("active"));b.classList.add("active");m.querySelector("#guideBody").innerHTML=guideContent(b.dataset.tab,item,p.parts||[],docs.documents||[],hist.events||[]);bindGuide(m,id,b.dataset.tab);});
  bindGuide(m,id,tab);
}
function guideContent(tab,item,parts,docs,events){
 if(tab==="overview")return `<div class="guide-overview"><div class="guide-stat"><span>Статус</span><b>${esc(item.status||"Нет данных")}</b></div><div class="guide-stat"><span>Расположение</span><b>${esc(item.location||"—")}</b></div><div class="guide-stat"><span>Инвентарный номер</span><b>${esc(item.inventory_number||"—")}</b></div><div class="guide-stat"><span>Последняя проверка</span><b>${esc(item.last_check||"—")}</b></div></div><p class="guide-description">${esc(item.description||"Описание пока не добавлено.")}</p>`;
 if(tab==="parts")return `<div class="modal-section-actions">${canEdit?`<button class="btn btn-primary btn-sm" data-guide-add-part="${item.id}">＋ Добавить часть</button>`:""}</div><div class="parts-object-list">${parts.length?parts.map(p=>`<div class="part-object"><div><b>${esc(p.name)}</b><span>${esc(p.part_number||"Без артикула")}</span></div><div class="part-actions">${canEdit?`<button class="btn btn-ghost btn-sm" data-guide-edit-part="${p.id}">Изменить</button><button class="btn btn-danger-soft btn-sm" data-guide-del-part="${p.id}">Удалить</button>`:""}<button class="btn btn-secondary btn-sm" data-guide-part-doc="${p.id}">Документы</button></div></div>`).join(""):"<div class=\"empty-state\">Частей пока нет.</div>"}</div>`;
 if(tab==="documents")return `<div class="modal-section-actions">${canEdit?`<button class="btn btn-primary btn-sm" data-guide-upload="${item.id}">＋ Добавить документ</button>`:""}</div><div class="documents-object-list">${docs.length?docs.map(d=>{const st=d.status||"pending";const ks=d.knowledge_status||"blocked";const badge=st==="approved"?"🟢 Подтверждён":st==="rejected"?"🔴 Отклонён":"🟡 На проверке";const ai=ks==="indexed"?"AI: 🟢 в базе знаний":ks==="error"?`AI: 🔴 ${esc(d.knowledge_error||"ошибка")}`:st==="approved"?"AI: 🟡 обрабатывается":"AI: ⚪ заблокирован";return `<div class="document-object"><div class="doc-icon">📄</div><div class="doc-main"><b>${esc(d.title||"Документ")}</b><span>${esc(d.doc_type||"")} · ${badge}</span><small>${d.exists?"Файл доступен":"Файл не найден"} · ${ai}</small></div><div class="doc-actions">${d.url?`<a class="btn btn-secondary btn-sm" target="_blank" href="${esc(d.url)}">Открыть</a>`:""}${canApprove&&st==="pending"?`<button class="btn btn-primary btn-sm" data-guide-approve-doc="${d.id}">Подтвердить</button><button class="btn btn-danger-soft btn-sm" data-guide-reject-doc="${d.id}">Отклонить</button>`:""}${canEdit?`<button class="btn btn-danger-soft btn-sm" data-guide-del-doc="${d.id}">Удалить</button>`:""}</div></div>`;}).join(""):"<div class=\"empty-state\">Документов пока нет.</div>"}</div>`;
 return events.length?events.map(e=>`<div class="history-object"><span>${esc(e.created_at||"")}</span><b>${esc(e.action||"")}</b><p>${esc(e.details||"")}</p><small>${esc(e.username||"")} · ${esc(e.role||"")}</small></div>`).join(""):"<div class=\"empty-state\">История пока пуста.</div>";
}
function bindGuide(m,id,tab){m.querySelectorAll("[data-guide-add-part]").forEach(b=>b.onclick=()=>partForm(id,null));m.querySelectorAll("[data-guide-edit-part]").forEach(b=>b.onclick=()=>partForm(id,+b.dataset.guideEditPart));m.querySelectorAll("[data-guide-del-part]").forEach(b=>b.onclick=()=>deletePart(+b.dataset.guideDelPart,id));m.querySelectorAll("[data-guide-part-doc]").forEach(b=>b.onclick=()=>docsTab(id,+b.dataset.guidePartDoc));m.querySelectorAll("[data-guide-upload]").forEach(b=>b.onclick=()=>uploadDocument(id));m.querySelectorAll("[data-guide-del-doc]").forEach(b=>b.onclick=async()=>{if(!confirm("Архивировать документ?"))return;await api(`/api/structure/documents/${b.dataset.guideDelDoc}`,{method:"DELETE"});openGuide(id,"documents");});m.querySelectorAll("[data-guide-approve-doc]").forEach(b=>b.onclick=async()=>{try{await api(`/api/structure/documents/${b.dataset.guideApproveDoc}/status`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:"approved"})});openGuide(id,"documents");}catch(e){alert(e.message);}});m.querySelectorAll("[data-guide-reject-doc]").forEach(b=>b.onclick=async()=>{try{await api(`/api/structure/documents/${b.dataset.guideRejectDoc}/status`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:"rejected"})});openGuide(id,"documents");}catch(e){alert(e.message);}});}

document.addEventListener("DOMContentLoaded", () => {

    updateClock();

    setInterval(updateClock, 1000);

    load();


    const refreshButton =
        document.getElementById("refreshStructure");

    if (refreshButton) {
        refreshButton.onclick = load;
    }


    const addEquipmentButton =
        document.getElementById("addEquipmentTop");

    if (addEquipmentButton) {
        addEquipmentButton.onclick = () => equipmentForm();
    }


    const addStageButton =
        document.getElementById("addStageTop");

    if (addStageButton) {
        addStageButton.onclick = addStage;
    }


        const searchInput =
        document.getElementById("equipmentSearch");

    if (searchInput) {
        searchInput.oninput = event => {
            search = event.target.value.trim();
            render();
        };
    }


    // =========================================================
    // Архив оборудования
    // =========================================================

    const archiveButton =
        document.getElementById("equipmentArchiveBtn");

    if (archiveButton) {
        archiveButton.onclick = async () => {
            try {
                const data =
                    await api("/api/structure/equipment-archive");

                const archived = (data.equipment || [])
                    .filter(item => Number(item.is_active) === 0);

                if (!archived.length) {
                    modal(
                        "Архив оборудования",
                        `
                            <div class="empty-state">
                                Архив оборудования пуст.
                            </div>
                        `
                    );

                    return;
                }

                const rows = archived.map(item => `
                    <div class="document-object">
                        <div class="doc-icon">🗄</div>

                        <div class="doc-main">
                            <b>${esc(item.name || "Оборудование")}</b>

                            <span>
                                ${esc(item.type || "Оборудование")}
                            </span>

                            <small>
                                ${esc(item.location || "Расположение не указано")}
                            </small>
                        </div>

                        <div class="doc-actions">

                        <button
                            class="btn btn-secondary btn-sm"
                            data-restore-equipment="${item.id}"
                        >
                            Восстановить
                        </button>

                        <button
                            class="btn btn-danger-soft btn-sm"
                            data-delete-equipment="${item.id}"
                        >
                            Удалить навсегда
                        </button>

                        </div>
                    </div>
                `).join("");

                const archiveModal = modal(
                    "Архив оборудования",
                    `
                        <div class="documents-object-list">
                            ${rows}
                        </div>
                    `
                );

                archiveModal
                    .querySelectorAll("[data-restore-equipment]")
                    .forEach(button => {

                        button.onclick = async () => {

                            const equipmentId =
                                Number(
                                    button.dataset.restoreEquipment
                                );

                            if (!equipmentId) {
                                return;
                            }

                            if (
                                !confirm(
                                    "Восстановить это оборудование в активную структуру?"
                                )
                            ) {
                                return;
                            }

                            try {

                                await api(
                                    `/api/structure/equipment/${equipmentId}/restore`,
                                    {
                                        method: "POST"
                                    }
                                );

                                archiveModal.remove();

                                await load();

                                alert(
                                    "Оборудование восстановлено."
                                );

                            } catch (error) {

                                alert(error.message);
                            }
                        };
                    });

                archiveModal
    .querySelectorAll("[data-delete-equipment]")
    .forEach(button => {

        button.onclick = async () => {

            const equipmentId = Number(
                button.dataset.deleteEquipment
            );

            if (!equipmentId) {
                return;
            }

            const equipmentName =
                button
                    .closest(".document-object")
                    ?.querySelector(".doc-main b")
                    ?.textContent
                    ?.trim() || "это оборудование";

            const confirmed = confirm(
                `Удалить «${equipmentName}» НАВСЕГДА?\n\n` +
                "Операцию невозможно отменить."
            );

            if (!confirmed) {
                return;
            }

            try {

                await api(
                    `/api/structure/equipment/${equipmentId}/permanent`,
                    {
                        method: "DELETE"
                    }
                );

                button
                    .closest(".document-object")
                    ?.remove();

                await load();

                alert(
                    "Оборудование окончательно удалено."
                );

            } catch (error) {

                alert(
                    "Не удалось удалить оборудование: " +
                    error.message
                );
            }
        };
    });

            } catch (error) {

                alert(
                    "Не удалось открыть архив: " +
                    error.message
                );
            }
        };
    }

    // Фильтр по этапу
    const stageSelect =
        document.getElementById("stageFilter");

    if (stageSelect) {
        stageSelect.onchange = event => {
            stageFilter = event.target.value;
            render();
        };
    }


    // Фильтр по состоянию
    const statusSelect =
        document.getElementById("statusFilter");

    if (statusSelect) {
        statusSelect.onchange = event => {
            statusFilter = event.target.value;
            render();
        };
    }

});
})();