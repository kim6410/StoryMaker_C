/*
 * 단계9: 로컬 가속 실제 기능 탐지.
 * navigator.gpu 존재 여부만으로 성공 판정하지 않는다(작업지시 31-2장).
 * Adapter 요청 -> Device 생성 -> 최소 연산까지 성공해야 webgpu_ready로 판정한다.
 * WebCodecs도 isConfigSupported() 성공만 믿지 않고 실제 소형 프레임 시험 인코딩까지 확인한다(31-3장).
 */
(function (global) {
  "use strict";

  async function detectWebGPU() {
    if (!("gpu" in navigator)) {
      return { supported: false, reason: "no_navigator_gpu" };
    }
    try {
      const adapter = await navigator.gpu.requestAdapter();
      if (!adapter) return { supported: false, reason: "no_adapter" };
      const device = await adapter.requestDevice();
      if (!device) return { supported: false, reason: "no_device" };
      // 최소 연산: 작은 텍스처에 렌더 패스 1회 실행해 실제로 GPU가 명령을 받는지 확인한다.
      const texture = device.createTexture({
        size: [4, 4], format: "rgba8unorm",
        usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC,
      });
      const encoder = device.createCommandEncoder();
      const pass = encoder.beginRenderPass({
        colorAttachments: [{
          view: texture.createView(), loadOp: "clear", storeOp: "store",
          clearValue: { r: 0, g: 0, b: 0, a: 1 },
        }],
      });
      pass.end();
      device.queue.submit([encoder.finish()]);
      texture.destroy();
      device.destroy();
      return { supported: true, reason: "" };
    } catch (err) {
      return { supported: false, reason: "exception: " + (err && err.message) };
    }
  }

  async function detectWebCodecs() {
    if (typeof VideoEncoder === "undefined") {
      return { supported: false, reason: "no_video_encoder" };
    }
    // 실제 제작 해상도(1080x1920, Level 4.0)로 시험한다. 작은 해상도만 시험하면
    // "isConfigSupported는 통과했지만 실제 해상도에서는 즉시 실패"하는 오탐이 생긴다.
    const width = 1080, height = 1920;
    const config = { codec: "avc1.420028", width, height, bitrate: 2500000, framerate: 30,
                      avc: { format: "avc" } };
    try {
      const support = await VideoEncoder.isConfigSupported(config);
      if (!support.supported) return { supported: false, reason: "config_not_supported" };
    } catch (err) {
      return { supported: false, reason: "isConfigSupported_threw: " + (err && err.message) };
    }

    // 실제 소형 프레임 1~2개 시험 인코딩(31-3장): 지원 API만 믿지 않는다.
    return new Promise((resolve) => {
      const chunks = [];
      let errored = null;
      let encoder;
      try {
        encoder = new VideoEncoder({
          output: (chunk) => chunks.push(chunk),
          error: (e) => { errored = e; },
        });
        encoder.configure(config);
        const canvas = new OffscreenCanvas(width, height);
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#336699";
        ctx.fillRect(0, 0, width, height);
        const frame = new VideoFrame(canvas, { timestamp: 0 });
        encoder.encode(frame);
        frame.close();
        encoder.flush().then(() => {
          encoder.close();
          if (errored) {
            resolve({ supported: false, reason: "encode_error: " + errored.message });
          } else if (chunks.length === 0) {
            resolve({ supported: false, reason: "no_chunk_output" });
          } else {
            resolve({ supported: true, reason: "" });
          }
        }).catch((err) => {
          resolve({ supported: false, reason: "flush_failed: " + (err && err.message) });
        });
      } catch (err) {
        resolve({ supported: false, reason: "exception: " + (err && err.message) });
      }
    });
  }

  function detectAudioEncoder() {
    if (typeof AudioEncoder === "undefined") return { supported: false, reason: "no_audio_encoder" };
    return { supported: true, reason: "" };
  }

  function detectWorkerAndCanvas() {
    return {
      worker: typeof Worker !== "undefined",
      offscreenCanvas: typeof OffscreenCanvas !== "undefined",
      sharedArrayBuffer: typeof SharedArrayBuffer !== "undefined",
    };
  }

  function estimateMemoryMB() {
    if (navigator.deviceMemory) return navigator.deviceMemory * 1024;
    if (performance && performance.memory && performance.memory.jsHeapSizeLimit) {
      return Math.round(performance.memory.jsHeapSizeLimit / 1024 / 1024);
    }
    return null;
  }

  async function detect() {
    const [webgpu, webcodecsVideo] = await Promise.all([detectWebGPU(), detectWebCodecs()]);
    const audio = detectAudioEncoder();
    const workerCanvas = detectWorkerAndCanvas();
    const memoryMB = estimateMemoryMB();
    // 지원 여부만 검사한다(요청서 3-3장). 이 프로젝트의 렌더 파이프라인은 현재
    // WebAssembly를 실제로 호출하지 않으므로 wasmSupported는 "지원 가능"일 뿐
    // "실사용"을 의미하지 않는다 - 실사용 여부는 항상 false로 별도 보고한다.
    const wasmSupported = typeof WebAssembly !== "undefined";

    const localRenderReady = webcodecsVideo.supported && audio.supported &&
      workerCanvas.worker && workerCanvas.offscreenCanvas;

    return {
      webgpu, webcodecsVideo, audio, ...workerCanvas, memoryMB, wasmSupported,
      localRenderReady,
      userAgent: navigator.userAgent,
      recommendServer: !localRenderReady || (memoryMB !== null && memoryMB < 1536),
    };
  }

  global.StoryMakerRenderCapabilities = { detect };
})(window);
