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
  for (const [id, filename] of Object.entries({proof: "proof.png", csv: "profile.csv", zip: "observation.zip"})) {
    get(id).href = "/cogtrace" + route("/export/" + filename) + savedQuery();
  }
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/cogtrace" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null});
  get("library").value = card.id;
  show();
}

async function probe(x, y) {
  state.probe = await api(route("/probe") + savedQuery() + "&x=" + x + "&y=" + y);
  get("probe-x").value = x;
  get("probe-y").value = y;
  get("probe-result").textContent = pointLabel(state.probe);
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
action(library);
