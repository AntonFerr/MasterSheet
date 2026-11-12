const $ = (selector) => document.querySelector(selector);
const state = { rpgs: [], fichas: [], rpgFilter: "", search: "", profile: null, records: [], recordKind: "treino", activePowers: new Set() };
let toastTimer;

async function api(url, options = {}) {
  const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Não foi possível concluir a ação.");
  return data;
}
function notify(message) {
  const toast = $("#toast"); toast.textContent = message; toast.classList.add("visible");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove("visible"), 2600);
}
function esc(value = "") {
  return String(value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
}
function initials(name) { return (name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join("") || "✦").toUpperCase(); }
function formatId(id) { return id.slice(0, 8).toUpperCase(); }
function plural(count, one, many = `${one}s`) { return `${count} ${count === 1 ? one : many}`; }
async function refresh() {
  const [rpgs, fichas] = await Promise.all([api("/api/rpgs"), api("/api/fichas")]);
  state.rpgs = rpgs; state.fichas = fichas; render();
}
function render() {
  const selectedRpg = state.rpgs.find(rpg => rpg.id === state.rpgFilter);
  $("#crumb-current").textContent = selectedRpg?.name || "Todas as fichas";
  $("#page-title").innerHTML = `${esc(selectedRpg?.name || "Todas as fichas")}<span class="title-period">.</span>`;
  $("#page-description").textContent = selectedRpg ? `Personagens e histórias do universo ${selectedRpg.name}.` : "Personagens, histórias e aventuras em um só lugar.";
  $("#rpg-list").innerHTML = state.rpgs.length ? state.rpgs.map(rpg => `<button class="rpg-item ${state.rpgFilter === rpg.id ? "active" : ""}" data-rpg="${esc(rpg.id)}"><span class="rpg-gem"></span><span>${esc(rpg.name)}</span><span class="rpg-item-count">${rpg.ficha_count}</span></button>`).join("") : `<div class="rpg-empty">Nenhum RPG cadastrado.</div>`;
  $("#filter-rpg").innerHTML = `<option value="">Todos os RPGs</option>` + state.rpgs.map(rpg => `<option value="${esc(rpg.id)}">${esc(rpg.name)}</option>`).join("");
  $("#filter-rpg").value = state.rpgFilter;
  $("#ficha-rpg").innerHTML = state.rpgs.map(rpg => `<option value="${esc(rpg.id)}">${esc(rpg.name)}</option>`).join("");
  const query = state.search.trim().toLocaleLowerCase("pt-BR");
  const visible = state.fichas.filter(ficha => (!state.rpgFilter || ficha.rpg_id === state.rpgFilter) && (!query || [ficha.name, ficha.history, ficha.rpg_name, ficha.id, ...ficha.tags].join(" ").toLocaleLowerCase("pt-BR").includes(query)));
  $("#total-count").textContent = state.fichas.length;
  $("#footer-total").textContent = `${state.fichas.length} ${state.fichas.length === 1 ? "personagem guardado" : "personagens guardados"}`;
  $("#results-count").textContent = plural(visible.length, "ficha");
  $("#results-context").textContent = state.search ? "RESULTADOS DA BUSCA" : "RECENTES";
  $("#cards").innerHTML = visible.map(ficha => `<article class="character-card">
    <div class="card-topline"><div class="card-rpg"><span class="card-rpg-dot"></span>${esc(ficha.rpg_name)}</div><div class="card-menu"><button class="card-action" data-open="${esc(ficha.id)}">Abrir</button><button class="card-action" data-edit="${esc(ficha.id)}">Editar</button><button class="card-action" data-delete="${esc(ficha.id)}">Excluir</button></div></div>
    <div class="card-monogram" aria-hidden="true">${esc(initials(ficha.name))}</div><h2>${esc(ficha.name)}</h2><p class="card-history">${esc(ficha.history || "Uma nova história aguarda para ser escrita.")}</p>
    <div class="card-tags">${ficha.tags.slice(0, 3).map(tag => `<span class="tag">${esc(tag)}</span>`).join("")}</div>
    <div class="card-bottom"><span class="card-id" title="Identificador: ${esc(ficha.id)}">ID · ${esc(formatId(ficha.id))}</span><span class="card-arrow" aria-hidden="true">↗</span></div></article>`).join("");
  const isEmpty = visible.length === 0; $("#empty").hidden = !isEmpty; $("#cards").hidden = isEmpty;
  $("#empty-title").textContent = state.fichas.length === 0 ? "Sua próxima aventura começa aqui." : "Nenhuma ficha encontrada.";
  $("#empty-copy").textContent = state.fichas.length === 0 ? (state.rpgs.length ? "Adicione o primeiro personagem à sua biblioteca." : "Crie um RPG e depois adicione sua primeira ficha de personagem.") : "Tente mudar o filtro ou buscar por outro termo.";
  $("#empty-action").hidden = Boolean(state.search || state.rpgFilter);
  $("#empty-action").textContent = state.rpgs.length ? "＋ Criar primeira ficha" : "＋ Criar um RPG";
  $("#nav-library").classList.toggle("active", !state.rpgFilter);
}
function showError(selector, message) { $(selector).textContent = message; }
function openRpgDialog() { $("#rpg-error").textContent = ""; $("#rpg-name").value = ""; $("#rpg-dialog").showModal(); $("#rpg-name").focus(); }
function addRow(type, row = {}) {
  const container = $(`#${type}-rows`); const div = document.createElement("div");
  if (type === "powers") {
    div.className = "power-editor-row";
    div.innerHTML = `<div class="power-editor-fields"><input data-field="name" maxlength="100" aria-label="Poder" placeholder="Nome da habilidade" value="${esc(row.name || "")}"><input data-field="description" maxlength="1000" aria-label="Descrição breve" placeholder="Descrição breve" value="${esc(row.description || "")}"><button type="button" class="remove-row" aria-label="Remover poder">×</button></div><div class="power-effects"></div><button type="button" class="add-power-effect">＋ Modificador de atributo</button>`;
    div.querySelector(".remove-row").addEventListener("click", () => div.remove());
    div.querySelector(".add-power-effect").addEventListener("click", () => addPowerEffect(div.querySelector(".power-effects")));
    (row.effects || []).forEach(effect => addPowerEffect(div.querySelector(".power-effects"), effect));
    container.append(div); return;
  }
  div.className = `data-row ${type === "inventory" ? "inventory-row" : ""}`;
  const fields = type === "attributes" ? [["name", "Atributo"], ["value", "Valor ou fórmula (ex.: (Resistência)*2)"]] : [["name", "Item"], ["quantity", "Qtd."], ["description", "Detalhes"]];
  div.innerHTML = fields.map(([key, placeholder]) => `<input data-field="${key}" maxlength="${key === "description" ? 500 : key === "value" ? 120 : 100}" aria-label="${placeholder}" placeholder="${placeholder}" value="${esc(row[key] || "")}">`).join("") + `<button type="button" class="remove-row" aria-label="Remover linha">×</button>`;
  div.querySelector(".remove-row").addEventListener("click", () => { div.remove(); if (type === "attributes") refreshAttributeOptions(); }); container.append(div);
}
function addPowerEffect(container, effect = {}) {
  const row = document.createElement("div"); row.className = "power-effect-row";
  row.innerHTML = `<input data-effect-field="attribute" list="attribute-options" maxlength="80" aria-label="Atributo modificado" placeholder="Atributo (ex.: Força)" value="${esc(effect.attribute || "")}"><select data-effect-field="operation" aria-label="Operação"><option value="add">Somar +</option><option value="subtract">Subtrair −</option><option value="multiply">Multiplicar ×</option><option value="divide">Dividir ÷</option></select><input data-effect-field="amount" type="number" min="0.01" max="1000000" step="any" aria-label="Valor do modificador" placeholder="Valor" value="${effect.amount ?? ""}"><button type="button" class="remove-row" aria-label="Remover modificador">×</button>`;
  row.querySelector('[data-effect-field="operation"]').value = effect.operation || "add";
  row.querySelector(".remove-row").addEventListener("click", () => row.remove()); container.append(row);
}
function refreshAttributeOptions() {
  const names = [...$("#attributes-rows").querySelectorAll('[data-field="name"]')].map(input => input.value.trim()).filter(Boolean);
  $("#attribute-options").innerHTML = [...new Set(names)].map(name => `<option value="${esc(name)}"></option>`).join("");
}
function readRows(type) {
  if (type === "powers") return [...$("#powers-rows").querySelectorAll(".power-editor-row")].map(row => ({
    name: row.querySelector('[data-field="name"]').value.trim(),
    description: row.querySelector('[data-field="description"]').value.trim(),
    effects: [...row.querySelectorAll(".power-effect-row")].map(effect => ({
      attribute: effect.querySelector('[data-effect-field="attribute"]').value.trim(),
      operation: effect.querySelector('[data-effect-field="operation"]').value,
      amount: Number(effect.querySelector('[data-effect-field="amount"]').value),
    })).filter(effect => effect.attribute || effect.amount),
  })).filter(row => row.name || row.description || row.effects.length);
  return [...$(`#${type}-rows`).querySelectorAll(".data-row")].map(row => Object.fromEntries([...row.querySelectorAll("input")].map(input => [input.dataset.field, input.value.trim()]))).filter(row => Object.values(row).some(Boolean));
}
function resetFichaForm() {
  $("#ficha-id").value = ""; $("#ficha-form").reset(); $("#ficha-modal-title").textContent = "Criar ficha"; $("#ficha-error").textContent = "";
  for (const type of ["attributes", "powers", "inventory"]) $(`#${type}-rows`).replaceChildren();
  refreshAttributeOptions();
}
function openFichaDialog(ficha = null) {
  if (!state.rpgs.length) { openRpgDialog(); notify("Cadastre um RPG antes de criar uma ficha."); return; }
  resetFichaForm();
  if (ficha) {
    $("#ficha-id").value = ficha.id; $("#ficha-modal-title").textContent = "Editar ficha";
    $("#ficha-name").value = ficha.name; $("#ficha-rpg").value = ficha.rpg_id; $("#ficha-history").value = ficha.history;
    $("#ficha-tags").value = ficha.tags.join(", ");
    for (const type of ["attributes", "powers", "inventory"]) ficha[type].forEach(row => addRow(type, row));
  }
  refreshAttributeOptions();
  $("#ficha-dialog").showModal(); $("#ficha-name").focus();
}
const recordLabels = { treino: "Treinos", missao: "Missões", evento: "Eventos" };
function activateProfileTab(kind) {
  if (recordLabels[kind]) state.recordKind = kind;
  document.querySelectorAll("[data-profile-tab]").forEach(tab => {
    const active = tab.dataset.profileTab === kind;
    tab.classList.toggle("active", active); tab.setAttribute("aria-selected", String(active));
  });
  const summary = kind === "summary";
  const powers = kind === "powers";
  $("#profile-summary").hidden = !summary;
  $("#profile-powers-panel").hidden = !powers;
  $("#profile-records-panel").hidden = summary || powers;
  if (powers) renderPowerView();
  if (recordLabels[kind]) {
    $("#records-heading-title").textContent = recordLabels[kind];
    $("#record-kind-label").textContent = `· ${recordLabels[kind].toLocaleLowerCase("pt-BR")}`;
    $("#record-form").hidden = true; renderRecords();
  }
}
function profileStats() {
  const ficha = state.profile;
  const gained = new Map();
  state.records.forEach(record => record.gains.forEach(gain => {
    const key = gain.attribute.trim().toLocaleLowerCase("pt-BR");
    const current = gained.get(key) || { name: gain.attribute, amount: 0 };
    current.amount += Number(gain.amount); gained.set(key, current);
  }));
  const attributes = new Map(ficha.attributes.map(attribute => [attribute.name.toLocaleLowerCase("pt-BR"), attribute]));
  gained.forEach((gain, key) => { if (!attributes.has(key)) attributes.set(key, { name: gain.name, value: "0" }); });
  const fmt = value => Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
  const values = new Map();
  function calculate(attribute, trail = new Set()) {
    const key = attribute.name.toLocaleLowerCase("pt-BR");
    if (values.has(key)) return values.get(key);
    if (trail.has(key)) return null;
    const nextTrail = new Set(trail); nextTrail.add(key);
    let expression = String(attribute.value || "0").replace(/,/g, ".");
    expression = expression.replace(/\(([^()]+)\)/g, (match, ref) => {
      const dependency = attributes.get(ref.trim().toLocaleLowerCase("pt-BR"));
      if (!dependency) return match;
      const result = calculate(dependency, nextTrail);
      return result === null ? "NaN" : String(result);
    });
    if (!/^[\d\s.+\-*/()]+$/.test(expression)) return null;
    try {
      const result = Function(`"use strict"; return (${expression})`)();
      if (!Number.isFinite(result)) return null;
      values.set(key, result); return result;
    } catch { return null; }
  }
  return [...attributes.entries()].map(([key, attribute]) => {
    const calculated = calculate(attribute);
    const bonus = gained.get(key)?.amount || 0;
    return { key, name: attribute.name, baseText: String(attribute.value || "0"), bonus, value: calculated === null ? null : calculated + bonus };
  });
}
function fmtStat(value) { return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2))); }
function renderProfileSummary() {
  const ficha = state.profile;
  const stats = profileStats();
  const attributeMarkup = stats.map(stat => {
    const current = stat.value === null ? (stat.bonus ? `${stat.baseText} + ${fmtStat(stat.bonus)}` : stat.baseText) : fmtStat(stat.value);
    return `<div class="attribute-total"><span>${esc(stat.name)}</span><span class="attribute-values">${esc(stat.baseText)}${stat.baseText !== current ? ` <b>→ ${esc(current)}</b>` : ""}${stat.bonus ? ` <b>(+ ${fmtStat(stat.bonus)})</b>` : ""} <strong>${esc(current)}</strong></span></div>`;
  }).join("") || `<div class="profile-muted">Nenhum atributo cadastrado ainda.</div>`;
  const counts = Object.fromEntries(Object.keys(recordLabels).map(kind => [kind, state.records.filter(record => record.kind === kind).length]));
  $("#profile-summary").innerHTML = `<div class="profile-summary-grid"><section class="profile-summary-block"><h3>Atributos atuais</h3><p>Valores base somados aos ganhos dos registros.</p><div class="attribute-list">${attributeMarkup}</div></section><section class="profile-summary-block"><h3>História</h3><p class="profile-history">${esc(ficha.history || "Ainda não há uma história registrada para este personagem.")}</p><div class="record-counts">${Object.entries(recordLabels).map(([kind, label]) => `<button type="button" class="record-count" data-profile-tab="${kind}"><span>${counts[kind]}</span>${label}</button>`).join("")}</div></section></div>`;
}
const operationSymbols = { add: "+", subtract: "−", multiply: "×", divide: "÷" };
function renderPowerView() {
  const powers = state.profile.powers || [];
  const effectsMarkup = (power, index) => (power.effects || []).length ? `<div class="power-effect-chips">${power.effects.map(effect => `<span>${esc(effect.attribute)} ${operationSymbols[effect.operation] || "+"} ${esc(effect.amount)}</span>`).join("")}</div>` : `<div class="power-effect-chips"><span>Sem modificadores de atributo</span></div>`;
  $("#power-toggles").innerHTML = powers.length ? powers.map((power, index) => `<article class="power-option ${state.activePowers.has(index) ? "selected" : ""}"><button type="button" class="power-toggle" data-activate-power="${index}" aria-pressed="${state.activePowers.has(index)}"><span class="power-check">${state.activePowers.has(index) ? "✓" : ""}</span><span class="power-toggle-name">${esc(power.name)}</span><span class="power-toggle-state">${state.activePowers.has(index) ? "ATIVA" : "ATIVAR"}</span></button>${power.description ? `<p>${esc(power.description)}</p>` : ""}${effectsMarkup(power, index)}</article>`).join("") : `<div class="records-empty"><span>✦</span><strong>Nenhum poder cadastrado nesta ficha.</strong><p>Edite a ficha para adicionar habilidades e seus modificadores.</p></div>`;
  const selected = [...state.activePowers].filter(index => powers[index]).sort((a, b) => a - b);
  $("#active-power-count").textContent = `${selected.length} ${selected.length === 1 ? "ativa" : "ativas"}`;
  const stats = profileStats();
  const values = new Map(stats.map(stat => [stat.key, { ...stat, initialValue: stat.value, value: stat.value }]));
  for (const index of selected) {
    for (const effect of powers[index].effects || []) {
      const key = effect.attribute.trim().toLocaleLowerCase("pt-BR");
      if (!values.has(key)) values.set(key, { key, name: effect.attribute, baseText: "0", bonus: 0, initialValue: 0, value: 0 });
      const stat = values.get(key);
      if (stat.value === null) continue;
      const amount = Number(effect.amount);
      if (effect.operation === "add") stat.value += amount;
      else if (effect.operation === "subtract") stat.value -= amount;
      else if (effect.operation === "multiply") stat.value *= amount;
      else if (effect.operation === "divide") stat.value /= amount;
    }
  }
  $("#modified-attributes").innerHTML = values.size ? [...values.values()].map(stat => {
    const base = stat.initialValue === null ? `${stat.baseText}${stat.bonus ? ` + ${fmtStat(stat.bonus)}` : ""}` : fmtStat(stat.initialValue);
    const changed = stat.value !== null && selected.some(index => (powers[index].effects || []).some(effect => effect.attribute.trim().toLocaleLowerCase("pt-BR") === stat.key));
    return `<div class="modified-attribute ${changed ? "changed" : ""}"><span>${esc(stat.name)}</span><span class="modified-values"><b>${esc(base)}</b><i>→</i><strong>${esc(stat.value === null ? base : fmtStat(stat.value))}</strong></span></div>`;
  }).join("") : `<div class="records-empty"><strong>Cadastre atributos para visualizar seus valores.</strong></div>`;
}
function renderRecords() {
  const entries = state.records.filter(record => record.kind === state.recordKind);
  $("#record-list").innerHTML = entries.length ? entries.map(record => {
    const date = new Date(`${record.occurred_on}T12:00:00`).toLocaleDateString("pt-BR");
    const gains = record.gains.length ? `<div class="record-gains">${record.gains.map(gain => `<span class="tag">${esc(gain.attribute)} +${esc(gain.amount)}</span>`).join("")}</div>` : "";
    return `<article class="record-card"><img class="record-image" src="${esc(record.image_data)}" alt="Imagem do registro de ${esc(record.kind)}"><div class="record-body"><div class="record-meta"><span>${esc(record.kind.toLocaleUpperCase("pt-BR"))}</span><time datetime="${esc(record.occurred_on)}">${esc(date)}</time></div><p>${esc(record.description)}</p>${gains}</div><button type="button" class="record-delete" data-record-delete="${esc(record.id)}" aria-label="Excluir registro">×</button></article>`;
  }).join("") : `<div class="records-empty"><span>✦</span><strong>Nenhum registro de ${recordLabels[state.recordKind].toLocaleLowerCase("pt-BR")} ainda.</strong><p>Adicione o primeiro para guardar esta etapa da jornada.</p></div>`;
}
async function openProfile(ficha) {
  state.profile = ficha; state.records = []; state.activePowers = new Set();
  $("#profile-title").textContent = ficha.name; $("#profile-rpg").textContent = ficha.rpg_name;
  $("#profile-id").textContent = `ID · ${ficha.id}`;
  $("#record-form").reset(); $("#record-form").hidden = true;
  $("#profile-dialog").showModal(); activateProfileTab("summary");
  try {
    state.records = await api(`/api/fichas/${encodeURIComponent(ficha.id)}/registros`);
    renderProfileSummary();
  } catch (error) { $("#profile-summary").innerHTML = `<p class="form-error">${esc(error.message)}</p>`; }
}
function renderRecordGainFields() {
  const container = $("#record-gains");
  const attributes = state.profile?.attributes || [];
  container.innerHTML = attributes.length ? attributes.map((attribute, index) => `<label class="record-gain-row"><span>${esc(attribute.name)}</span><input class="text-input" data-gain-amount="${index}" type="number" min="0.01" max="1000000" step="any" placeholder="—" aria-label="Ganho de ${esc(attribute.name)}"></label>`).join("") : `<p class="field-hint">Esta ficha ainda não tem atributos cadastrados.</p>`;
}
async function readImage(file) {
  if (!file) throw new Error("Selecione uma imagem para o registro.");
  if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("Use uma imagem PNG, JPEG ou WebP.");
  if (file.size > 2_000_000) throw new Error("A imagem deve ter no máximo 2 MB.");
  return new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error("Não foi possível ler a imagem.")); reader.readAsDataURL(file);
  });
}

document.addEventListener("click", async event => {
  const rpgButton = event.target.closest("[data-rpg]");
  if (rpgButton) { state.rpgFilter = state.rpgFilter === rpgButton.dataset.rpg ? "" : rpgButton.dataset.rpg; render(); }
  if (event.target.closest("#nav-library")) { state.rpgFilter = ""; render(); }
  if (event.target.closest("#add-rpg-open")) openRpgDialog();
  if (event.target.closest("#new-ficha")) openFichaDialog();
  if (event.target.closest("#empty-action")) state.rpgs.length ? openFichaDialog() : openRpgDialog();
  const edit = event.target.closest("[data-edit]");
  if (edit) openFichaDialog(state.fichas.find(ficha => ficha.id === edit.dataset.edit));
  const open = event.target.closest("[data-open]");
  if (open) openProfile(state.fichas.find(ficha => ficha.id === open.dataset.open));
  const profileTab = event.target.closest("[data-profile-tab]");
  if (profileTab) activateProfileTab(profileTab.dataset.profileTab);
  const powerToggle = event.target.closest("[data-activate-power]");
  if (powerToggle) {
    const index = Number(powerToggle.dataset.activatePower);
    if (state.activePowers.has(index)) state.activePowers.delete(index); else state.activePowers.add(index);
    renderPowerView();
  }
  if (event.target.closest("#record-create")) {
    $("#record-form").reset(); renderRecordGainFields(); $("#record-error").textContent = "";
    const today = new Date();
    $("#record-date").value = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    $("#record-form").hidden = false; $("#record-description").focus();
  }
  if (event.target.closest("#record-cancel")) { $("#record-form").hidden = true; $("#record-form").reset(); }
  const deleteRecord = event.target.closest("[data-record-delete]");
  if (deleteRecord && confirm("Excluir este registro? Os ganhos associados também deixarão de ser contabilizados.")) {
    try {
      await api(`/api/registros/${encodeURIComponent(deleteRecord.dataset.recordDelete)}`, { method: "DELETE" });
      state.records = await api(`/api/fichas/${encodeURIComponent(state.profile.id)}/registros`);
      renderRecords(); renderProfileSummary(); notify("Registro excluído e ganhos recalculados.");
    } catch (error) { notify(error.message); }
  }
  const remove = event.target.closest("[data-delete]");
  if (remove) {
    const ficha = state.fichas.find(item => item.id === remove.dataset.delete);
    if (ficha && confirm(`Excluir a ficha de ${ficha.name}? Esta ação não pode ser desfeita.`)) {
      try { await api(`/api/fichas/${encodeURIComponent(ficha.id)}`, { method: "DELETE" }); await refresh(); notify("Ficha excluída."); }
      catch (error) { notify(error.message); }
    }
  }
  const close = event.target.closest("[data-close]"); if (close) $(`#${close.dataset.close}`).close();
  const add = event.target.closest("[data-add]"); if (add) addRow(add.dataset.add);
});
$("#filter-rpg").addEventListener("change", event => { state.rpgFilter = event.target.value; render(); });
$("#search").addEventListener("input", event => { state.search = event.target.value; render(); });
document.addEventListener("input", event => { if (event.target.matches('#attributes-rows [data-field="name"]')) refreshAttributeOptions(); });
document.addEventListener("keydown", event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); $("#search").focus(); }
  if (event.key === "Escape") { for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close(); }
});
$("#rpg-form").addEventListener("submit", async event => {
  event.preventDefault(); showError("#rpg-error", "");
  try {
    const created = await api("/api/rpgs", { method: "POST", body: JSON.stringify({ name: $("#rpg-name").value }) });
    $("#rpg-dialog").close(); await refresh(); state.rpgFilter = created.id; render(); notify("RPG cadastrado.");
  } catch (error) { showError("#rpg-error", error.message); }
});
$("#ficha-form").addEventListener("submit", async event => {
  event.preventDefault(); showError("#ficha-error", "");
  const ficha = { name: $("#ficha-name").value, rpg_id: $("#ficha-rpg").value, history: $("#ficha-history").value,
    attributes: readRows("attributes"), powers: readRows("powers"), inventory: readRows("inventory"),
    tags: $("#ficha-tags").value.split(",").map(tag => tag.trim()).filter(Boolean) };
  const id = $("#ficha-id").value;
  try {
    await api(id ? `/api/fichas/${encodeURIComponent(id)}` : "/api/fichas", { method: id ? "PUT" : "POST", body: JSON.stringify(ficha) });
    $("#ficha-dialog").close(); await refresh(); notify(id ? "Ficha atualizada." : "Ficha criada e identificador gerado.");
  } catch (error) { showError("#ficha-error", error.message); }
});
$("#record-form").addEventListener("submit", async event => {
  event.preventDefault(); $("#record-error").textContent = "";
  try {
    const image_data = await readImage($("#record-image").files[0]);
    const gains = [...$("#record-gains").querySelectorAll("[data-gain-amount]")].filter(input => input.value !== "").map(input => ({
      attribute: state.profile.attributes[Number(input.dataset.gainAmount)].name,
      amount: Number(input.value),
    }));
    const payload = { kind: state.recordKind, occurred_on: $("#record-date").value, description: $("#record-description").value, image_data, gains };
    await api(`/api/fichas/${encodeURIComponent(state.profile.id)}/registros`, { method: "POST", body: JSON.stringify(payload) });
    state.records = await api(`/api/fichas/${encodeURIComponent(state.profile.id)}/registros`);
    $("#record-form").hidden = true; $("#record-form").reset(); renderRecords(); renderProfileSummary();
    notify("Registro salvo; atributos atuais recalculados.");
  } catch (error) { $("#record-error").textContent = error.message; }
});
refresh().catch(error => { $("#empty").hidden = false; $("#empty-title").textContent = "Não foi possível carregar a biblioteca."; $("#empty-copy").textContent = error.message; $("#empty-action").hidden = true; });
