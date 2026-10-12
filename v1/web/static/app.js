// Open Voice V3 Web Demo Controller
document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const micBtn = document.getElementById("mic-btn");
  const micStatus = document.getElementById("mic-status");
  const visualizer = document.getElementById("visualizer-container");
  const textForm = document.getElementById("text-form");
  const textInput = document.getElementById("text-input");

  const switchActions = document.getElementById("switch-actions");
  const switchCleanup = document.getElementById("switch-cleanup");
  const switchTools = document.getElementById("switch-tools");
  const modeText = document.getElementById("mode-text");

  const branchBadge = document.getElementById("branch-badge");
  const rawTranscript = document.getElementById("raw-transcript");
  const cleanedTranscript = document.getElementById("cleaned-transcript");

  const cardBadge = document.getElementById("card-badge");
  const cardContainer = document.getElementById("card-container");
  const replyBox = document.getElementById("reply-box");
  const replyTextEl = document.getElementById("reply-text");
  const ttsPlayBtn = document.getElementById("tts-play-btn");
  const ttsTimeTag = document.getElementById("tts-time-tag");
  const audioPlayer = document.getElementById("audio-player");

  const totalLatencyChip = document.getElementById("total-latency-chip");
  const timingTableBody = document.getElementById("timing-table-body");
  const toolLogContainer = document.getElementById("tool-log-container");
  const refreshLogBtn = document.getElementById("refresh-log-btn");

  // State
  let isRecording = false;
  let audioContext = null;
  let mediaStream = null;
  let processorNode = null;
  let pcmData = [];
  let silenceTimer = null;
  let speechStarted = false;
  let lastAudioUrl = null;

  // 1. Update Mode Summary Text (in English)
  function updateModeIndicator() {
    const act = switchActions.checked;
    const cln = switchCleanup.checked;
    const tls = switchTools.checked;

    let desc = "";
    if (!act) {
      desc = cln ? "Dictation only (Cleanup enabled, decider skipped)" : "Raw dictation (Cleanup disabled)";
    } else if (!tls) {
      desc = "Command assistant (Tools disabled, speech reply only)";
    } else {
      desc = "Full command assistant with tools & cards";
    }
    modeText.textContent = `Mode: ${desc}`;
  }

  switchActions.addEventListener("change", updateModeIndicator);
  switchCleanup.addEventListener("change", updateModeIndicator);
  switchTools.addEventListener("change", updateModeIndicator);
  updateModeIndicator();

  // 2. Microphone Recording with Web Audio API (16kHz Mono WAV + Silence Detection)
  micBtn.addEventListener("click", () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  async function startRecording() {
    try {
      pcmData = [];
      speechStarted = false;

      audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000,
      });

      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      const source = audioContext.createMediaStreamSource(mediaStream);
      processorNode = audioContext.createScriptProcessor(4096, 1, 1);

      processorNode.onaudioprocess = (e) => {
        if (!isRecording) return;
        const channel = e.inputBuffer.getChannelData(0);
        pcmData.push(new Float32Array(channel));

        // Silence / Voice Activity Detection
        let sum = 0;
        for (let i = 0; i < channel.length; i++) {
          sum += channel[i] * channel[i];
        }
        const rms = Math.sqrt(sum / channel.length);

        if (rms > 0.03) {
          speechStarted = true;
          if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
          }
        } else if (speechStarted) {
          if (!silenceTimer) {
            // ~1.2s silence threshold
            silenceTimer = setTimeout(() => {
              console.log("[Mic] Auto-stopping on 1.2s silence");
              stopRecording();
            }, 1200);
          }
        }
      };

      source.connect(processorNode);
      processorNode.connect(audioContext.destination);

      isRecording = true;
      micBtn.classList.add("recording");
      visualizer.classList.add("active");
      micStatus.textContent = "Listening... speak now";
    } catch (err) {
      console.error("Mic access error:", err);
      alert("Microphone permission denied or not supported: " + err.message);
    }
  }

  function stopRecording() {
    if (!isRecording) return;
    isRecording = false;

    if (silenceTimer) {
      clearTimeout(silenceTimer);
      silenceTimer = null;
    }

    micBtn.classList.remove("recording");
    visualizer.classList.remove("active");
    micStatus.textContent = "Processing audio...";

    if (mediaStream) {
      mediaStream.getTracks().forEach((track) => track.stop());
    }
    if (processorNode) {
      processorNode.disconnect();
    }
    if (audioContext && audioContext.state !== "closed") {
      audioContext.close();
    }

    // Merge PCM buffers
    let totalLength = 0;
    for (const chunk of pcmData) {
      totalLength += chunk.length;
    }
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of pcmData) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    if (totalLength < 4000) {
      micStatus.textContent = "Audio too short. Please try again.";
      return;
    }

    const wavBlob = encodeWAV(merged, 16000);
    sendAudioRequest(wavBlob);
  }

  // 16-bit Mono 16kHz PCM WAV Encoder
  function encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    /* RIFF identifier */
    writeString(view, 0, "RIFF");
    /* file length */
    view.setUint32(4, 36 + samples.length * 2, true);
    /* RIFF type */
    writeString(view, 8, "WAVE");
    /* format chunk identifier */
    writeString(view, 12, "fmt ");
    /* format chunk length */
    view.setUint32(16, 16, true);
    /* sample format (raw PCM) */
    view.setUint16(20, 1, true);
    /* channel count (mono) */
    view.setUint16(22, 1, true);
    /* sample rate */
    view.setUint32(24, sampleRate, true);
    /* byte rate (sampleRate * 2) */
    view.setUint32(28, sampleRate * 2, true);
    /* block align */
    view.setUint16(32, 2, true);
    /* bits per sample */
    view.setUint16(34, 16, true);
    /* data chunk identifier */
    writeString(view, 36, "data");
    /* data chunk length */
    view.setUint32(40, samples.length * 2, true);

    // Float32 to Int16 PCM
    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }

    return new Blob([view], { type: "audio/wav" });
  }

  function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }

  // 3. Audio & Text Pipeline Requests
  async function sendAudioRequest(blob) {
    const clientStartTime = performance.now();
    const formData = new FormData();
    formData.append("audio", blob, "recording.wav");
    formData.append("actions", switchActions.checked);
    formData.append("cleanup", switchCleanup.checked);
    formData.append("tools", switchTools.checked);

    try {
      const resp = await fetch("/api/process", {
        method: "POST",
        body: formData,
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Request failed");
      }
      const data = await resp.json();
      const clientTotalMs = performance.now() - clientStartTime;
      renderResult(data, clientTotalMs);
      micStatus.textContent = "Ready! Click mic to speak again.";
    } catch (err) {
      console.error(err);
      micStatus.textContent = "Error: " + err.message;
    }
  }

  textForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = textInput.value.trim();
    if (!text) return;

    const clientStartTime = performance.now();
    micStatus.textContent = "Processing text...";

    try {
      const resp = await fetch("/api/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          actions: switchActions.checked,
          cleanup: switchCleanup.checked,
          tools: switchTools.checked,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || "Request failed");
      }

      const data = await resp.json();
      const clientTotalMs = performance.now() - clientStartTime;
      renderResult(data, clientTotalMs);
      micStatus.textContent = "Ready! Click mic to speak again.";
      textInput.value = "";
    } catch (err) {
      console.error(err);
      micStatus.textContent = "Error: " + err.message;
    }
  });

  // 4. Render Results to UI
  function renderResult(data, clientTotalMs) {
    // Transcripts
    rawTranscript.textContent = data.raw_text || "—";
    cleanedTranscript.textContent = data.cleaned_text || "—";

    // Branch badge
    if (data.branch === "command") {
      branchBadge.textContent = "Command";
      branchBadge.className = "branch-badge command";
    } else {
      branchBadge.textContent = "Dictation";
      branchBadge.className = "branch-badge dictation";
    }

    // Outcome Card
    renderCard(data.card);

    // Reply Box & Audio TTS
    if (data.reply_text) {
      replyBox.classList.remove("hidden");
      replyTextEl.textContent = data.reply_text;
      fetchAndPlayTTS(data.reply_text);
    } else {
      replyBox.classList.add("hidden");
    }

    // Timing Table
    renderTimingTable(data.timings, clientTotalMs);

    // Refresh Tool Log
    fetchToolLog();
  }

  function renderCard(card) {
    if (!card) {
      cardContainer.innerHTML = `<div class="empty-state"><p>No card available.</p></div>`;
      cardBadge.textContent = "—";
      return;
    }

    cardBadge.textContent = card.badge || card.type;
    let cardHtml = "";

    if (card.type === "calendar") {
      cardHtml = `
        <div class="outcome-card calendar">
          <div class="card-top">
            <span class="card-title">${card.title}</span>
            <span class="card-chip">${card.status}</span>
          </div>
          <div class="card-body-text"><strong>${card.event_title}</strong></div>
          <div class="meta-grid">
            <div class="meta-field"><span class="meta-key">Date</span><span class="meta-val">${card.date}</span></div>
            <div class="meta-field"><span class="meta-key">Time</span><span class="meta-val">${card.start_time}</span></div>
            <div class="meta-field"><span class="meta-key">Attendees</span><span class="meta-val">${card.attendees.join(", ") || "None"}</span></div>
          </div>
        </div>
      `;
    } else if (card.type === "email") {
      cardHtml = `
        <div class="outcome-card email">
          <div class="card-top">
            <span class="card-title">${card.title}</span>
            <span class="card-chip">${card.status}</span>
          </div>
          <div class="meta-grid">
            <div class="meta-field"><span class="meta-key">To</span><span class="meta-val">${card.to}</span></div>
            <div class="meta-field"><span class="meta-key">Subject</span><span class="meta-val">${card.subject}</span></div>
          </div>
          <div class="card-body-text">"${card.body}"</div>
        </div>
      `;
    } else if (card.type === "reminder") {
      cardHtml = `
        <div class="outcome-card reminder">
          <div class="card-top">
            <span class="card-title">${card.title}</span>
            <span class="card-chip">${card.status}</span>
          </div>
          <div class="card-body-text"><strong>${card.text}</strong></div>
          <div class="meta-grid">
            <div class="meta-field"><span class="meta-key">Date</span><span class="meta-val">${card.date}</span></div>
            <div class="meta-field"><span class="meta-key">Time</span><span class="meta-val">${card.time}</span></div>
          </div>
        </div>
      `;
    } else if (card.type === "question") {
      cardHtml = `
        <div class="outcome-card question">
          <div class="card-top">
            <span class="card-title">${card.title}</span>
            <span class="card-chip">Missing Info</span>
          </div>
          <div class="card-body-text">${card.question}</div>
        </div>
      `;
    } else if (card.type === "refusal") {
      cardHtml = `
        <div class="outcome-card refusal">
          <div class="card-top">
            <span class="card-title">${card.title}</span>
            <span class="card-chip">Refusal</span>
          </div>
          <div class="card-body-text">${card.reason}</div>
        </div>
      `;
    } else if (card.type === "tools_disabled") {
      cardHtml = `
        <div class="outcome-card tools_disabled">
          <div class="card-top">
            <span class="card-title">${card.title}</span>
            <span class="card-chip">Tools Off</span>
          </div>
          <div class="card-body-text">${card.explanation}</div>
        </div>
      `;
    } else if (card.type === "dictation") {
      cardHtml = `
        <div class="outcome-card dictation">
          <div class="card-top">
            <span class="card-title">${card.title}</span>
            <span class="card-chip">${card.cleaned ? "Cleaned" : "Raw"}</span>
          </div>
          <div class="card-body-text">${card.text}</div>
          <button class="copy-btn" id="copy-text-btn">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            <span>Copy Text</span>
          </button>
        </div>
      `;
    } else {
      cardHtml = `
        <div class="outcome-card">
          <div class="card-body-text">${card.text || JSON.stringify(card)}</div>
        </div>
      `;
    }

    cardContainer.innerHTML = cardHtml;

    const copyBtn = document.getElementById("copy-text-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => {
        navigator.clipboard.writeText(card.text);
        copyBtn.querySelector("span").textContent = "Copied!";
        setTimeout(() => {
          copyBtn.querySelector("span").textContent = "Copy Text";
        }, 2000);
      });
    }
  }

  // 5. TTS Voice Synthesis & Playback
  async function fetchAndPlayTTS(text) {
    ttsTimeTag.textContent = "Generating speech...";
    const t0 = performance.now();

    try {
      const resp = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      if (!resp.ok) throw new Error("TTS failed");

      const ttsLatency = resp.headers.get("X-TTS-Latency-MS") || Math.round(performance.now() - t0);
      ttsTimeTag.textContent = `TTS: ${ttsLatency} ms`;

      const audioBlob = await resp.blob();
      if (lastAudioUrl) URL.revokeObjectURL(lastAudioUrl);
      lastAudioUrl = URL.createObjectURL(audioBlob);

      audioPlayer.src = lastAudioUrl;
      audioPlayer.play();

      // Update TTS row in timing table
      const ttsRow = document.getElementById("timing-row-tts");
      if (ttsRow) {
        ttsRow.innerHTML = `
          <td><strong>TTS (Vertex Voice)</strong></td>
          <td><span class="status-pill status-waited">Spoken</span></td>
          <td>${ttsLatency} ms</td>
        `;
      }
    } catch (e) {
      console.warn("TTS playback error:", e);
      ttsTimeTag.textContent = "Voice unavailable";
    }
  }

  ttsPlayBtn.addEventListener("click", () => {
    if (audioPlayer.src) {
      audioPlayer.currentTime = 0;
      audioPlayer.play();
    }
  });

  // 6. Timing Table
  function renderTimingTable(timings, clientTotalMs) {
    if (!timings) return;

    totalLatencyChip.textContent = `Total Latency: ${timings.total_ms || clientTotalMs.toFixed(1)} ms`;

    const asrPill = timings.asr_ms > 0 ? `<span class="status-pill status-waited">Transcribed</span>` : `<span class="status-pill status-skipped">Skipped (Text)</span>`;
    const deciderPill = timings.decider_ms > 0 ? `<span class="status-pill status-waited">Waited</span>` : `<span class="status-pill status-skipped">Skipped</span>`;
    const cleanupPill = timings.cleanup_discarded ? `<span class="status-pill status-discarded">Discarded (0ms)</span>` : (timings.cleanup_ms > 0 ? `<span class="status-pill status-waited">Waited</span>` : `<span class="status-pill status-skipped">Skipped</span>`);
    const agentPill = timings.agent_ms > 0 ? `<span class="status-pill status-waited">Waited</span>` : `<span class="status-pill status-skipped">Skipped</span>`;
    const toolPill = timings.tool_call_ms > 0 ? `<span class="status-pill status-waited">Executed</span>` : `<span class="status-pill status-ready">—</span>`;

    timingTableBody.innerHTML = `
      <tr>
        <td><strong>ASR (Indic Conformer)</strong></td>
        <td>${asrPill}</td>
        <td>${timings.asr_ms} ms</td>
      </tr>
      <tr>
        <td><strong>Decider (Gemini)</strong></td>
        <td>${deciderPill}</td>
        <td>${timings.decider_ms} ms</td>
      </tr>
      <tr>
        <td><strong>Cleanup (Gemini)</strong></td>
        <td>${cleanupPill}</td>
        <td>${timings.cleanup_ms} ms</td>
      </tr>
      <tr>
        <td><strong>Agent (System 2)</strong></td>
        <td>${agentPill}</td>
        <td>${timings.agent_ms} ms</td>
      </tr>
      <tr>
        <td><strong>Tool Execution</strong></td>
        <td>${toolPill}</td>
        <td>${timings.tool_call_ms} ms</td>
      </tr>
      <tr id="timing-row-tts">
        <td><strong>TTS (Vertex Voice)</strong></td>
        <td><span class="status-pill status-ready">Ready</span></td>
        <td>—</td>
      </tr>
      <tr class="total-row">
        <td><strong>Pipeline Total</strong></td>
        <td><strong>Completed</strong></td>
        <td><strong>${timings.pipeline_total_ms || timings.total_ms} ms</strong></td>
      </tr>
    `;
  }

  // 7. Tool Calls Log
  async function fetchToolLog() {
    try {
      const resp = await fetch("/api/tools/log");
      if (!resp.ok) return;
      const data = await resp.json();
      const logs = data.logs || [];

      if (logs.length === 0) {
        toolLogContainer.innerHTML = `<p class="empty-log-text">No tool calls logged yet.</p>`;
        return;
      }

      toolLogContainer.innerHTML = logs.map((item) => {
        const timeStr = item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : "";
        const argsStr = JSON.stringify(item.arguments || {});
        return `
          <div class="tool-log-entry">
            <span class="log-time">[${timeStr}]</span>
            <span class="log-tool">${item.tool}</span>: ${argsStr}
          </div>
        `;
      }).join("");
    } catch (e) {
      console.warn("Tool log error:", e);
    }
  }

  refreshLogBtn.addEventListener("click", fetchToolLog);
  fetchToolLog();
});
