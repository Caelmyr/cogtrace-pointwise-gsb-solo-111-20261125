"use strict";

const get = (id) => document.getElementById(id);
const state = {card: null, result: null, photo: null, probe: null, mode: "probe", chart: "sweep", busy: false,
  compare: {referenceAngle: null, suspectAngle: null, draft: null, adopted: null}};
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
  if (state.compare?.adopted) paintCompare(ctx, cfg);
  if (probe) {
    ctx.strokeStyle = "#132637";
    ctx.strokeRect(probe.x - 5, probe.y - 5, 10, 10);
  }
}

function compareRadian(angle) {
  return angle * Math.PI / 180;
}

function paintCompare(ctx, cfg) {
  const adopted = state.compare.adopted;
  const comparison = adopted.result;
  const half = comparison.half_pitch_deg;
  const centers = [
    [comparison.reference_selected_angle, "#42e695"],
    [comparison.suspect_selected_angle + adopted.offset, "#63b8ff"],
  ];
  ctx.save();
  ctx.lineWidth = Math.max(1, cfg.outer / 260);
  ctx.setLineDash([5, 5]);
  for (const [center, color] of centers) {
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.55;
    for (const boundary of [center - half, center + half]) {
      const a = compareRadian(boundary);
      ctx.beginPath();
      ctx.moveTo(cfg.cx, cfg.cy);
      ctx.lineTo(cfg.cx + cfg.outer * Math.cos(a), cfg.cy + cfg.outer * Math.sin(a));
      ctx.stroke();
    }
  }
  ctx.setLineDash([]);
  ctx.globalAlpha = 0.8;
  for (const row of comparison.rows) {
    for (const [edge, color] of [[row.reference, "#42e695"], [row.suspect, "#63b8ff"]]) {
      if (!edge) continue;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(edge.x, edge.y, 2.2, 0, 2 * Math.PI);
      ctx.fill();
    }
  }
  ctx.globalAlpha = 1;
  const point = adopted.point || comparison.point;
  for (const [edge, color, tag] of [[point?.reference, "#42e695", "R"], [point?.suspect, "#63b8ff", "T"]]) {
    if (!edge) continue;
    ctx.strokeStyle = "#f4fbf5";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(edge.x, edge.y, 7, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(edge.x, edge.y, 5, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = "bold 13px monospace";
    ctx.fillText(tag, edge.x + 9, edge.y - 8);
  }
  ctx.restore();
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
  get("single-proof").href = "/cogtrace" + route("/export/proof.png") + savedQuery();
  renderCompare();
  paintSource();
  paintChart();
}

async function open(card) {
  const base = "/cards/" + card.id;
  const photo = new Image();
  photo.src = "/cogtrace" + base + "/capture.png";
  const [result] = await Promise.all([api(base + "/measurement?revision=" + card.revision), photo.decode()]);
  Object.assign(state, {card, result, photo, probe: null,
    compare: {referenceAngle: null, suspectAngle: null, draft: null, adopted: null}});
  get("reference-angle").value = "";
  get("suspect-angle").value = "";
  get("offset-angle").value = "";
  get("comparison-angle").value = "";
  get("compare-proof").hidden = true;
  get("compare-csv").hidden = true;
  get("proof").textContent = "PNG 校样 ↓";
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

function finiteInput(element, label) {
  const raw = String(element.value ?? "").trim();
  if (raw === "") throw new Error(label + "需要填写有效数字。");
  const value = Number(raw);
  if (!Number.isFinite(value)) throw new Error(label + "需要填写有效数字。");
  return value;
}

async function fetchComparison({offset, relativeAngle} = {}) {
  const referenceAngle = finiteInput(get("reference-angle"), "完好齿选角");
  const suspectAngle = finiteInput(get("suspect-angle"), "待查齿选角");
  state.compare.referenceAngle = referenceAngle;
  state.compare.suspectAngle = suspectAngle;
  const params = new URLSearchParams({
    revision: String(state.card.revision),
    reference_angle: String(referenceAngle),
    suspect_angle: String(suspectAngle),
  });
  if (offset !== undefined && offset !== null && offset !== "") {
    if (!Number.isFinite(offset)) throw new Error("采用角偏需要有效数字。");
    params.set("offset", String(offset));
  }
  if (relativeAngle !== undefined && relativeAngle !== null && relativeAngle !== "") {
    if (!Number.isFinite(relativeAngle)) throw new Error("对照角需要有效数字。");
    params.set("comparison_angle", String(relativeAngle));
  }
  return api(route("/compare") + "?" + params.toString());
}

function edgeSourceText(edge) {
  if (!edge) return "无实拍边读数；本角留空";
  return `实际源角 ${edge.actual_angle.toFixed(3)}°，源像素 (${edge.x}, ${edge.y})，半径 ${edge.radius} px`;
}

function sideSummaryText(summary) {
  if (!summary || summary.maximum_difference_px === null) return "无共同实拍边，留空";
  const loss = summary.radial_loss_px ?? 0;
  return `最大半径差 ${summary.maximum_difference_px} px @ ${summary.loss_angle.toFixed(2)}°，正差少料量 ${loss} px`;
}

function renderCompare() {
  const adopted = state.compare?.adopted;
  const result = adopted?.result || state.compare?.draft;
  const offsetNode = get("adopted-offset");
  const lossNode = get("adopted-loss");
  const sideNode = get("adopted-side");
  const badge = get("compare-badge");
  if (!result) {
    offsetNode.textContent = "尚未采用";
    lossNode.textContent = "—";
    sideNode.textContent = "采用后显示左 / 右侧与角度";
    badge.className = "compare-badge";
    badge.textContent = "同一偏移下，缺实拍边的角度会留空，不计少料。";
    get("comparison-detail").textContent =
      "采用角偏后，可点选下表中的对照角；这里会列出两边各自的实际源角、源像素和半径。";
    const readout = get("readout-compare");
    readout.hidden = true;
    readout.textContent = "";
    return;
  }

  offsetNode.textContent = `${result.adopted_offset_deg.toFixed(3)}° / 限 ±${result.max_adjustment_deg.toFixed(3)}°` +
    (adopted ? " · 已采用" : " · 试算建议");
  const offsetInput = get("offset-angle");
  offsetInput.min = String(-result.max_adjustment_deg);
  offsetInput.max = String(result.max_adjustment_deg);
  if (result.radial_loss_px === null || result.radial_loss_px === undefined) {
    lossNode.textContent = "无共同实拍边";
  } else {
    lossNode.textContent = `${result.radial_loss_px} px`;
  }
  const regionName = {left: "左侧", right: "右侧", center: "齿顶 / 0°"};
  const worstFlank = regionName[result.worst_side] || "共同读数不足";
  const worstRegion = regionName[result.worst_region] || "—";
  sideNode.textContent =
    `最大正差区位：${worstRegion}；左右边中差得较多：${worstFlank}。` +
    `左：${sideSummaryText(result.left)}｜右：${sideSummaryText(result.right)}｜齿顶：${sideSummaryText(result.center)}`;
  if (adopted && result.material_loss) {
    badge.className = "compare-badge loss";
    badge.textContent = `少料：正差最大 ${result.radial_loss_px} px；只有完好齿半径大于待查齿半径的正差才标记。`;
  } else if (adopted) {
    badge.className = "compare-badge ok";
    badge.textContent = "未见正差（或共同读数不足），不标少料。";
  } else {
    badge.className = "compare-badge";
    badge.textContent = `试算建议角偏 ${result.suggested_offset_deg.toFixed(3)}°；点「采用角偏并核查对照角」后联动校样。`;
  }
  renderComparisonDetail(adopted?.point || result.point);
  renderCompareTable(result);
}

function renderComparisonDetail(point) {
  const node = get("comparison-detail");
  if (!point) {
    node.textContent = "暂无对照角读数。";
    return;
  }
  const sideName = {left: "左侧扇段", right: "右侧扇段", center: "齿顶 / 0°"}[point.side] || point.side;
  let text = `对照角 ${point.relative_angle.toFixed(3)}°（${sideName}）\n` +
    `完好齿：${edgeSourceText(point.reference)}\n` +
    `待查齿：${edgeSourceText(point.suspect)}\n`;
  if (point.complete) {
    text += `同一角偏下半径差（完好 − 待查）= ${point.difference_px} px；少料量 = ${point.loss_px} px。`;
    text += point.material_loss ? " 这是正差，标记为少料。" : " 这不是正差，不标少料。";
  } else {
    text += "至少一侧缺少实拍边读数；本角结果留空，不算缺料。";
  }
  node.textContent = text;
  const readout = get("readout-compare");
  readout.hidden = false;
  readout.className = "readout-compare" + (point.material_loss ? " loss" : "");
  const comparison = state.compare?.adopted?.result || state.compare?.draft;
  const offsetText = state.compare?.adopted?.offset?.toFixed?.(3) ??
    comparison?.adopted_offset_deg?.toFixed?.(3) ?? "0.000";
  readout.textContent =
    `对照角 ${point.relative_angle.toFixed(2)}° · 角偏 ${offsetText}°\n` +
    `完好齿 ${point.reference ? `${point.reference.actual_angle.toFixed(3)}° / (${point.reference.x},${point.reference.y})` : "缺读数留空"}\n` +
    `待查齿 ${point.suspect ? `${point.suspect.actual_angle.toFixed(3)}° / (${point.suspect.x},${point.suspect.y})` : "缺读数留空"}\n` +
    (point.complete ? `半径差 ${point.difference_px} px；${point.material_loss ? `正差少料 ${point.loss_px} px` : "非正差，不标少料"}`
      : "一侧缺实拍边；留空，不计少料");
}

function edgeCell(edge) {
  if (!edge) return '<span class="missing">缺实拍边 · 留空</span>';
  return `<strong>${edge.radius} px</strong><br><small>${edge.actual_angle.toFixed(3)}° · (${edge.x}, ${edge.y})</small>`;
}

function renderCompareTable(result) {
  const tbody = get("compare-table").querySelector("tbody");
  const selectedAngle = state.compare.adopted?.point?.relative_angle;
  tbody.replaceChildren();
  for (const row of result.rows) {
    const tr = document.createElement("tr");
    if (selectedAngle !== undefined && Math.abs(selectedAngle - row.relative_angle) < 1e-9) tr.className = "selected";
    const angleTd = document.createElement("td");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "angle-link";
    button.dataset.angle = String(row.relative_angle);
    button.textContent = `${row.relative_angle.toFixed(0)}°`;
    angleTd.append(button);

    const refTd = document.createElement("td");
    refTd.innerHTML = edgeCell(row.reference);
    const suspectTd = document.createElement("td");
    suspectTd.innerHTML = edgeCell(row.suspect);

    const diffTd = document.createElement("td");
    if (row.difference_px === null) {
      diffTd.innerHTML = '<span class="missing">留空 · 不计少料</span>';
    } else {
      const span = document.createElement("strong");
      span.className = row.difference_px > 0 ? "loss" : row.difference_px < 0 ? "gain" : "";
      span.textContent = `${row.difference_px > 0 ? "+" : ""}${row.difference_px} px`;
      diffTd.append(span);
      if (row.material_loss) {
        const badge = document.createElement("span");
        badge.className = "mini-badge loss";
        badge.textContent = "少料";
        diffTd.append(badge);
      }
    }
    tr.append(angleTd, refTd, suspectTd, diffTd);
    tbody.append(tr);
  }
}

function comparisonExportUrl(filename) {
  const adopted = state.compare.adopted;
  if (!adopted) return "#";
  const result = adopted.result;
  const params = new URLSearchParams({
    revision: String(state.card.revision),
    reference_angle: String(result.reference_selected_angle),
    suspect_angle: String(result.suspect_selected_angle),
    offset: String(adopted.offset),
  });
  if (adopted.point?.relative_angle !== undefined) {
    params.set("comparison_angle", String(adopted.point.relative_angle));
  }
  return "/cogtrace" + route("/export/" + filename) + "?" + params.toString();
}

function updateComparisonLinks() {
  if (!state.compare.adopted) return;
  const proofUrl = comparisonExportUrl("proof.png");
  get("proof").href = proofUrl;
  get("proof").textContent = "PNG 校样（双齿两处）↓";
  get("compare-proof").href = proofUrl;
  get("compare-proof").hidden = false;
  get("compare-csv").href = comparisonExportUrl("comparison.csv");
  get("compare-csv").hidden = false;
  get("single-proof").href = "/cogtrace" + route("/export/proof.png") + savedQuery();
}

async function runComparisonTrial() {
  const result = await fetchComparison({});
  state.compare.draft = result;
  state.compare.adopted = {offset: result.adopted_offset_deg, result, point: result.point};
  get("offset-angle").value = result.adopted_offset_deg.toFixed(3);
  get("comparison-angle").value = result.point.relative_angle;
  updateComparisonLinks();
  renderCompare();
  paintSource();
  const lossText = result.material_loss ? `，正差少料 ${result.radial_loss_px} px` : "";
  notice(`已对齐并采用角偏 ${result.adopted_offset_deg.toFixed(3)}°${lossText}；也可微调角偏后再次采用。`);
}

async function adoptComparison(angleOverride) {
  const offsetRaw = get("offset-angle").value.trim();
  const offset = offsetRaw === "" ? undefined : finiteInput(get("offset-angle"), "采用角偏");
  const angleInput = get("comparison-angle").value;
  const relativeAngle = angleOverride ?? (angleInput === "" ? undefined : finiteInput(get("comparison-angle"), "对照角"));
  const result = await fetchComparison({offset, relativeAngle});
  state.compare.draft = result;
  state.compare.adopted = {offset: result.adopted_offset_deg, result, point: result.point};
  get("offset-angle").value = result.adopted_offset_deg.toFixed(3);
  get("comparison-angle").value = result.point.relative_angle;
  updateComparisonLinks();
  renderCompare();
  paintSource();
  const lossText = result.material_loss ? `，正差少料 ${result.radial_loss_px} px` : "，未见正差少料";
  notice(`已采用角偏 ${result.adopted_offset_deg.toFixed(3)}°${lossText}。PNG 校样和当前详情可复核两边源角与像素。`);
}

get("remember-reference").addEventListener("click", () => action(async () => {
  const angle = finiteInput(settings.find((field) => field.dataset.setting === "angle"), "核查角度");
  state.compare = {referenceAngle: angle, suspectAngle: state.compare?.suspectAngle ?? null,
    draft: null, adopted: null};
  get("reference-angle").value = angle.toFixed(3);
  state.mode = "mark";
  document.querySelectorAll("[data-mode]").forEach((item) =>
    item.setAttribute("aria-pressed", String(item.id === "mark-mode")));
  renderCompare();
  notice(`已记完好齿方向 ${angle.toFixed(3)}°。请在画布用「选方向」转到待查齿，再点「再记待查齿并试算」。`);
}));

get("remember-suspect").addEventListener("click", () => action(async () => {
  const angle = finiteInput(settings.find((field) => field.dataset.setting === "angle"), "核查角度");
  get("suspect-angle").value = angle.toFixed(3);
  await runComparisonTrial();
}));

get("run-compare").addEventListener("click", () => action(runComparisonTrial));

get("comparison-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(() => adoptComparison());
});

get("comparison-angle").addEventListener("change", () => action(() => {
  const raw = get("comparison-angle").value;
  if (!state.compare.adopted) return adoptComparison(raw === "" ? undefined : Number(raw));
  return adoptComparison(raw === "" ? undefined : Number(raw));
}));

get("compare-table").addEventListener("click", (event) => {
  const button = event.target.closest(".angle-link");
  if (!button || !state.card) return;
  const angle = Number(button.dataset.angle);
  action(() => adoptComparison(angle));
});

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
