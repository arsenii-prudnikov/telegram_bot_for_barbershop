const START_HOUR = 8, END_HOUR = 21, PX_PER_MIN = 1.4, PAD = 12;
const euro = v => v.toLocaleString("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const $ = id => document.getElementById(id);
let current = new URLSearchParams(location.search).get("d") || null;

const minutes = iso => { const d = new Date(iso); return d.getHours() * 60 + d.getMinutes(); };
const yPos = m => PAD + (m - START_HOUR * 60) * PX_PER_MIN;
const hm = s => { const [h, m] = s.split(":").map(Number); return h * 60 + m; };
const localDate = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function loadDay() {
  const data = await api("/api/day" + (current ? `?d=${current}` : ""));
  current = data.date;
  $("day-label").textContent = data.label;
  const tl = $("timeline");
  const height = (END_HOUR - START_HOUR) * 60 * PX_PER_MIN + 2 * PAD;
  tl.style.setProperty("--cols", data.masters.length);
  tl.innerHTML = `<div class="tl-head"></div>` + data.masters.map(m => `<div class="tl-head">${m.emoji} ${esc(m.name)}</div>`).join("");

  const hours = document.createElement("div");
  hours.className = "tl-hours";
  hours.style.height = height + "px";
  for (let h = START_HOUR; h <= END_HOUR; h++) hours.innerHTML += `<div style="top:${yPos(h * 60)}px">${h}:00</div>`;
  tl.appendChild(hours);

  for (const m of data.masters) {
    const col = document.createElement("div");
    col.className = "tl-col";
    col.style.height = height + "px";
    for (let h = START_HOUR; h <= END_HOUR; h++) col.innerHTML += `<div class="tl-line" style="top:${yPos(h * 60)}px"></div>`;
    // nicht gearbeitete Zeiten schraffieren
    let cursor = START_HOUR * 60;
    for (const [a, b] of [...m.hours, [`${END_HOUR}:00`, `${END_HOUR}:00`]]) {
      if (hm(a) > cursor) col.innerHTML += `<div class="tl-off" style="top:${yPos(cursor)}px;height:${(hm(a) - cursor) * PX_PER_MIN}px"></div>`;
      cursor = Math.max(cursor, hm(b));
    }
    for (const b of data.blocks.filter(b => !b.master_id || b.master_id === m.id)) {
      const s = Math.max(minutes(b.start), START_HOUR * 60), e = Math.min(b.end.slice(0, 10) > data.date ? END_HOUR * 60 : minutes(b.end), END_HOUR * 60);
      col.innerHTML += `<div class="tl-block" style="top:${yPos(s)}px;height:${(e - s) * PX_PER_MIN}px">⛔ ${esc(b.reason || "gesperrt")}</div>`;
    }
    for (const a of data.appointments.filter(a => a.master_id === m.id)) {
      const s = minutes(a.start), e = minutes(a.end);
      const el = document.createElement("div");
      el.className = `tl-app ${a.status}`;
      el.style.top = yPos(s) + "px";
      el.style.height = Math.max((e - s) * PX_PER_MIN - 3, 26) + "px";
      el.innerHTML = `<b>${a.start.slice(11, 16)} ${a.emoji} ${esc(a.customer)}</b>${esc(a.service)}`;
      el.onclick = () => showDetail(a);
      col.appendChild(el);
    }
    tl.appendChild(col);
  }
  const now = new Date();
  if (data.date === localDate(now)) {
    const line = document.createElement("div");
    line.className = "tl-now";
    line.style.top = (tl.querySelector(".tl-head").offsetHeight + yPos(now.getHours() * 60 + now.getMinutes())) + "px";
    tl.appendChild(line);
  }
  history.replaceState(null, "", `?d=${current}`);
}

function showDetail(a) {
  const labels = { booked: "🟢 gebucht", done: "✅ erledigt", no_show: "🚫 nicht erschienen", cancelled: "❌ abgesagt" };
  $("detail-body").innerHTML = `
    <h3>${a.emoji} ${esc(a.service)}</h3>
    <p class="muted">${a.start.slice(11, 16)}–${a.end.slice(11, 16)} Uhr · ${esc(a.master)} · ${euro(a.price)}</p>
    <p>🙋 <b>${esc(a.customer)}</b>${a.phone ? `<br>📱 <a href="tel:${esc(a.phone)}">${esc(a.phone)}</a>` : ""}</p>
    <p>${labels[a.status] || a.status}</p>
    ${a.status === "booked" ? `<div class="row">
      <button class="btn" data-act="noshow">🚫 Nicht erschienen</button>
      <button class="btn danger" data-act="cancel">❌ Absagen</button></div>` : ""}`;
  $("detail-body").querySelectorAll("[data-act]").forEach(btn => btn.onclick = async () => {
    if (btn.dataset.act === "cancel" && !confirm("Termin wirklich absagen?")) return;
    await api(`/api/appointments/${a.id}/${btn.dataset.act}`, { method: "POST" });
    $("detail").hidden = true;
    refresh();
  });
  $("detail").hidden = false;
}

async function loadStats() {
  const s = await api("/api/stats");
  $("k-apps").textContent = s.appointments;
  $("k-rev").textContent = euro(s.revenue);
  $("k-util").textContent = `${s.next7.utilization.toLocaleString("de-DE")} %`;
  $("k-rating").textContent = s.rating ? `${s.rating.toLocaleString("de-DE")} ★` : "–";
  const max = Math.max(...s.series.map(x => x.revenue), 1);
  $("chart").innerHTML = s.series.map(x => `<div class="bar" title="${x.count} Termine">
      <em>${x.revenue ? euro(x.revenue) : ""}</em><i style="height:${(x.revenue / max) * 140}px"></i><small>${x.label}</small></div>`).join("");
  const topMax = Math.max(...s.top_services.map(x => x.count), 1);
  $("top").innerHTML = s.top_services.map(x => `<li><span>${x.emoji} ${esc(x.name)}</span><b>${x.count}</b>
      <span class="meter"><i style="width:${(x.count / topMax) * 100}%"></i></span></li>`).join("") || "<li class='muted'>Noch keine Daten</li>";
  $("extra").textContent = `🆕 ${s.new_customers} neue Kunden · ❌ ${s.cancelled} Absagen · 🚫 ${s.no_shows} nicht erschienen`;
}

function shift(days) {
  const d = new Date(current + "T12:00:00");
  d.setDate(d.getDate() + days);
  current = localDate(d);
  loadDay();
}

function refresh() { loadDay(); loadStats(); }
$("prev").onclick = () => shift(-1);
$("next").onclick = () => shift(1);
$("today").onclick = () => { current = null; loadDay(); };
$("close").onclick = () => { $("detail").hidden = true; };
$("detail").onclick = e => { if (e.target.id === "detail") $("detail").hidden = true; };
refresh();
setInterval(refresh, 60000);
