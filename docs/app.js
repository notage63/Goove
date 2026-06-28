// Server-room temperature dashboard.
// Reads the static JSON files written by scripts/poll_govee.py and renders them.

const REFRESH_MS = 15 * 60 * 1000; // 15 minutes (matches the polling cron)
const STALE_MS = 45 * 60 * 1000; // flag data older than 45 min as stale
const ALERT_THRESHOLD_C = 30; // keep in sync with ALERT_THRESHOLD_C in the workflow

let chart;
let allReadings = [];
let rangeDays = 7;

async function loadJSON(path) {
  // Cache-bust so the page always sees the freshest commit.
  const resp = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
  if (!resp.ok) throw new Error(`${path}: ${resp.status}`);
  return resp.json();
}

function fmtTemp(r) {
  if (r == null || r.temperature == null) return "--";
  return `${r.temperature.toFixed(1)} °${r.unit || "C"}`;
}

function renderLatest(latest) {
  const tempEl = document.getElementById("temp-value");
  const humEl = document.getElementById("humidity-value");
  const updEl = document.getElementById("updated");
  const banner = document.getElementById("status-banner");

  tempEl.textContent = fmtTemp(latest);
  humEl.textContent = latest.humidity != null ? `${latest.humidity.toFixed(0)} %` : "--";

  const ts = new Date(latest.timestamp);
  updEl.textContent = `Last updated: ${ts.toLocaleString()}`;

  const ageMs = Date.now() - ts.getTime();
  banner.classList.remove("ok", "alert", "stale");

  if (ageMs > STALE_MS) {
    banner.classList.add("stale");
    banner.textContent = "⚠️ Data may be stale — no recent update from the sensor.";
  } else if (latest.temperature_c >= ALERT_THRESHOLD_C) {
    banner.classList.add("alert");
    banner.textContent = `🔥 OVERHEAT — at or above ${ALERT_THRESHOLD_C} °C threshold.`;
  } else {
    banner.classList.add("ok");
    banner.textContent = `✅ Normal — below ${ALERT_THRESHOLD_C} °C threshold.`;
  }
}

function renderChart() {
  const cutoff = Date.now() - rangeDays * 24 * 60 * 60 * 1000;
  const points = allReadings
    .filter((r) => new Date(r.timestamp).getTime() >= cutoff)
    .map((r) => ({ x: new Date(r.timestamp), y: r.temperature }));

  const unit = allReadings.length ? allReadings[allReadings.length - 1].unit || "C" : "C";
  const ctx = document.getElementById("chart");

  const data = {
    datasets: [
      {
        label: `Temperature (°${unit})`,
        data: points,
        borderColor: "#38bdf8",
        backgroundColor: "rgba(56, 189, 248, 0.15)",
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.25,
        fill: true,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      x: { type: "time", ticks: { color: "#94a3b8" }, grid: { color: "rgba(148,163,184,0.1)" } },
      y: { ticks: { color: "#94a3b8" }, grid: { color: "rgba(148,163,184,0.1)" } },
    },
    plugins: { legend: { labels: { color: "#e2e8f0" } } },
  };

  if (chart) {
    chart.data = data;
    chart.update();
  } else {
    chart = new Chart(ctx, { type: "line", data, options });
  }
}

async function refresh() {
  try {
    const [latest, readings] = await Promise.all([
      loadJSON("data/latest.json"),
      loadJSON("data/readings.json").catch(() => []),
    ]);
    renderLatest(latest);
    allReadings = Array.isArray(readings) ? readings : [];
    renderChart();
  } catch (err) {
    const banner = document.getElementById("status-banner");
    banner.classList.add("stale");
    banner.textContent = "No data yet — waiting for the first reading.";
    console.error(err);
  }
}

document.querySelectorAll(".range-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".range-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    rangeDays = Number(btn.dataset.range);
    renderChart();
  });
});

refresh();
setInterval(refresh, REFRESH_MS);
