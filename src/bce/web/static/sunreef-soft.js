/* ============================================================================
   SUNREEF — SOFT MACHINE  ·  interactions  ·  v1
   ----------------------------------------------------------------------------
   Vanilla JS, no dependencies. Progressive enhancement — everything degrades
   to a usable no-JS state. Self-initialises on DOMContentLoaded.

   Provides three behaviours, all driven by data attributes / roles so they
   work anywhere the markup appears (see reference.html):

     1. THEME TOGGLE
        <button id="theme-toggle"> or [data-sunreef-toggle]
        Flips <html data-theme="light|dark">, persisted to localStorage.
        NB: to avoid a flash of the wrong theme, ALSO inline this tiny script
        in <head> BEFORE the stylesheet:
          <script>try{var s=localStorage.getItem('bce-theme');
            if(s)document.documentElement.setAttribute('data-theme',s);}catch(e){}</script>

     2. SEGMENTED TABS
        <div class="tabs"> with <button role="tab" data-target="panelId">
        Panels are elements with matching id; inactive ones get [hidden].

     3. COPY TO CLIPBOARD
        <button class="copybtn" data-copy="panelId">  copies that panel's
        .prose text; shows a transient "Copied" on .copybtn__label.
   ============================================================================ */
(function () {
  "use strict";
  var STORAGE_KEY = "bce-theme";

  function initTheme() {
    var root = document.documentElement;
    var toggles = document.querySelectorAll("#theme-toggle, [data-sunreef-toggle]");
    toggles.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        var current = root.getAttribute("data-theme") || (dark ? "dark" : "light");
        var next = current === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try { localStorage.setItem(STORAGE_KEY, next); } catch (e) {}
      });
    });
  }

  function initTabs() {
    document.querySelectorAll(".tabs").forEach(function (group) {
      var tabs = Array.prototype.slice.call(group.querySelectorAll('[role="tab"]'));
      tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
          tabs.forEach(function (t) {
            var on = t === tab;
            t.setAttribute("aria-selected", on ? "true" : "false");
            var panel = document.getElementById(t.getAttribute("data-target"));
            if (panel) { panel.hidden = !on; }
          });
        });
      });
    });
  }

  function initCopy() {
    document.querySelectorAll(".copybtn[data-copy]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var panel = document.getElementById(btn.getAttribute("data-copy"));
        var prose = panel ? panel.querySelector(".prose") : null;
        if (!prose || !navigator.clipboard || !navigator.clipboard.writeText) { return; }
        navigator.clipboard.writeText(prose.innerText.trim()).then(function () {
          btn.classList.add("is-done");
          var label = btn.querySelector(".copybtn__label");
          var prev = label ? label.textContent : "";
          if (label) { label.textContent = "Copied"; }
          setTimeout(function () {
            btn.classList.remove("is-done");
            if (label) { label.textContent = prev; }
          }, 1600);
        }).catch(function () {});
      });
    });
  }

  function init() { initTheme(); initTabs(); initCopy(); }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
