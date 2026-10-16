/* Chart.js rendering for the dashboard, assessments and student pages. All data comes from JSON endpoints. */
(function () {
  "use strict";
  const COLORS = { indigo: "#4f46e5", blue: "#2563eb", cyan: "#0891b2", green: "#059669", amber: "#d97706", red: "#dc2626", slate: "#94a3b8" };
  const registry = {};
  if (window.Chart) { Chart.defaults.font.family = '"Segoe UI",system-ui,sans-serif'; Chart.defaults.color = "#475569"; Chart.defaults.maintainAspectRatio = false; }

  function draw(id, config) {
    const el = document.getElementById(id); if (!el || !window.Chart) return;
    if (registry[id]) registry[id].destroy();
    registry[id] = new Chart(el, config);
  }
  const hasData = arr => arr && arr.some(v => v !== null && v !== undefined && v !== 0);
  function toggle(id, ok, message) {
    const canvas = document.getElementById(id); if (!canvas) return;
    const box = canvas.parentElement; let note = box.querySelector(".chart-empty");
    if (!note) { note = document.createElement("div"); note.className = "empty chart-empty"; note.style.cssText = "position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;background:#fff"; box.appendChild(note); }
    note.innerHTML = '<i class="bi bi-bar-chart"></i>' + escapeHtml(message || "No data for this selection yet."); note.style.display = ok ? "none" : "flex";
  }

  window.renderDashboardCharts = function (c) {
    const ce = c.course_engagement;
    toggle("chartCourse", ce.labels.length && (hasData(ce.engagement) || hasData(ce.minutes)), "No course data yet. Run predictions or record activities.");
    draw("chartCourse", { type: "bar", data: { labels: ce.labels, datasets: [
      { label: "Avg engagement score (0-100)", data: ce.engagement, backgroundColor: COLORS.indigo, borderRadius: 6, yAxisID: "y" },
      { label: "Learning minutes", data: ce.minutes, backgroundColor: "#c7d2fe", borderRadius: 6, yAxisID: "y1" }] },
      options: { scales: { y: { min: 0, max: 100, title: { display: true, text: "Score" } }, y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "Minutes" } } } } });

    const t = c.activity_trend;
    toggle("chartTrend", hasData(t.activities), "No activity recorded in this date range.");
    draw("chartTrend", { type: "line", data: { labels: t.labels, datasets: [
      { label: "Activities (" + t.granularity + ")", data: t.activities, borderColor: COLORS.indigo, backgroundColor: "rgba(79,70,229,.12)", fill: true, tension: .3, pointRadius: 2, yAxisID: "y" },
      { label: "Learning minutes", data: t.minutes, borderColor: COLORS.cyan, tension: .3, pointRadius: 2, yAxisID: "y1" }] },
      options: { interaction: { mode: "index", intersect: false }, scales: { y: { beginAtZero: true }, y1: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false } } } } });

    const p = c.assessment_performance;
    toggle("chartAssess", hasData(p.quiz) || hasData(p.assignment), "No assessment results in this selection.");
    draw("chartAssess", { type: "bar", data: { labels: p.labels, datasets: [
      { label: "Quiz average", data: p.quiz, backgroundColor: COLORS.blue, borderRadius: 6 },
      { label: "Assignment average", data: p.assignment, backgroundColor: COLORS.amber, borderRadius: 6 }] },
      options: { scales: { y: { min: 0, max: 100 } } } });

    const r = c.risk_distribution, total = r.low + r.medium + r.high;
    toggle("chartRisk", total > 0, "No predictions yet. Run predictions to see the risk split.");
    draw("chartRisk", { type: "doughnut", data: { labels: ["Low risk", "Medium risk", "High risk"], datasets: [{ data: [r.low, r.medium, r.high], backgroundColor: [COLORS.green, COLORS.amber, COLORS.red], borderWidth: 2 }] },
      options: { cutout: "62%", plugins: { legend: { position: "bottom" } } } });

    const s = c.student_comparison;
    toggle("chartStudents", s.labels.length > 0, "No student activity in this selection.");
    draw("chartStudents", { type: "bar", data: { labels: s.labels, datasets: [
      { label: "Learning minutes", data: s.minutes, backgroundColor: COLORS.indigo, borderRadius: 6 },
      { label: "Activities", data: s.activities, backgroundColor: COLORS.slate, borderRadius: 6 }] },
      options: { indexAxis: "y", scales: { x: { beginAtZero: true } } } });
  };

  window.renderAssessmentTrend = function (d) {
    toggle("chartAssessTrend", hasData(d.quiz) || hasData(d.assignment), "No assessment results yet.");
    draw("chartAssessTrend", { type: "line", data: { labels: d.labels, datasets: [
      { label: "Quiz average", data: d.quiz, borderColor: COLORS.blue, tension: .3, spanGaps: true },
      { label: "Assignment average", data: d.assignment, borderColor: COLORS.amber, tension: .3, spanGaps: true }] },
      options: { scales: { y: { min: 0, max: 100 } } } });
  };

  window.renderStudentChart = function (labels, minutes) {
    toggle("chartStudentDaily", minutes.length > 0, "No learning time recorded yet.");
    draw("chartStudentDaily", { type: "bar", data: { labels: labels, datasets: [{ label: "Learning minutes per day", data: minutes, backgroundColor: COLORS.indigo, borderRadius: 4 }] },
      options: { scales: { y: { beginAtZero: true } } } });
  };
})();
