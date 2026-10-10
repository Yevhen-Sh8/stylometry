/* DIMS landing — waitlist form, language memory, formula ↔ indicator link. */
(function () {
  "use strict";

  // Remember an explicit language choice so the root page redirects there next time.
  document.querySelectorAll(".langs a[data-lang]").forEach(function (a) {
    a.addEventListener("click", function () {
      try { localStorage.setItem("dims-lang", a.dataset.lang); } catch (e) { /* storage blocked */ }
    });
  });

  // The specialists' block is collapsed; a link to #experts should open it.
  var experts = document.getElementById("experts");
  function openExperts() {
    if (experts && location.hash === "#experts") experts.open = true;
  }
  openExperts();
  window.addEventListener("hashchange", openExperts);
  document.querySelectorAll('a[href="#experts"]').forEach(function (a) {
    a.addEventListener("click", function () { if (experts) experts.open = true; });
  });

  // Hovering or focusing a term in the formula highlights its indicator card, and back.
  var terms = document.querySelectorAll("[data-ind]");
  function mark(key, on) {
    terms.forEach(function (el) {
      if (el.dataset.ind === key) el.classList.toggle("is-active", on);
    });
  }
  terms.forEach(function (el) {
    var key = el.dataset.ind;
    el.addEventListener("mouseenter", function () { mark(key, true); });
    el.addEventListener("mouseleave", function () { mark(key, false); });
  });

  // Waitlist form → any endpoint that accepts form POSTs and answers JSON
  // (Formspree, Web3Forms, own backend). Without an endpoint it stays a preview.
  var form = document.getElementById("waitlist-form");
  if (!form) return;
  var status = document.getElementById("wl-status");
  var email = document.getElementById("wl-email");
  var consent = document.getElementById("wl-consent");
  var submit = document.getElementById("wl-submit");
  var msg = form.dataset;
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function say(text, kind) {
    status.textContent = text;
    status.classList.toggle("is-ok", kind === "ok");
    status.classList.toggle("is-error", kind === "error");
  }

  email.addEventListener("input", function () { email.removeAttribute("aria-invalid"); });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var value = email.value.trim();
    if (!EMAIL_RE.test(value)) {
      email.setAttribute("aria-invalid", "true");
      email.focus();
      say(msg.msgInvalid, "error");
      return;
    }
    if (!consent.checked) {
      consent.focus();
      say(msg.msgConsent, "error");
      return;
    }
    if (form.elements.company && form.elements.company.value) {
      say(msg.msgSuccess, "ok");  // honeypot filled: pretend success, send nothing
      return;
    }
    var endpoint = msg.endpoint;
    if (!endpoint) {
      say(msg.msgUnconfigured, "error");
      return;
    }
    var data = new FormData(form);
    data.delete("company");
    data.set("email", value);
    data.set("page", location.pathname);
    // Ad tracking tags (?utm_source=…) show which campaign brought the sign-up.
    new URLSearchParams(location.search).forEach(function (value, key) {
      if (/^utm_[a-z]+$/.test(key)) data.set(key, value.slice(0, 100));
    });
    submit.disabled = true;
    say(msg.msgSending);
    fetch(endpoint, { method: "POST", body: data, headers: { Accept: "application/json" } })
      .then(function (resp) {
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        form.reset();
        say(msg.msgSuccess, "ok");
      })
      .catch(function () { say(msg.msgError, "error"); })
      .then(function () { submit.disabled = false; });
  });
})();
