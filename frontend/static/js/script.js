/* Global UI helpers: CSRF-aware fetch, sidebar, confirm dialogs, loading overlay, form validation, auto-dismiss. */
(function () {
  "use strict";
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";
  window.csrfToken = csrf;

  window.apiFetch = async function (url, options = {}) {
    const opts = Object.assign({ headers: {}, credentials: "same-origin" }, options);
    opts.headers = Object.assign({ "X-CSRF-Token": csrf, "Accept": "application/json" }, opts.headers);
    if (opts.json) { opts.method = opts.method || "POST"; opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
    let res, data = {};
    try { res = await fetch(url, opts); } catch (e) { throw new Error("Network error: could not reach the server."); }
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    if (res.status === 401) { window.location = "/login"; throw new Error("Please log in again."); }
    if (!res.ok || data.ok === false) throw new Error(data.error || ("Request failed (" + res.status + ")."));
    return data;
  };
  window.escapeHtml = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  window.showLoading = on => { const o = document.getElementById("loadingOverlay"); if (o) o.classList.toggle("show", on); };
  window.toast = function (message, type = "info") {
    const holder = document.getElementById("flashArea"); if (!holder) return;
    const div = document.createElement("div");
    div.className = "alert alert-" + type + " alert-dismissible fade show"; div.setAttribute("role", "alert");
    div.innerHTML = escapeHtml(message) + '<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>';
    holder.prepend(div); setTimeout(() => bootstrap.Alert.getOrCreateInstance(div).close(), 6000);
  };

  document.addEventListener("DOMContentLoaded", function () {
    // sidebar toggle (mobile)
    const sb = document.getElementById("sidebar"), bd = document.getElementById("sidebarBackdrop");
    const toggle = () => { sb.classList.toggle("open"); bd.classList.toggle("show"); };
    const btn = document.getElementById("sidebarToggle"); if (btn) btn.addEventListener("click", toggle); if (bd) bd.addEventListener("click", toggle);

    // confirmation dialogs: <form data-confirm="Are you sure?">
    const modalEl = document.getElementById("confirmModal");
    if (modalEl) {
      const modal = new bootstrap.Modal(modalEl); let pending = null;
      document.querySelectorAll("form[data-confirm]").forEach(f => f.addEventListener("submit", e => {
        if (f.dataset.confirmed) return; e.preventDefault(); pending = f;
        document.getElementById("confirmText").textContent = f.dataset.confirm; modal.show();
      }));
      document.getElementById("confirmYes").addEventListener("click", () => { if (pending) { pending.dataset.confirmed = "1"; modal.hide(); pending.requestSubmit ? pending.requestSubmit() : pending.submit(); } });
    }

    // Bootstrap validation + loading state on submit
    document.querySelectorAll("form.needs-validation").forEach(form => form.addEventListener("submit", e => {
      if (!form.checkValidity()) { e.preventDefault(); e.stopPropagation(); form.classList.add("was-validated"); return; }
      const b = form.querySelector('button[type="submit"]'); if (b && !form.hasAttribute("data-confirm")) { b.disabled = true; b.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Please wait'; }
    }, false));

    // filter selects submit automatically
    document.querySelectorAll("form.filters select").forEach(s => s.addEventListener("change", () => s.form.submit()));

    // edit-modal population: <button data-edit-target="#modalId" data-fields='{"name":"x"}' data-action="/url">
    document.querySelectorAll("[data-edit-target]").forEach(btn => btn.addEventListener("click", () => {
      const m = document.querySelector(btn.dataset.editTarget); if (!m) return;
      const form = m.querySelector("form"); form.action = btn.dataset.action;
      const fields = JSON.parse(btn.dataset.fields || "{}");
      Object.keys(fields).forEach(k => { const el = form.elements[k]; if (el) el.value = fields[k] ?? ""; });
      bootstrap.Modal.getOrCreateInstance(m).show();
    }));

    // dependent student dropdown: <select data-students-for="#studentSelect">
    document.querySelectorAll("select[data-students-for]").forEach(courseSel => {
      const target = document.querySelector(courseSel.dataset.studentsFor); if (!target) return;
      const load = async () => {
        if (!courseSel.value) { target.innerHTML = '<option value="">Select a course first</option>'; return; }
        target.innerHTML = '<option value="">Loading...</option>';
        try {
          const d = await apiFetch("/api/courses/" + courseSel.value + "/students");
          target.innerHTML = d.students.length ? '<option value="">Select student</option>' + d.students.map(s => '<option value="' + s.id + '">' + escapeHtml(s.name) + "</option>").join("") : '<option value="">No enrolled students</option>';
        } catch (e) { target.innerHTML = '<option value="">Could not load students</option>'; }
      };
      courseSel.addEventListener("change", load); if (courseSel.value) load();
    });

    // auto-dismiss flash alerts
    document.querySelectorAll("#flashArea .alert").forEach(a => setTimeout(() => { try { bootstrap.Alert.getOrCreateInstance(a).close(); } catch (e) {} }, 7000));
  });
})();
