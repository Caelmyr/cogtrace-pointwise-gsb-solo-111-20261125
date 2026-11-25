"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", chart: "sweep", busy: false};
const settings = [...document.querySelectorAll("[data-setting]")];

async function api(path, options) {
  const response = await fetch("/cogtrace" + path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "请求失败，请检查输入后重试。");
  return body;
}

function route(tail) {
  return "/cards/" + state.card.id + tail;
}

function savedQuery() {
  return "?revision=" + state.card.revision;
}

function notice(message, target = "notice") {
  const element = get(target);
  element.textContent = message;
  element.hidden = !message;
}

async function action(work, target = "notice") {
  if (state.busy) return;
  state.busy = true;
  document.querySelectorAll("button, select").forEach((node) => { node.disabled = true; });
  notice("", target);
  try {
    await work();
  } catch (error) {
    notice(error.message, target);
  } finally {
    state.busy = false;
    document.querySelectorAll("button, select").forEach((node) => { node.disabled = false; });
  }
}

async function library() {
  const {cards} = await api("/cards");
  const select = get("library");
  select.replaceChildren(new Option("选取已存卡片", ""));
  for (const card of cards) select.append(new Option(card.name, card.id));
  select.value = state.card?.id || "";
}

function paintSource() {
  const canvas = get("capture");
  const ctx = canvas.getContext("2d");
  const {photo, card, probe} = state;
  if (!photo) return;
  canvas.width = card.width;
  canvas.height = card.height;
  ctx.drawImage(photo, 0, 0);
  const cfg = card.settings;
  ctx.lineWidth = Math.max(1, card.width / 550);
  ctx.strokeStyle = "#4f796e";
  ctx.setLineDash([6, 5]);
  for (const radius of [cfg.inner, cfg.outer]) {
    ctx.beginPath();
    ctx.arc(cfg.cx, cfg.cy, radius, 0, 2 * Math.PI);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  paintToothEvidence(ctx, cfg);
  const angle = state.result.angle * Math.PI / 180;
  ctx.strokeStyle = "#bb6622";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cfg.cx, cfg.cy);
  ctx.lineTo(cfg.cx + cfg.outer * Math.cos(angle), cfg.cy + cfg.outer * Math.sin(angle));
  ctx.stroke();
  const drawn = state.result.reading;
  if (drawn) {
    ctx.fillStyle = "#bd6622";
    ctx.beginPath();
    ctx.arc(drawn.x, drawn.y, 4, 0, 2 * Math.PI);
    ctx.fill();
  }
  if (probe) {
    ctx.strokeStyle = "#132637";
    ctx.strokeRect(probe.x - 5, probe.y - 5, 10, 10);
  }
}

function paintChart() {
  const canvas = get("chart");
  const ctx = canvas.getContext("2d");
  const {width, height} = canvas;
  const {result, card} = state;
  const sweep = state.chart === "sweep";
  const cfg = card.settings;
  const xMin = sweep ? 0 : cfg.inner;
  const xMax = sweep ? 359 : cfg.outer;
  const yMin = sweep ? cfg.inner : 0;
  const yMax = sweep ? cfg.outer : 255;
  const xAt = (x) => 40 + (width - 66) * (x - xMin) / (xMax - xMin);
  const yAt = (y) => height - 25 - (height - 42) * (y - yMin) / (yMax - yMin);
  get("chart-title").textContent = sweep ? "周向齿缘" : "当前径线";
  get("chart-caption").textContent = sweep ? "环带内最外实测暗像素 · °" : "原片亮度 · 径向距离 px";
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fbfdf9";
  ctx.fillRect(0, 0, width, height);
  ctx.font = "12px monospace";
  ctx.fillStyle = "#53685b";
  ctx.strokeStyle = "#c6d4c7";
  for (const level of [yMin, Math.round((yMin + yMax) / 2), yMax]) {
    ctx.fillText(level, 5, yAt(level) + 3);
    ctx.beginPath();
    ctx.moveTo(xAt(xMin), yAt(level));
    ctx.lineTo(xAt(xMax), yAt(level));
    ctx.stroke();
  }
  ctx.fillText(String(xMin), xAt(xMin), height - 6);
  ctx.fillText(String(xMax), width - 35, height - 6);
  ctx.strokeStyle = "#366b5d";
  ctx.lineWidth = 2;
  ctx.beginPath();
  let started = false;
  const values = sweep ? result.sweep.map((row) => [row.angle, row.edge?.radius]) :
    result.profile.map((row) => [row.r, row.brightness]);
  for (const [x, y] of values) {
    if (y === undefined) {
      started = false;
      continue;
    }
    if (started) ctx.lineTo(xAt(x), yAt(y));
    else ctx.moveTo(xAt(x), yAt(y));
    started = true;
  }
  ctx.stroke();
  if (sweep) {
    for (const tooth of result.teeth || []) {
      if (!tooth.has_evidence || tooth.source_angle === null || tooth.radius === null) continue;
      ctx.fillStyle = "#2f7f9b";
      ctx.beginPath();
      ctx.arc(xAt(tooth.source_angle), yAt(tooth.radius), 3.2, 0, 2 * Math.PI);
      ctx.fill();
    }
    ctx.strokeStyle = "#bd6622";
    ctx.beginPath();
    ctx.moveTo(xAt(Math.min(result.angle, 359)), yAt(yMin));
    ctx.lineTo(xAt(Math.min(result.angle, 359)), yAt(yMax));
    ctx.stroke();
  } else {
    ctx.strokeStyle = "#bd6622";
    ctx.setLineDash([6,4]);
    ctx.beginPath();
    ctx.moveTo(xAt(xMin), yAt(cfg.cutoff));
    ctx.lineTo(xAt(xMax), yAt(cfg.cutoff));
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

function toothForDirection(angle) {
  const teeth = state.result?.teeth;
  const anchor = state.card?.settings?.first_tooth_angle;
  if (!teeth?.length || anchor === null || anchor === undefined || !Number.isFinite(Number(angle))) return null;
  const pitch = 360 / teeth.length;
  let clockwise = (Number(angle) - Number(anchor)) % 360;
  if (clockwise < 0) clockwise += 360;
  const index = Math.floor(clockwise / pitch + 0.5) % teeth.length;
  return teeth[index];
}

function updateToothReadout(angle = state.directionAngle ?? state.result?.angle) {
  const element = get("tooth-position");
  if (!element || !state.result) return;
  const anchor = state.card?.settings?.first_tooth_angle;
  if (anchor === null || anchor === undefined) {
    element.textContent = "采用一号齿后，这里显示当前方向对应的齿位号。";
    element.dataset.adopted = "false";
    delete element.dataset.toothIndex;
    delete element.dataset.state;
    return;
  }
  const tooth = toothForDirection(angle);
  if (!tooth) {
    element.textContent = "已采用一号齿，但暂时无法计算齿位号。";
    element.dataset.adopted = "true";
    delete element.dataset.toothIndex;
    delete element.dataset.state;
    return;
  }
  element.dataset.adopted = "true";
  element.dataset.toothIndex = String(tooth.index);
  element.dataset.tooth = String(tooth.index);
  element.dataset.state = tooth.state || tooth.status;
  element.dataset.status = tooth.status;
  if (tooth.has_evidence && tooth.evidence) {
    element.textContent = `当前方向齿位号：第 ${tooth.index} 齿 · 实见证据 · 源角 ${tooth.source_angle.toFixed(2)}° · r=${tooth.radius} px`;
  } else {
    element.textContent = `当前方向齿位号：第 ${tooth.index} 齿 · 缺证（保留编号，无实测源点）`;
  }
  document.querySelectorAll(".tooth-item").forEach((item) => {
    item.dataset.current = String(Number(item.dataset.toothIndex) === tooth.index);
  });
}

function renderTeeth() {
  const list = get("tooth-list");
  const anchorState = get("anchor-state");
  const summary = get("tooth-summary");
  const anchor = state.card?.settings?.first_tooth_angle;
  const teeth = state.result?.teeth || [];
  list.replaceChildren();

  if (anchor === null || anchor === undefined || !teeth.length) {
    anchorState.textContent = "尚未采用一号齿";
    summary.textContent = "";
    list.hidden = true;
    updateToothReadout();
    return;
  }

  anchorState.textContent = `一号齿方向 ${Number(anchor).toFixed(3)}° · 顺时针编号`;
  const seen = state.result.seen_count ?? teeth.filter((tooth) => tooth.has_evidence).length;
  summary.textContent = `已配实证 ${seen} / ${teeth.length} · 缺证 ${teeth.length - seen}`;
  list.hidden = false;
  const fragment = document.createDocumentFragment();
  for (const tooth of teeth) {
    const item = document.createElement("li");
    item.className = `tooth tooth-item is-${tooth.state || tooth.status} ${tooth.has_evidence ? "seen matched evidence-seen has-evidence" : "missing evidence-missing no-evidence"}`;
    item.dataset.toothIndex = String(tooth.index);
    item.dataset.toothNumber = String(tooth.index);
    item.dataset.tooth = String(tooth.index);
    item.dataset.index = String(tooth.index);
    item.dataset.state = tooth.state || tooth.status;
    item.dataset.status = tooth.status;
    item.dataset.matchStatus = tooth.match_status || (tooth.matched ? "matched" : "missing");
    item.dataset.evidence = String(Boolean(tooth.has_evidence));
    item.id = `tooth-${tooth.index}`;
    item.setAttribute("aria-label", `齿位 ${tooth.index}，${tooth.has_evidence ? "实见证据" : "缺证"}`);

    const number = document.createElement("span");
    number.className = "tooth-number";
    number.textContent = `第 ${tooth.index} 齿`;
    const status = document.createElement("span");
    status.className = "tooth-status";
    status.textContent = tooth.has_evidence ? "实见" : "缺证";
    const detail = document.createElement("span");
    detail.className = "tooth-detail";
    if (tooth.has_evidence) {
      detail.textContent = `源角 ${tooth.source_angle.toFixed(2)}° · r=${tooth.radius} · ${tooth.x},${tooth.y}`;
    } else {
      detail.textContent = "仅保留编号与状态";
    }
    item.append(number, status, detail);
    fragment.append(item);
  }
  list.append(fragment);
  updateToothReadout();
}

function paintToothEvidence(ctx, cfg) {
  const teeth = state.result?.teeth || [];
  if (!teeth.length) return;
  const current = toothForDirection(state.directionAngle ?? state.result.angle);
  ctx.font = `${Math.max(11, Math.round(state.card.width / 58))}px monospace`;
  for (const tooth of teeth) {
    const evidence = tooth.evidence;
    if (!evidence || evidence.x === null || evidence.y === null) continue;
    const isCurrent = current?.index === tooth.index;
    const radians = (evidence.source_angle ?? evidence.angle) * Math.PI / 180;
    ctx.beginPath();
    ctx.moveTo(cfg.cx, cfg.cy);
    ctx.lineTo(cfg.cx + cfg.outer * Math.cos(radians), cfg.cy + cfg.outer * Math.sin(radians));
    ctx.strokeStyle = isCurrent ? "#0f668d" : "rgba(47, 127, 155, .42)";
    ctx.lineWidth = isCurrent ? 3 : 1;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(evidence.x, evidence.y, isCurrent ? 5 : 3, 0, 2 * Math.PI);
    ctx.fillStyle = isCurrent ? "#0f668d" : "#2f7f9b";
    ctx.fill();
    ctx.fillStyle = "#174b61";
    ctx.fillText(String(tooth.index), evidence.x + 6, Math.max(12, evidence.y - 6));
  }
}

function pointLabel(point) {
  return "(" + point.x + ", " + point.y + ") · " + point.angle.toFixed(2) + "° · " +
    point.radius.toFixed(1) + " px · " + point.brightness.toFixed(1);
}

function show() {
  const {card, result} = state;
  get("workspace").hidden = false;
  get("empty").hidden = true;
  get("origin").textContent = (card.synthetic ? "合成练习图" : "导入原片") + " · 修订 " + card.revision;
  get("card-title").textContent = card.name;
  get("dimensions").textContent = card.width + " × " + card.height + " px · " + card.photo_name;
  get("name").value = card.name;
  for (const field of settings) field.value = card.settings[field.dataset.setting];
  get("probe-x").max = card.width - 1;
  get("probe-y").max = card.height - 1;
  get("probe-x").value = state.probe?.x ?? result.reading?.x ?? Math.round(card.settings.cx);
  get("probe-y").value = state.probe?.y ?? result.reading?.y ?? Math.round(card.settings.cy);
  get("probe-result").textContent = state.probe ? pointLabel(state.probe) : "选择原片像素";
  const edge = result.reading;
  get("edge-radius").textContent = edge?.radius ?? "—";
  get("radius-detail").textContent = edge ? "px" : "环带内未见齿缘";
  get("measurement-state").textContent = result.angle.toFixed(2) + "°";
  get("selected-level").textContent = (edge ? "实际源点 (" + edge.x + ", " + edge.y + ") · " : "") +
    "手填齿距 " + result.manual_pitch_deg.toFixed(2) + "°";
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", "teeth-csv": "teeth.csv", zip: "observation.zip"})) {
    get(id).href = "/cogtrace" + route("/export/" + filename) + savedQuery();
  }
  state.directionAngle = state.probe?.angle ?? result.angle;
  renderTeeth();
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/cogtrace" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null});
  try { localStorage.setItem("cogtrace:lastCard", card.id); } catch (_) { /* storage is optional */ }
  get("library").value = card.id;
  show();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  state.directionAngle = state.probe.angle;
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
  updateToothReadout(state.probe.angle);
  paintSource();
}

get("practice").addEventListener("click", () => action(async () => {
  await open(await api("/practice", {method: "POST"}));
  await library();
}));

get("library").addEventListener("change", () => {
  if (get("library").value) action(async () => open(await api("/cards/" + get("library").value)));
});
get("open-import").addEventListener("click", () => {
  notice("", "import-notice");
  get("import").showModal();
});
get("cancel-import").addEventListener("click", () => get("import").close());
get("upload").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const card = await api("/cards", {method: "POST", body: new FormData(event.target)});
    await open(card);
    await library();
    get("import").close();
    event.target.reset();
  }, "import-notice");
});
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => {
  state.mode = button.dataset.mode;
  document.querySelectorAll("[data-mode]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
}));
get("capture").addEventListener("click", (event) => {
  if (!state.card) return;
  const canvas = event.currentTarget;
  const rect = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(canvas.width - 1, Math.floor((event.clientX - rect.left) * canvas.width / rect.width)));
  const y = Math.max(0, Math.min(canvas.height - 1, Math.floor((event.clientY - rect.top) * canvas.height / rect.height)));
  action(async () => {
    await probe(x, y);
    if (state.mode === "mark") {
      settings.find((field) => field.dataset.setting === "angle").value = state.probe.angle.toFixed(3);
      notice("已填入原片方向，保存后更新齿缘和校样。");
    }
  });
});
get("probe-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => probe(get("probe-x").value, get("probe-y").value));
});
get("calibration").addEventListener("submit", (event) => {
  event.preventDefault();
  action(async () => {
    const fields = Object.fromEntries(settings.map((field) => [field.dataset.setting, Number(field.value)]));
    const card = await api(route(""), {
      method: "PATCH", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({revision: state.card.revision, name: get("name").value, settings: fields}),
    });
    await open(card);
    await library();
  });
});
get("adopt-tooth").addEventListener("click", () => action(async () => {
  const angleField = settings.find((field) => field.dataset.setting === "angle");
  if (angleField.value.trim() === "") throw new Error("请先填写有效的核查角度，或使用「选方向」点选实见齿尖。");
  const selectedAngle = Number(angleField.value);
  if (!Number.isFinite(selectedAngle)) throw new Error("请先填写有效的核查角度，或使用「选方向」点选实见齿尖。");
  const firstToothAngle = ((selectedAngle % 360) + 360) % 360;
  const fields = Object.fromEntries(settings.map((field) => [field.dataset.setting, Number(field.value)]));
  fields.angle = firstToothAngle;
  fields.first_tooth_angle = firstToothAngle;
  const card = await api(route(""), {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      revision: state.card.revision,
      name: get("name").value,
      settings: fields,
    }),
  });
  await open(card);
  await library();
  notice(`已采用 ${firstToothAngle.toFixed(3)}° 方向为一号齿；之后修改核查角度不会移动编号。`);
}));
settings.find((field) => field.dataset.setting === "angle").addEventListener("input", (event) => {
  const angle = Number(event.currentTarget.value);
  if (!state.card || !Number.isFinite(angle)) return;
  state.directionAngle = ((angle % 360) + 360) % 360;
  updateToothReadout(state.directionAngle);
  paintSource();
});
get("prepare").addEventListener("click", () => action(async () => {
  const {url} = await api(route("/prepare") + savedQuery(), {method: "POST"});
  location.assign(url);
}));
document.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
  state.chart = button.dataset.chart;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
  if (state.card) paintChart();
}));
action(async () => {
  await library();
  let lastCard = null;
  try { lastCard = localStorage.getItem("cogtrace:lastCard"); } catch (_) { /* optional */ }
  if (lastCard && Array.from(get("library").options).some((option) => option.value === lastCard)) {
    try {
      await open(await api("/cards/" + lastCard));
    } catch (_) {
      try { localStorage.removeItem("cogtrace:lastCard"); } catch (__) { /* optional */ }
    }
  }
});
