const $ = (id) => document.getElementById(id);
const fmt = new Intl.NumberFormat("ru-RU");
const rub = (v) => (v == null ? "—" : fmt.format(v) + " ₽");
const fdate = (iso) => iso ? new Date(iso + "T00:00:00").toLocaleDateString("ru-RU", { day: "numeric", month: "short", year: "numeric" }) : "";
const SOURCE_NAMES = { drom: "Drom.ru", autoru: "Auto.ru", "drom-demo": "Drom (демо)", "autoru-demo": "Auto.ru (демо)" };
const srcName = (s) => SOURCE_NAMES[s] || s;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let priceChart, countChart, lastParams;

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function fillSelect(sel, items, placeholder) {
  sel.innerHTML = (placeholder ? `<option value="">${placeholder}</option>` : "") +
    items.map((i) => `<option value="${esc(i.value)}">${esc(i.label)}</option>`).join("");
  sel.disabled = false;
}

function css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

function isoDate(d) { return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }

function setPreset(days) {
  const to = new Date();
  const from = new Date(); from.setDate(to.getDate() - days);
  $("from").value = isoDate(from); $("to").value = isoDate(to);
  document.querySelectorAll(".presets button").forEach((b) => b.classList.toggle("on", +b.dataset.days === days));
}

async function loadBrands() {
  const brands = await api("/api/brands");
  fillSelect($("brand"), brands.map((b) => ({ value: b.id, label: b.name })), "Выберите марку");
}

async function onBrand() {
  const id = $("brand").value;
  ["model", "generation", "trim"].forEach((k) => { $(k).disabled = true; });
  $("model").innerHTML = "";
  if (!id) return;
  const models = await api(`/api/brands/${id}/models`);
  window._models = Object.fromEntries(models.map((m) => [m.id, m]));
  fillSelect($("model"), models.map((m) => ({ value: m.id, label: m.name })), "Выберите модель");
}

async function onModel() {
  const id = $("model").value;
  $("tracked").disabled = $("collectNow").disabled = !id;
  if (!id) return;
  $("tracked").checked = !!window._models[id]?.tracked;
  const gens = await api(`/api/models/${id}/generations`);
  fillSelect($("generation"), gens.map((g) => ({ value: g.id, label: g.name })), "Все поколения");
  await loadTrims();
}

async function loadTrims() {
  const id = $("model").value;
  const gen = $("generation").value;
  const trims = await api(`/api/models/${id}/trims` + (gen ? `?generation_id=${gen}` : ""));
  fillSelect($("trim"), trims.map((t) => ({ value: t.key, label: `${t.label} (${t.count})` })),
    trims.length ? "Все комплектации" : "Нет данных — соберите объявления");
}

async function loadSources() {
  const sources = await api("/api/sources");
  $("sources").innerHTML = "<legend>Площадки</legend>" + (sources.length
    ? sources.map((s) => `<label class="check"><input type="checkbox" value="${esc(s)}" checked> ${esc(srcName(s))}</label>`).join("")
    : '<span class="empty">данных пока нет</span>');
}

function params() {
  const p = new URLSearchParams({ model_id: $("model").value, date_from: $("from").value, date_to: $("to").value,
    exclude_outliers: $("outliers").checked, use_published: $("published").checked });
  if ($("generation").value) p.set("generation_id", $("generation").value);
  if ($("trim").value) p.set("trim_key", $("trim").value);
  if ($("yearFrom").value) p.set("year_from", $("yearFrom").value);
  if ($("yearTo").value) p.set("year_to", $("yearTo").value);
  const boxes = [...$("sources").querySelectorAll("input")];
  if (boxes.some((b) => !b.checked)) boxes.filter((b) => b.checked).forEach((b) => p.append("sources", b.value));
  return p;
}

function status(text, err) { $("status").textContent = text; $("status").className = "status" + (err ? " err" : ""); }

async function run() {
  if (!$("model").value) return status("Выберите марку и модель", true);
  status("Считаю…");
  lastParams = params();
  try {
    const data = await api("/api/analytics?" + lastParams);
    render(data);
  } catch (e) { status("Ошибка: " + e.message, true); }
}

function listingLink(l) {
  const where = [l.year && `${l.year} г.`, l.city, srcName(l.source)].filter(Boolean).join(", ");
  return `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(where)}</a>${l.date ? ", " + fdate(l.date) : ""}`;
}

function render(d) {
  const s = d.summary;
  if (!s) {
    $("result").hidden = true;
    return status("За выбранный период нет объявлений по этим параметрам. Отметьте модель для отслеживания и запустите сбор.");
  }
  $("result").hidden = false;
  const m = d.meta;
  status(`Период: ${fdate(d.query.date_from)} — ${fdate(d.query.date_to)}; ` +
    (m.outliers_excluded ? `исключено выбросов: ${m.outliers_excluded}; ` : "") +
    (m.first_snapshot ? `снимки цен: ${fdate(m.first_snapshot)} — ${fdate(m.last_snapshot)}` : ""));

  $("kAvg").textContent = rub(s.avg);
  $("kMed").textContent = `медиана ${rub(s.median)}`;
  $("kMin").textContent = rub(s.min_listing.price);
  $("kMinNote").innerHTML = listingLink(s.min_listing) + `<br>мин. средняя за день: ${rub(s.lowest_day.avg)} (${fdate(s.lowest_day.date)})`;
  $("kMax").textContent = rub(s.max_listing.price);
  $("kMaxNote").innerHTML = listingLink(s.max_listing) + `<br>пик средней за день: ${rub(s.peak_day.avg)} (${fdate(s.peak_day.date)})`;
  if (s.change && s.change.pct != null) {
    const c = s.change, sign = c.pct > 0 ? "+" : "";
    $("kChg").innerHTML = `<span class="${c.pct > 0 ? "up" : c.pct < 0 ? "down" : ""}">${c.pct > 0 ? "▲" : c.pct < 0 ? "▼" : "■"} ${sign}${c.pct}%</span>`;
    $("kChgNote").textContent = `${rub(c.start)} → ${rub(c.end)} (окна по ${c.window_days} дн.)`;
  } else { $("kChg").textContent = "—"; $("kChgNote").textContent = "мало данных"; }
  $("kCnt").textContent = fmt.format(m.listings);
  $("kCntNote").textContent = [s.avg_mileage_km != null && `средний пробег ${fmt.format(s.avg_mileage_km)} км`,
    s.price_drops && `снижали цену: ${s.price_drops}`].filter(Boolean).join(" · ");

  $("chartHint").textContent = m.estimated_days
    ? `Пунктир — дни до начала сбора, достроенные по дате публикации объявлений (оценка, ${m.estimated_days} дн.). Заливка — диапазон мин–макс.`
    : "Заливка — диапазон мин–макс цен объявлений в продаже на каждый день.";
  drawCharts(d.series);
  $("seriesTable").innerHTML = table(["Дата", "Объявл.", "Средняя", "Медиана", "Мин", "Макс"],
    d.series.map((r) => [fdate(r.date) + (r.estimated ? " *" : ""), r.count, rub(r.avg), rub(r.median), rub(r.min), rub(r.max)]), [1, 2, 3, 4, 5]);
  $("bySource").innerHTML = table(["Площадка", "Объявл.", "Средняя", "Медиана", "Мин", "Макс"],
    d.by_source.map((r) => [srcName(r.source), r.count, rub(r.avg), rub(r.median), rub(r.min), rub(r.max)]), [1, 2, 3, 4, 5]);
  $("byYear").innerHTML = table(["Год", "Объявл.", "Средняя", "Медиана"],
    d.by_year.map((r) => [r.year, r.count, rub(r.avg), rub(r.median)]), [1, 2, 3]);
  const lrow = (l) => [`<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.year || "")} ${esc(l.trim || l.title || "")}</a>`,
    l.mileage_km != null ? fmt.format(l.mileage_km) + " км" : "—", esc(l.city || ""), rub(l.price)];
  $("cheapest").innerHTML = table(["Авто", "Пробег", "Город", "Цена"], d.cheapest.map(lrow), [1, 3], true);
  $("priciest").innerHTML = table(["Авто", "Пробег", "Город", "Цена"], d.priciest.map(lrow), [1, 3], true);
  $("csv").href = "/api/analytics.csv?" + lastParams;
}

function table(head, rows, numCols = [], raw = false) {
  if (!rows.length) return '<p class="empty">Нет данных</p>';
  const cls = (i, tag) => [numCols.includes(i) && "num", raw && tag === "td" && i === 0 && "wrap"].filter(Boolean).join(" ");
  const cell = (v, i, tag) => `<${tag}${cls(i, tag) ? ` class="${cls(i, tag)}"` : ""}>${raw || tag === "th" ? v : esc(v)}</${tag}>`;
  return `<table><thead><tr>${head.map((h, i) => cell(h, i, "th")).join("")}</tr></thead><tbody>` +
    rows.map((r) => `<tr>${r.map((v, i) => cell(v, i, "td")).join("")}</tr>`).join("") + "</tbody></table>";
}

function drawCharts(series) {
  const labels = series.map((r) => fdate(r.date));
  const est = series.map((r) => r.estimated);
  const dash = (ctx) => (est[ctx.p1DataIndex] ? [5, 4] : undefined);
  const grid = css("--grid"), muted = css("--text-muted"), text = css("--text-secondary");
  const axis = { grid: { color: grid }, ticks: { color: muted, maxRotation: 0, autoSkipPadding: 16 }, border: { display: false } };
  const tooltip = { mode: "index", intersect: false, callbacks: { label: (c) => ` ${c.dataset.label}: ${c.dataset.yAxisID === "n" ? fmt.format(c.parsed.y) : rub(c.parsed.y)}` } };
  const point = { pointRadius: 0, pointHoverRadius: 5, pointHitRadius: 12 };

  priceChart?.destroy();
  priceChart = new Chart($("priceChart"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Макс", data: series.map((r) => r.max), borderWidth: 0, backgroundColor: css("--band"), fill: "+1", ...point, order: 3 },
      { label: "Мин", data: series.map((r) => r.min), borderWidth: 0, backgroundColor: css("--band"), fill: false, ...point, order: 3 },
      { label: "Средняя", data: series.map((r) => r.avg), borderColor: css("--series-1"), backgroundColor: css("--series-1"), borderWidth: 2, tension: .25, segment: { borderDash: dash }, ...point },
      { label: "Медиана", data: series.map((r) => r.median), borderColor: css("--series-2"), backgroundColor: css("--series-2"), borderWidth: 2, tension: .25, segment: { borderDash: dash }, ...point },
    ] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: text, boxWidth: 12, boxHeight: 2, filter: (i) => !["Мин", "Макс"].includes(i.text) || i.text === "Макс",
        generateLabels: (ch) => Chart.defaults.plugins.legend.labels.generateLabels(ch).map((l) => (l.text === "Макс" ? { ...l, text: "Диапазон мин–макс", fillStyle: css("--band"), strokeStyle: css("--band") } : l)) } }, tooltip },
      scales: { x: axis, y: { ...axis, ticks: { ...axis.ticks, callback: (v) => fmt.format(v / 1000) + " тыс." } } } },
  });

  countChart?.destroy();
  countChart = new Chart($("countChart"), {
    type: "bar",
    data: { labels, datasets: [{ label: "Объявлений", yAxisID: "n", data: series.map((r) => r.count), backgroundColor: css("--series-1"), borderRadius: 4, maxBarThickness: 18 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip },
      scales: { x: { ...axis, grid: { display: false } }, n: { ...axis, beginAtZero: true, position: "left" } } },
  });
}

async function loadRuns() {
  const r = await api("/api/collect/runs");
  $("collectNow").textContent = r.running ? "Идёт сбор…" : "Собрать сейчас";
  $("runs").innerHTML = r.runs.length ? table(["Время", "Площадка", "Модель", "Статус", "Найдено", "Комментарий"],
    r.runs.map((x) => [new Date(x.started_at).toLocaleString("ru-RU"), esc(srcName(x.source)), esc(x.model),
      `<span class="badge ${esc(x.status)}">${esc(x.status)}</span>`, x.found, esc(x.message || "")]), [4], true)
    : '<p class="empty">Сбор ещё не запускался. Ежедневный сбор идёт по отслеживаемым моделям; можно запустить вручную.</p>';
  if (r.running) setTimeout(loadRuns, 5000);
}

$("brand").addEventListener("change", onBrand);
$("model").addEventListener("change", onModel);
$("generation").addEventListener("change", loadTrims);
$("run").addEventListener("click", run);
document.querySelectorAll(".presets button").forEach((b) => b.addEventListener("click", () => setPreset(+b.dataset.days)));
["from", "to"].forEach((k) => $(k).addEventListener("change", () => document.querySelectorAll(".presets button").forEach((b) => b.classList.remove("on"))));
$("toggleTable").addEventListener("click", () => { $("seriesTable").hidden = !$("seriesTable").hidden; });
$("tracked").addEventListener("change", async () => {
  const id = $("model").value;
  await api(`/api/models/${id}/track`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tracked: $("tracked").checked }) });
  window._models[id].tracked = $("tracked").checked;
});
$("collectNow").addEventListener("click", async () => {
  try {
    await api("/api/collect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_ids: [+$("model").value] }) });
    setTimeout(loadRuns, 1000);
  } catch (e) { status(e.message, true); }
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => lastParams && run());

setPreset(30);
loadBrands(); loadSources(); loadRuns();
