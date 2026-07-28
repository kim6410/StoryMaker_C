/*
 * 단계9: 로컬(WebGPU 준비/WebCodecs) 렌더 Worker.
 * 메인 스레드는 UI만 담당하고, 실제 프레임 생성·인코딩·Muxing은 여기서 처리한다(작업지시 31-4장).
 * 서버가 이미 계산한 장면·타이밍(manifest)만 신뢰하고, 임의 경로에는 접근하지 않는다.
 */
importScripts("/static/vendor/mp4-muxer.min.js");

const FONT_STACK = "'Malgun Gothic','Apple SD Gothic Neo',sans-serif";

function post(type, payload) {
  self.postMessage({ type, ...payload });
}

function toCssColor(hex) {
  // 서버(FFmpeg lavfi)는 0x1b2a4a 표기를 쓰지만 Canvas는 CSS 표기(#1b2a4a)가 필요하다.
  return hex && hex.startsWith("0x") ? "#" + hex.slice(2) : hex;
}

function buildGradientCanvas(ctx, width, height, color0, color1) {
  const grad = ctx.createLinearGradient(0, 0, width, height);
  grad.addColorStop(0, toCssColor(color0));
  grad.addColorStop(1, toCssColor(color1));
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, width, height);
}

function drawBadge(ctx, text, x, y, align, fontSize) {
  ctx.font = `bold ${fontSize}px ${FONT_STACK}`;
  const metrics = ctx.measureText(text);
  const padX = 14, padY = 10;
  const boxW = metrics.width + padX * 2;
  const boxH = fontSize + padY * 2;
  const boxX = align === "right" ? x - boxW : x;
  ctx.fillStyle = "rgba(0,0,0,0.35)";
  ctx.fillRect(boxX, y, boxW, boxH);
  ctx.fillStyle = "#ffffff";
  ctx.textBaseline = "middle";
  ctx.fillText(text, boxX + padX, y + boxH / 2);
}

function drawCaption(ctx, text, width, height, fontSize) {
  if (!text) return;
  ctx.font = `${fontSize}px ${FONT_STACK}`;
  const maxWidth = width - 100;
  const words = text.split(" ");
  const lines = [];
  let current = "";
  for (const w of words) {
    const candidate = current ? current + " " + w : w;
    if (ctx.measureText(candidate).width > maxWidth && current) {
      lines.push(current);
      current = w;
    } else {
      current = candidate;
    }
  }
  if (current) lines.push(current);
  const shown = lines.slice(0, 2);
  const lineHeight = fontSize + 10;
  const totalH = shown.length * lineHeight + 20;
  const boxY = height - 260 - totalH / 2;
  const maxLineWidth = Math.max(...shown.map((l) => ctx.measureText(l).width));
  ctx.fillStyle = "rgba(0,0,0,0.5)";
  ctx.fillRect((width - maxLineWidth) / 2 - 20, boxY, maxLineWidth + 40, totalH);
  ctx.fillStyle = "#ffffff";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  shown.forEach((line, i) => {
    ctx.fillText(line, width / 2, boxY + 20 + i * lineHeight + lineHeight / 2);
  });
  ctx.textAlign = "left";
}

function zoomScaleAt(t, duration, zoomStart, zoomEnd) {
  if (duration <= 0) return zoomStart;
  const ratio = Math.min(1, Math.max(0, t / duration));
  return zoomStart + (zoomEnd - zoomStart) * ratio;
}

async function renderVideoTrack(manifest, muxer, onProgress) {
  const { width, height, fps, scenes, company_name: companyName, phone_number: phoneNumber } = manifest;
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext("2d");

  const videoEncoder = new VideoEncoder({
    output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    error: (e) => post("error", { message: "video_encode_error: " + e.message }),
  });
  videoEncoder.configure({
    // avc1.420028 = Baseline profile, Level 4.0(0x28) — 1080x1920(약 2.07M화소)을 담으려면
    // Level 3.1(0x1F, 921,600화소 한도)로는 부족해 인코더가 즉시 오류를 낸다(31-3장 실제 시험 인코딩으로 발견).
    codec: "avc1.420028", width, height, bitrate: 2_500_000, framerate: fps,
    avc: { format: "avc" },
  });

  let frameIndex = 0;
  const totalFrames = Math.round(scenes.reduce((s, sc) => s + sc.duration_seconds, 0) * fps);

  for (const scene of scenes) {
    const sceneFrames = Math.max(1, Math.round(scene.duration_seconds * fps));
    for (let i = 0; i < sceneFrames; i++) {
      const localT = i / fps;
      const zoom = zoomScaleAt(localT, scene.duration_seconds, scene.zoom_start, scene.zoom_end);

      buildGradientCanvas(ctx, width, height, scene.color0, scene.color1);
      // 간단한 줌: 확대된 소스 영역을 캔버스 전체에 그린다(중심 유지).
      const srcW = width / zoom, srcH = height / zoom;
      const srcX = (width - srcW) / 2, srcY = (height - srcH) / 2;
      ctx.drawImage(canvas, srcX, srcY, srcW, srcH, 0, 0, width, height);

      if (companyName) drawBadge(ctx, companyName, 44, 40, "left", 30);
      if (phoneNumber) drawBadge(ctx, phoneNumber, width - 44, 40, "right", 26);
      if (localT >= scene.caption_start_local && localT <= scene.caption_end_local && scene.caption) {
        drawCaption(ctx, scene.caption, width, height, 34);
      }

      const timestamp = Math.round((frameIndex / fps) * 1e6);
      const frame = new VideoFrame(canvas, { timestamp, duration: Math.round(1e6 / fps) });
      videoEncoder.encode(frame, { keyFrame: frameIndex % (fps * 2) === 0 });
      frame.close();
      frameIndex++;

      if (frameIndex % 15 === 0) {
        onProgress(frameIndex / totalFrames);
        await new Promise((r) => setTimeout(r, 0));
      }
    }
  }

  await videoEncoder.flush();
  videoEncoder.close();
}

function mixAudio(manifest, ttsSamples, ttsSampleRate, musicSamples, musicSampleRate) {
  const targetRate = ttsSampleRate;
  const totalSamples = Math.round(manifest.total_duration_seconds * targetRate);
  const startLeadSamples = Math.round(manifest.start_lead_seconds * targetRate);
  const endHoldSeconds = manifest.end_hold_seconds;

  const mixed = new Float32Array(totalSamples);
  for (let i = 0; i < ttsSamples.length && startLeadSamples + i < totalSamples; i++) {
    mixed[startLeadSamples + i] = ttsSamples[i];
  }

  if (musicSamples && musicSamples.length > 0) {
    const ducked = 0.14;
    const fadeInSamples = Math.round(manifest.start_lead_seconds * targetRate);
    const fadeOutStart = totalSamples - Math.round(endHoldSeconds * targetRate);
    for (let i = 0; i < totalSamples; i++) {
      const srcIdx = musicSampleRate === targetRate
        ? i % musicSamples.length
        : Math.floor((i * musicSampleRate) / targetRate) % musicSamples.length;
      let vol = ducked;
      if (i < fadeInSamples) vol = ducked * (i / fadeInSamples);
      else if (i >= fadeOutStart) vol = ducked * Math.max(0, 1 - (i - fadeOutStart) / (totalSamples - fadeOutStart));
      mixed[i] += musicSamples[srcIdx] * vol;
    }
  }

  for (let i = 0; i < mixed.length; i++) {
    if (mixed[i] > 1) mixed[i] = 1;
    if (mixed[i] < -1) mixed[i] = -1;
  }
  return mixed;
}

async function renderAudioTrack(manifest, muxer, ttsSamples, ttsSampleRate, musicSamples, musicSampleRate) {
  const mixed = mixAudio(manifest, ttsSamples, ttsSampleRate, musicSamples, musicSampleRate);
  const audioEncoder = new AudioEncoder({
    output: (chunk, meta) => muxer.addAudioChunk(chunk, meta),
    error: (e) => post("error", { message: "audio_encode_error: " + e.message }),
  });
  audioEncoder.configure({ codec: "mp4a.40.2", numberOfChannels: 1, sampleRate: ttsSampleRate, bitrate: 128000 });

  const frameSize = 1024;
  for (let pos = 0; pos < mixed.length; pos += frameSize) {
    const n = Math.min(frameSize, mixed.length - pos);
    const chunk = mixed.subarray(pos, pos + n);
    const audioData = new AudioData({
      format: "f32", sampleRate: ttsSampleRate, numberOfFrames: n, numberOfChannels: 1,
      timestamp: Math.round((pos / ttsSampleRate) * 1e6), data: chunk,
    });
    audioEncoder.encode(audioData);
    audioData.close();
  }
  await audioEncoder.flush();
  audioEncoder.close();
}

self.onmessage = async (event) => {
  const msg = event.data;
  if (msg.type !== "start") return;
  const { manifest, ttsSamples, ttsSampleRate, musicSamples, musicSampleRate, jobUid } = msg;

  try {
    post("stage", { stage: "encoding_video" });
    const muxer = new Mp4Muxer.Muxer({
      target: new Mp4Muxer.ArrayBufferTarget(),
      video: { codec: "avc", width: manifest.width, height: manifest.height },
      audio: { codec: "aac", numberOfChannels: 1, sampleRate: ttsSampleRate },
      fastStart: "in-memory",
    });

    await renderVideoTrack(manifest, muxer, (ratio) => post("frame_progress", { ratio }));

    post("stage", { stage: "encoding_audio" });
    await renderAudioTrack(manifest, muxer, ttsSamples, ttsSampleRate, musicSamples, musicSampleRate);

    post("stage", { stage: "muxing" });
    muxer.finalize();
    const buffer = muxer.target.buffer;

    post("stage", { stage: "uploading" });
    const blob = new Blob([buffer], { type: "video/mp4" });
    const fd = new FormData();
    fd.append("file", blob, "local_render.mp4");
    const res = await fetch(`/content/job/${jobUid}/mp4/upload-local`, { method: "POST", body: fd });
    const result = await res.json();

    if (result.ok) {
      post("completed", { durationSeconds: result.duration_seconds, fileSizeBytes: result.file_size_bytes });
    } else {
      post("failed", { errorCode: result.error_code, errorMessage: result.error_message });
    }
  } catch (err) {
    post("failed", { errorCode: "worker_exception", errorMessage: err && err.message });
  }
};
