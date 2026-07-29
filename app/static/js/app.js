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
      if (modal) {
        modal.classList.add("show");
        var focusable = modal.querySelector("button, [href], input, textarea");
        if (focusable) focusable.focus();
      }
    });
  });
  qsa("[data-modal-close]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var modal = btn.closest(".modal-backdrop");
      if (modal) modal.classList.remove("show");
    });
  });
  // 배경(모달 바깥) 클릭 시 닫기
  qsa(".modal-backdrop").forEach(function (backdrop) {
    backdrop.addEventListener("click", function (e) {
      if (e.target === backdrop) backdrop.classList.remove("show");
    });
  });
  // ESC로 모달·모바일 메뉴 닫기
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    qsa(".modal-backdrop.show").forEach(function (m) { m.classList.remove("show"); });
    closeSidebar();
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

  // ---- 시간이 걸리는 폼 제출: 중복 제출 방지 + 진행 중 문구 순환 표시 ----
  // 실제로 단계별 완료를 서버에서 받아오는 것은 아니고(백엔드는 단일 동기 요청),
  // 대기 중임을 명확히 보여주기 위한 순환 안내문이다 - 가짜 퍼센트나 완료 체크는 표시하지 않는다.
  qsa("[data-async-submit]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (form.dataset.submitting === "1") {
        e.preventDefault();
        return;
      }
      form.dataset.submitting = "1";
      var btn = form.querySelector("button[type=submit]");
      if (!btn) return;
      btn.disabled = true;
      var original = btn.textContent;
      var messages = (form.getAttribute("data-progress-messages") || "처리하고 있습니다").split(",");
      var i = 0;
      btn.innerHTML = '<span class="spinner" aria-hidden="true" style="width:14px;height:14px;margin-right:6px"></span>' + messages[0];
      var timer = setInterval(function () {
        i = (i + 1) % messages.length;
        var spinner = btn.querySelector(".spinner");
        btn.textContent = messages[i];
        if (spinner) btn.prepend(spinner);
      }, 1600);
      // 페이지 이동으로 폼이 사라지면 타이머는 자동 정리된다. 혹시 실패해 같은 페이지에
      // 머무는 경우를 대비해 넉넉한 시간 뒤 버튼을 원상복구한다(서버 오류로 리다이렉트가
      // 오지 않는 극단적 상황 대비 안전장치).
      setTimeout(function () {
        clearInterval(timer);
        if (form.dataset.submitting === "1" && document.body.contains(btn)) {
          btn.disabled = false;
          btn.textContent = original;
          form.dataset.submitting = "";
        }
      }, 120000);
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
