// Open Voice V3 Web Demo Controller
document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const micBtn = document.getElementById("mic-btn");
  const micStatus = document.getElementById("mic-status");
  const visualizer = document.getElementById("visualizer-container");
  const visualizerBars = document.querySelectorAll(".visualizer-bar");
  const textForm = document.getElementById("text-form");
  const textInput = document.getElementById("text-input");

  const switchActions = document.getElementById("switch-actions");
  const switchCleanup = document.getElementById("switch-cleanup");
  const switchTools = document.getElementById("switch-tools");
  const switchTTS = document.getElementById("switch-tts");
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
  let analyser = null;
  let processorNode = null;
  let pcmData = [];
  let silenceTimer = null;
  let speechStarted = false;
  let animFrameId = null;
  let lastAudioUrl = null;
  let currentReplyText = "";

  // 1. Customer Mode Indicator (Section 8 of V3 Plan)
  function updateModeIndicator() {
    const act = switchActions.checked;
    const cln = switchCleanup.checked;
    const tls = switchTools.checked;
    const tts = switchTTS ? switchTTS.checked : true;

    let desc = "";
    if (!act && cln) {
      desc = "Actions off, Cleanup on (Pure dictation, cleaned text only, decider skipped)";
    } else if (!act && !cln) {
      desc = "Actions off, Cleanup off (Raw dictation as-is, cleanup & decider skipped)";
    } else if (act && !tls && cln) {
      desc = "Actions on, Tools off, Cleanup on (Commands recognized, words reply only, no tool call)";
    } else if (act && tls && cln) {
      desc = "Actions on, Tools on, Cleanup on (Full command assistant, dummy tools & cards)";
    } else if (act && !cln) {
      desc = "Actions on, Cleanup off (Raw text sent directly to decider/agent)";
    } else {
      desc = "Custom configuration";
    }
    if (!tts) {
      desc += " [TTS Muted]";
    }
    modeText.textContent = `Active Mode: ${desc}`;
  }

  switchActions.addEventListener("change", updateModeIndicator);
  switchCleanup.addEventListener("change", updateModeIndicator);
  switchTools.addEventListener("change", updateModeIndicator);
  if (switchTTS) switchTTS.addEventListener("change", updateModeIndicator);
  updateModeIndicator();

  // 2. Microphone Capture with Real-Time Audio Meter & Silence Auto-Stop
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
          autoGainControl: true,
        },
      });

      const source = audioContext.createMediaStreamSource(mediaStream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 64;

      processorNode = audioContext.createScriptProcessor(4096, 1, 1);

      processorNode.onaudioprocess = (e) => {
        if (!isRecording) return;
        const channel = e.inputBuffer.getChannelData(0);
        pcmData.push(new Float32Array(channel));

        // Volume Calculation
        let sum = 0;
        for (let i = 0; i < channel.length; i++) {
          sum += channel[i] * channel[i];
        }
        const rms = Math.sqrt(sum / channel.length);

        // Voice Activity Detection & Silence Auto-Stop (~1.2s silence)
        if (rms > 0.025) {
          speechStarted = true;
          micStatus.textContent = "Speaking detected... (Listening)";
          if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
          }
        } else if (speechStarted) {
          if (!silenceTimer) {
            silenceTimer = setTimeout(() => {
              console.log("[Mic] Auto-stopping after 1.2s silence");
              stopRecording();
            }, 1200);
          }
        }
      };

      source.connect(analyser);
      analyser.connect(processorNode);
      processorNode.connect(audioContext.destination);

      isRecording = true;
      micBtn.classList.add("recording");
      visualizer.classList.add("active");
      micStatus.textContent = "Listening... speak now";

      // Live Visualizer loop
      updateVisualizerMeter();
    } catch (err) {
      console.error("Mic access error:", err);
      alert("Microphone permission denied or not supported: " + err.message);
    }
  }

  function updateVisualizerMeter() {
    if (!isRecording || !analyser) return;

    const freqData = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(freqData);

    // Drive the 5 bars with live frequency amplitudes
    for (let i = 0; i < visualizerBars.length; i++) {
      const val = freqData[i * 2] || 0;
      const height = Math.max(6, Math.min(26, Math.round((val / 255) * 26)));
      visualizerBars[i].style.height = `${height}px`;
    }

    animFrameId = requestAnimationFrame(updateVisualizerMeter);
  }

  function stopRecording() {
    if (!isRecording) return;
    isRecording = false;

    if (silenceTimer) {
      clearTimeout(silenceTimer);
      silenceTimer = null;
    }
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }

    micBtn.classList.remove("recording");
    visualizer.classList.remove("active");
    visualizerBars.forEach((bar) => (bar.style.height = "6px"));
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

    if (totalLength < 3200) {
      micStatus.textContent = "Audio too short. Please speak again.";
      return;
    }

    const wavBlob = encodeWAV(merged, 16000);
    sendAudioRequest(wavBlob);
  }

  // 16-bit Mono 16kHz PCM WAV Encoder
  function encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(view, 8, "WAVE");
    writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); // PCM
    view.setUint16(22, 1, true); // mono
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, "data");
    view.setUint32(40, samples.length * 2, true);

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
    rawTranscript.textContent = "Transcribing audio clip...";
    cleanedTranscript.textContent = "Waiting for cleanup...";
    branchBadge.textContent = "Processing...";
    branchBadge.className = "branch-badge";

    const formData = new FormData();
    formData.append("audio", blob, "speech.wav");
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
      renderResult(data, clientTotalMs, clientStartTime);
      micStatus.textContent = "Ready! Click mic to speak again.";
    } catch (err) {
      console.error(err);
      rawTranscript.textContent = "—";
      cleanedTranscript.textContent = "—";
      micStatus.textContent = "Error: " + err.message;
    }
  }

  textForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = textInput.value.trim();
    if (!text) return;

    const clientStartTime = performance.now();
    rawTranscript.textContent = text;
    cleanedTranscript.textContent = "Processing...";
    branchBadge.textContent = "Processing...";
    branchBadge.className = "branch-badge";
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
      renderResult(data, clientTotalMs, clientStartTime);
      micStatus.textContent = "Ready! Click mic to speak again.";
      textInput.value = "";
    } catch (err) {
      console.error(err);
      micStatus.textContent = "Error: " + err.message;
    }
  });

  // 4. Render Results to UI (V3c specification)
  function renderResult(data, clientTotalMs, clientStartTime) {
    // Transcript area: raw text, then cleaned text
    rawTranscript.textContent = data.raw_text || "—";
    if (data.switches && !data.switches.cleanup) {
      cleanedTranscript.textContent = `${data.raw_text} (Cleanup off)`;
    } else {
      cleanedTranscript.textContent = data.cleaned_text || data.raw_text || "—";
    }

    // Branch badge
    if (data.branch === "command") {
      branchBadge.textContent = "Command";
      branchBadge.className = "branch-badge command";
    } else {
      branchBadge.textContent = "Dictation";
      branchBadge.className = "branch-badge dictation";
    }

    // Outcome Card (rendered immediately)
    renderCard(data.card);

    // Reply Box & Audio TTS
    currentReplyText = data.reply_text || "";
    if (data.reply_text) {
      replyBox.classList.remove("hidden");
      replyTextEl.textContent = data.reply_text;
      ttsTimeTag.textContent = "";
      if (lastAudioUrl) {
        URL.revokeObjectURL(lastAudioUrl);
        lastAudioUrl = null;
      }
      audioPlayer.src = "";
    } else {
      replyBox.classList.add("hidden");
      currentReplyText = "";
    }

    // Timing Table matching customer switches & TTS state
    const ttsEnabled = switchTTS ? switchTTS.checked : true;
    renderTimingTable(data.timings, data.switches, clientTotalMs, !!data.reply_text, ttsEnabled);

    // If TTS is enabled and reply text exists, fetch and play voice synthesis
    if (data.reply_text && ttsEnabled) {
      fetchAndPlayTTS(data.reply_text, clientStartTime);
    }

    // Refresh Tool Log (Section 9: last 5 calls refreshed after each command)
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

  // 5. TTS Voice Synthesis & Playback (Section 9 of V3 Plan)
  async function fetchAndPlayTTS(text, clientStartTime) {
    if (!text) return;
    ttsTimeTag.textContent = "Synthesizing voice...";
    const t0 = performance.now();

    const ttsRow = document.getElementById("timing-row-tts");
    if (ttsRow) {
      ttsRow.innerHTML = `
        <td><strong>TTS (Vertex Voice)</strong></td>
        <td><span class="status-pill status-waited">Synthesizing</span></td>
        <td>...</td>
      `;
    }
    const ttfaRow = document.getElementById("timing-row-ttfa");
    if (ttfaRow) {
      ttfaRow.innerHTML = `
        <td><strong>Time to First Audio</strong></td>
        <td><span class="status-pill status-waited">Waiting</span></td>
        <td id="table-ttfa-ms">...</td>
      `;
    }

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
      const playPromise = audioPlayer.play();
      if (playPromise !== undefined) {
        playPromise.catch((e) => {
          console.warn("Autoplay interrupted or blocked:", e);
        });
      }

      const ttfa = clientStartTime ? Math.round(performance.now() - clientStartTime) : Math.round(ttsLatency);

      if (ttsRow) {
        ttsRow.innerHTML = `
          <td><strong>TTS (Vertex Voice)</strong></td>
          <td><span class="status-pill status-waited">Spoken</span></td>
          <td>${ttsLatency} ms</td>
        `;
      }
      if (ttfaRow) {
        ttfaRow.innerHTML = `
          <td><strong>Time to First Audio</strong></td>
          <td><span class="status-pill status-waited">Playing</span></td>
          <td id="table-ttfa-ms">${ttfa} ms</td>
        `;
      }
    } catch (e) {
      console.warn("TTS playback error:", e);
      ttsTimeTag.textContent = "Voice unavailable";
      if (ttsRow) {
        ttsRow.innerHTML = `
          <td><strong>TTS (Vertex Voice)</strong></td>
          <td><span class="status-pill status-discarded">Failed</span></td>
          <td>—</td>
        `;
      }
      if (ttfaRow) {
        ttfaRow.innerHTML = `
          <td><strong>Time to First Audio</strong></td>
          <td><span class="status-pill status-discarded">Failed</span></td>
          <td id="table-ttfa-ms">—</td>
        `;
      }
    }
  }

  ttsPlayBtn.addEventListener("click", () => {
    if (audioPlayer.src && audioPlayer.src !== window.location.href) {
      audioPlayer.currentTime = 0;
      audioPlayer.play();
    } else if (currentReplyText) {
      fetchAndPlayTTS(currentReplyText, performance.now());
    }
  });

  // 6. Timing Table (Refined for Section 8 customer switch expectations & TTFA)
  function renderTimingTable(timings, switches, clientTotalMs, hasReplyText, ttsEnabled) {
    if (!timings) return;

    totalLatencyChip.textContent = `Total Latency: ${timings.total_ms || clientTotalMs.toFixed(1)} ms`;

    // ASR
    const asrPill = timings.asr_ms > 0 ? `<span class="status-pill status-waited">Transcribed</span>` : `<span class="status-pill status-skipped">Skipped (Text)</span>`;
    const asrTime = timings.asr_ms > 0 ? `${timings.asr_ms} ms` : `—`;

    // Decider: if Actions off -> no decider time in panel
    let deciderPill = `<span class="status-pill status-skipped">Skipped (Actions Off)</span>`;
    let deciderTime = `—`;
    if (switches && switches.actions) {
      deciderPill = `<span class="status-pill status-waited">Waited</span>`;
      deciderTime = `${timings.decider_ms} ms`;
    }

    // Cleanup: if Cleanup off -> no cleanup time in panel
    let cleanupPill = `<span class="status-pill status-skipped">Disabled (Off)</span>`;
    let cleanupTime = `—`;
    if (switches && switches.cleanup) {
      if (timings.cleanup_discarded) {
        cleanupPill = `<span class="status-pill status-discarded">Discarded (0ms active)</span>`;
        cleanupTime = `0.0 ms`;
      } else {
        cleanupPill = `<span class="status-pill status-waited">Waited</span>`;
        cleanupTime = `${timings.cleanup_ms} ms`;
      }
    }

    // Agent
    let agentPill = `<span class="status-pill status-skipped">Skipped (Dictation)</span>`;
    let agentTime = `—`;
    if (timings.agent_ms > 0) {
      agentPill = `<span class="status-pill status-waited">Waited</span>`;
      agentTime = `${timings.agent_ms} ms`;
    }

    // Tools
    let toolPill = `<span class="status-pill status-ready">—</span>`;
    let toolTime = `—`;
    if (switches && switches.tools && timings.tool_call_ms > 0) {
      toolPill = `<span class="status-pill status-waited">Executed</span>`;
      toolTime = `${timings.tool_call_ms} ms`;
    } else if (switches && !switches.tools) {
      toolPill = `<span class="status-pill status-skipped">Tools Disabled</span>`;
    }

    // TTS & TTFA initial state in table
    let ttsPill = `<span class="status-pill status-skipped">Skipped (Dictation)</span>`;
    let ttsTime = `—`;
    let ttfaPill = `<span class="status-pill status-skipped">Skipped</span>`;
    let ttfaTime = `—`;

    if (hasReplyText) {
      if (ttsEnabled) {
        ttsPill = `<span class="status-pill status-waited">Synthesizing...</span>`;
        ttsTime = `...`;
        ttfaPill = `<span class="status-pill status-waited">Waiting...</span>`;
        ttfaTime = `...`;
      } else {
        ttsPill = `<span class="status-pill status-skipped">Disabled (TTS Off)</span>`;
        ttsTime = `—`;
        ttfaPill = `<span class="status-pill status-skipped">Disabled</span>`;
        ttfaTime = `—`;
      }
    }

    timingTableBody.innerHTML = `
      <tr>
        <td><strong>ASR (Indic Conformer)</strong></td>
        <td>${asrPill}</td>
        <td>${asrTime}</td>
      </tr>
      <tr>
        <td><strong>Decider (Gemini)</strong></td>
        <td>${deciderPill}</td>
        <td>${deciderTime}</td>
      </tr>
      <tr>
        <td><strong>Cleanup (Gemini)</strong></td>
        <td>${cleanupPill}</td>
        <td>${cleanupTime}</td>
      </tr>
      <tr>
        <td><strong>Agent (System 2)</strong></td>
        <td>${agentPill}</td>
        <td>${agentTime}</td>
      </tr>
      <tr>
        <td><strong>Tool Execution</strong></td>
        <td>${toolPill}</td>
        <td>${toolTime}</td>
      </tr>
      <tr id="timing-row-tts">
        <td><strong>TTS (Vertex Voice)</strong></td>
        <td>${ttsPill}</td>
        <td>${ttsTime}</td>
      </tr>
      <tr id="timing-row-ttfa">
        <td><strong>Time to First Audio</strong></td>
        <td>${ttfaPill}</td>
        <td id="table-ttfa-ms">${ttfaTime}</td>
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
