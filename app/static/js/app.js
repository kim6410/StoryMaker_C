// StoryMaker Claude Lab - 1단계 껍데기용 공용 스크립트
// 실제 API 호출 없이 화면 이동/상태 표시만 담당한다.
(function () {
  "use strict";

  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  // ---- 모바일 사이드 메뉴 토글 ----
  var hamburger = qs("[data-hamburger]");
  var sidebar = qs("[data-sidebar]");
  var overlay = qs("[data-overlay]");

  function closeSidebar() {
    if (sidebar) sidebar.classList.remove("open");
    if (overlay) overlay.classList.remove("show");
  }
  function openSidebar() {
    if (sidebar) sidebar.classList.add("open");
    if (overlay) overlay.classList.add("show");
  }
  if (hamburger) {
    hamburger.addEventListener("click", function () {
      if (sidebar && sidebar.classList.contains("open")) closeSidebar();
      else openSidebar();
    });
  }
  if (overlay) overlay.addEventListener("click", closeSidebar);
  qsa(".sidebar .nav-item").forEach(function (el) {
    el.addEventListener("click", closeSidebar);
  });

  // ---- 토스트 알림 ----
  window.showToast = function (message) {
    var toast = qs("[data-toast]");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("show");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(function () { toast.classList.remove("show"); }, 2600);
  };

  // ---- data-toast-msg 버튼: 클릭하면 토스트만 표시 (아직 실제 기능 미연결) ----
  qsa("[data-toast-msg]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.preventDefault();
      window.showToast(el.getAttribute("data-toast-msg"));
    });
  });

  // ---- 탭 전환 ----
  qsa("[data-tabs]").forEach(function (group) {
    var tabs = qsa(".tab", group);
    var panels = qsa("[data-tab-panel]", group.parentElement);
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (t) { t.classList.remove("active"); });
        tab.classList.add("active");
        var key = tab.getAttribute("data-tab");
        panels.forEach(function (p) {
          p.style.display = (p.getAttribute("data-tab-panel") === key) ? "" : "none";
        });
      });
    });
  });

  // ---- 썸네일 후보 선택 (8개 중 1개, 클릭 시 선택 표시만) ----
  qsa("[data-thumb-grid]").forEach(function (grid) {
    qsa(".thumb", grid).forEach(function (thumb) {
      thumb.addEventListener("click", function () {
        qsa(".thumb", grid).forEach(function (t) { t.classList.remove("selected"); });
        thumb.classList.add("selected");
        var confirmBtn = qs("[data-thumb-confirm]");
        if (confirmBtn) confirmBtn.removeAttribute("disabled");
      });
    });
  });

  // ---- 모달 열기/닫기 ----
  qsa("[data-modal-open]").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var modal = qs(btn.getAttribute("data-modal-open"));
      if (modal) modal.classList.add("show");
    });
  });
  qsa("[data-modal-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var modal = btn.closest(".modal-backdrop");
      if (modal) modal.classList.remove("show");
    });
  });

  // ---- 클립보드 복사 버튼 (샘플 텍스트 복사만 수행) ----
  qsa("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var target = qs(btn.getAttribute("data-copy"));
      if (!target) return;
      var text = target.innerText || target.textContent || "";
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () { window.showToast("복사했습니다."); });
      } else {
        window.showToast("복사했습니다. (샘플)");
      }
    });
  });

  // ---- 중복 클릭 방지: submit류 버튼은 한 번 누르면 비활성화 ----
  qsa("[data-once]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (btn.dataset.locked === "1") return;
      btn.dataset.locked = "1";
      var original = btn.textContent;
      btn.textContent = "처리 중...";
      setTimeout(function () {
        btn.dataset.locked = "";
        btn.textContent = original;
      }, 1200);
    });
  });
})();
