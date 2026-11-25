"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, bore: null, mode: "probe", chart: "sweep", busy: false};
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
  paintCompass(ctx);
}

function drawCross(ctx, x, y, color, arm) {
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1.5, ctx.canvas.width / 480);
  ctx.beginPath();
  ctx.moveTo(x - arm, y); ctx.lineTo(x + arm, y);
  ctx.moveTo(x, y - arm); ctx.lineTo(x, y + arm);
  ctx.stroke();
}

function drawWallDot(ctx, x, y, color, outline) {
  const radius = Math.max(3.2, ctx.canvas.width / 170);
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, 2 * Math.PI);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = outline;
  ctx.stroke();
}

function paintCompass(ctx) {
  const {card, result, bore} = state;
  if (!card) return;
  const adopted = result?.compass || (card.compass ? bore?.adopted || card.compass : null);
  const recommended = bore?.recommended;
  const line = Math.max(1.6, card.width / 430);

  if (!adopted && recommended) {
    ctx.save();
    ctx.strokeStyle = "#e0443e";
    ctx.setLineDash([9, 6]);
    ctx.lineWidth = line;
    ctx.beginPath();
    ctx.arc(recommended.gx, recommended.gy, recommended.radius, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.setLineDash([]);
    drawCross(ctx, recommended.gx, recommended.gy, "#e0443e", 8);
    ctx.restore();
    for (const point of bore.wall_points || []) drawWallDot(ctx, point.x, point.y, "rgba(255,45,85,.55)", "#ffffff");
  }

  if (!adopted) return;
  const {gx, gy, radius} = adopted;
  ctx.save();
  ctx.strokeStyle = "#ff3b3b";
  ctx.lineWidth = line + 0.6;
  ctx.beginPath();
  ctx.arc(gx, gy, radius, 0, 2 * Math.PI);
  ctx.stroke();
  ctx.restore();
  drawCross(ctx, gx, gy, "#ff3b3b", 9);
  for (const point of adopted.wall_points || []) drawWallDot(ctx, point.x, point.y, "#ff2d55", "#ffffff");
  const wall = adopted.direction?.wall;
  if (wall) {
    ctx.strokeStyle = "#22c7da";
    ctx.lineWidth = Math.max(1.2, line * 0.75);
    ctx.beginPath();
    ctx.moveTo(gx, gy);
    ctx.lineTo(wall.x, wall.y);
    ctx.stroke();
    drawWallDot(ctx, wall.x, wall.y, "#22c7da", "#06323a");
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

const REVIEW_TEXT = {
  image_edge: "连通开口一直延到图边（图外），不像闭合通孔，请复核裁切/盘心。",
  inner_edge: "连通开口碰到内环边，内环以内没看到完整孔壁，不像闭合通孔，请复核内环半径。",
  seed_not_opening: "已填盘心所在像素不是亮开口，无法从该点起填，请复核盘心或金属亮度上限。",
};

function setText(id, text) {
  const node = get(id);
  if (node) node.textContent = text;
}

function renderMargin() {
  const row = get("compass-margin-row");
  if (!row) return;
  const compass = state.result?.compass;
  row.classList.remove("idle", "blank", "warn");
  if (!compass) {
    row.classList.add("idle");
    row.textContent = "采用中心通孔圆规后，此处按同一核查角度给出规边到实际孔壁的余量；没见到孔壁则留空。";
    return;
  }
  const direction = compass.direction || {};
  const wall = direction.wall;
  if (wall && direction.margin !== null && direction.margin !== undefined) {
    row.innerHTML = "";
    row.append("同一角度规边余量 ");
    const value = document.createElement("b");
    value.id = "compass-margin-value";
    value.textContent = Number(direction.margin).toFixed(2) + " px";
    row.append(value);
    row.append(" → 实测孔壁 (" + wall.x + ", " + wall.y + ")");
    return;
  }
  row.classList.add("blank");
  row.innerHTML = '同一角度规边余量 <b id="compass-margin-value" aria-label="留空"></b>';
  const detail = document.createElement("span");
  detail.className = "margin-blank";
  detail.textContent = "该方向（" + Number(direction.angle ?? state.result.angle).toFixed(2) +
    "°）没见到孔壁（" + (direction.reason === "image_edge" ? "延到图外" :
      direction.reason === "inner_edge" ? "内环边内无金属" : "未见金属") + "），余量留空。";
  row.append(detail);
}

function renderBore() {
  const bore = state.bore;
  const adopted = state.card?.compass || null;
  const adoptButton = get("adopt-compass");
  const clearButton = get("clear-compass");
  const status = get("compass-status");
  if (!bore) {
    if (adoptButton) adoptButton.disabled = true;
    renderMargin();
    return;
  }
  const rec = bore.recommended;
  setText("bore-limit", bore.max_offset);
  const review = get("bore-review");
  if (bore.review && (bore.reasons || []).length) {
    review.hidden = false;
    review.textContent = "提示复核：" + bore.reasons.map((key) => REVIEW_TEXT[key] || key).join(" ");
  } else {
    review.hidden = true;
    review.textContent = "";
  }

  if (!rec) {
    setText("bore-diameter", "无法拟合");
    setText("bore-radius", "盘心起点不是开口");
    setText("bore-center", "—");
    setText("bore-offset", "");
    setText("bore-tight", "—");
    setText("bore-tight-detail", "");
    if (adoptButton) adoptButton.disabled = true;
  } else {
    setText("bore-diameter", rec.diameter + " px");
    setText("bore-radius", "半径 " + rec.radius + " px · 盘心到最近实测金属 " +
      rec.clearance + " px（实测口径约 " + (2 * rec.clearance) + " px）");
    setText("bore-center", "(" + rec.gx + ", " + rec.gy + ")");
    setText("bore-offset", "偏离当前盘心 " + rec.offset + " / 上限 " + bore.max_offset + " px");
    const tight = bore.tightest;
    if (tight) {
      setText("bore-tight", "(" + tight.x + ", " + tight.y + ")");
      setText("bore-tight-detail", "距规心 " + tight.distance + " px · 余量 " +
        tight.margin + " px · " + tight.angle + "°");
    }
    setText("bore-component", bore.component_pixels + " px");
    setText("bore-excluded", "螺栓孔等 " + bore.excluded_components + " 组 / " +
      bore.excluded_pixels + " px 开口未并入");
    if (adoptButton) adoptButton.disabled = false;
  }

  if (adopted) {
    const marks = bore.adopted || {};
    adoptButton.hidden = true;
    clearButton.hidden = false;
    status.hidden = false;
    status.classList.toggle("warn", marks.fits_current_metal === false || marks.within_center_limit === false);
    status.textContent = marks.fits_current_metal === false ?
      "已采用 (" + adopted.gx + ", " + adopted.gy + ") · D " + adopted.diameter +
      " px，但当前标定下会碰到金属，请复核（原盘心/外缘读数未改）。" :
      "已采用规心 (" + adopted.gx + ", " + adopted.gy + ") · 直径 " + adopted.diameter +
      " px；原盘心与外缘读数保持不变，重开卡片仍保留。";
  } else {
    adoptButton.hidden = false;
    clearButton.hidden = true;
    status.hidden = true;
    status.textContent = "";
  }
  renderMargin();
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
  renderBore();
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/cogtrace" + base + "/capture.png";
  const [result, bore] = await Promise.all([
    api(base + "/measurement?revision=" + card.revision),
    api(base + "/bore?revision=" + card.revision).catch(() => null),
    photo.decode(),
  ]);
  Object.assign(state, {card, result, photo, bore, probe: null});
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

async function liveCompassRay(angle) {
  if (!state.card?.compass || angle === "" || !Number.isFinite(Number(angle))) return;
  try {
    const ray = await api(route("/compass/ray") + savedQuery() + "&angle=" + encodeURIComponent(angle));
    if (state.result?.compass) {
      state.result.compass.direction = ray;
      renderMargin();
      paintSource();
    }
  } catch (error) {
    // The saved measurement still refreshes after “保存并核查”.
  }
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
      const angle = state.probe.angle.toFixed(3);
      settings.find((field) => field.dataset.setting === "angle").value = angle;
      notice("已填入原片方向，保存后更新齿缘和校样。");
      await liveCompassRay(angle);
    }
  });
});
const angleField = settings.find((field) => field.dataset.setting === "angle");
if (angleField) angleField.addEventListener("change", () => liveCompassRay(angleField.value));
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
get("adopt-compass").addEventListener("click", () => action(async () => {
  const card = await api(route("/compass/adopt"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision}),
  });
  await open(card);
  notice("已采用推荐圆规；原盘心与外缘读数保持不变。");
}));
get("clear-compass").addEventListener("click", () => action(async () => {
  const card = await api(route("/compass/clear"), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({revision: state.card.revision}),
  });
  await open(card);
  notice("已取消采用圆规。");
}));
document.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
  state.chart = button.dataset.chart;
  document.querySelectorAll("[data-chart]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item === button)));
  if (state.card) paintChart();
}));
action(library);
