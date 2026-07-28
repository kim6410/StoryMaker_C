/*
 * 단계9: 메인 스레드 컨트롤러. UI 상태만 다루고, 무거운 작업은 Worker에 위임한다(31-4장).
 * 실패·시간초과·미지원 시 기존 서버 렌더(POST /content/job/{job_uid}/mp4/generate)로 폴백한다.
 */
(function (global) {
  "use strict";

  const LOCAL_RENDER_TIMEOUT_MS = 90_000;
  const STALL_TIMEOUT_MS = 25_000;

  async function decodeAudioUrl(url) {
    const res = await fetch(url);
    if (!res.ok) throw new Error("audio_fetch_failed:" + res.status);
    const arrayBuffer = await res.arrayBuffer();
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC();
    try {
      const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
      const samples = decoded.getChannelData(0).slice();
      return { samples, sampleRate: decoded.sampleRate };
    } finally {
      ctx.close();
    }
  }

  async function reportDiagnostics(jobUid, caps, outcome, fallbackReason, totalMs) {
    try {
      await fetch(`/content/job/${jobUid}/mp4/render-diagnostics`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          render_method: "local", webgpu_ready: caps.webgpu.supported,
          webcodecs_ready: caps.webcodecsVideo.supported, memory_mb: caps.memoryMB,
          outcome, fallback_reason: fallbackReason || "", total_ms: totalMs,
          user_agent: caps.userAgent,
        }),
      });
    } catch (e) { /* 진단 로그 실패는 렌더 결과에 영향을 주지 않는다 */ }
  }

  async function runServerFallback(jobUid, onStage) {
    onStage("server_rendering");
    const res = await fetch(`/content/job/${jobUid}/mp4/generate`, { method: "POST" });
    return res.ok || res.status === 303;
  }

  async function startLocalRender(jobUid, caps, callbacks) {
    const started = performance.now();
    const onStage = callbacks.onStage || (() => {});
    const onProgress = callbacks.onProgress || (() => {});
    const onDone = callbacks.onDone || (() => {});
    const onFallback = callbacks.onFallback || (() => {});

    let fallbackReason = "";
    let worker = null;
    let settled = false;
    let lastProgressAt = Date.now();

    const finishWithFallback = async (reason) => {
      if (settled) return;
      settled = true;
      fallbackReason = reason;
      if (worker) { worker.terminate(); worker = null; }
      onFallback(reason);
      const ok = await runServerFallback(jobUid, onStage);
      await reportDiagnostics(jobUid, caps, ok ? "fallback_success" : "fallback_failed", reason,
        Math.round(performance.now() - started));
      onDone({ ok, method: "server", fallbackReason: reason });
    };

    if (!caps.localRenderReady) {
      await finishWithFallback("unsupported: " + JSON.stringify({
        webcodecs: caps.webcodecsVideo.reason, worker: caps.worker, offscreenCanvas: caps.offscreenCanvas,
      }));
      return;
    }

    try {
      onStage("preparing_media");
      const manifestRes = await fetch(`/content/job/${jobUid}/render-manifest.json`);
      if (!manifestRes.ok) { await finishWithFallback("manifest_fetch_failed"); return; }
      const manifest = await manifestRes.json();

      const tts = await decodeAudioUrl(manifest.tts_audio_url);
      let music = null;
      if (manifest.music_url) {
        try { music = await decodeAudioUrl(manifest.music_url); }
        catch (e) { music = null; }
      }

      const overallTimeout = setTimeout(() => finishWithFallback("overall_timeout"), LOCAL_RENDER_TIMEOUT_MS);
      const stallInterval = setInterval(() => {
        if (Date.now() - lastProgressAt > STALL_TIMEOUT_MS) {
          clearInterval(stallInterval);
          finishWithFallback("progress_stalled");
        }
      }, 5000);

      worker = new Worker("/static/js/local-renderer-worker.js");
      worker.onmessage = async (event) => {
        const msg = event.data;
        lastProgressAt = Date.now();
        if (msg.type === "stage") onStage(msg.stage);
        else if (msg.type === "frame_progress") onProgress(msg.ratio);
        else if (msg.type === "completed") {
          settled = true;
          clearTimeout(overallTimeout);
          clearInterval(stallInterval);
          worker.terminate();
          await reportDiagnostics(jobUid, caps, "local_success", "", Math.round(performance.now() - started));
          onDone({ ok: true, method: "local", durationSeconds: msg.durationSeconds, fileSizeBytes: msg.fileSizeBytes });
        } else if (msg.type === "failed" || msg.type === "error") {
          clearTimeout(overallTimeout);
          clearInterval(stallInterval);
          await finishWithFallback("worker_" + (msg.errorCode || "error") + ": " + (msg.errorMessage || msg.message || ""));
        }
      };
      worker.onerror = (e) => {
        clearTimeout(overallTimeout);
        clearInterval(stallInterval);
        finishWithFallback("worker_crashed: " + e.message);
      };

      const ttsBuffer = tts.samples.buffer;
      const musicBuffer = music ? music.samples.buffer : null;
      worker.postMessage({
        type: "start", manifest, jobUid,
        ttsSamples: tts.samples, ttsSampleRate: tts.sampleRate,
        musicSamples: music ? music.samples : null, musicSampleRate: music ? music.sampleRate : null,
      }, musicBuffer ? [ttsBuffer, musicBuffer] : [ttsBuffer]);
    } catch (err) {
      await finishWithFallback("exception: " + (err && err.message));
    }
  }

  global.StoryMakerLocalRender = { startLocalRender, decodeAudioUrl };
})(window);
