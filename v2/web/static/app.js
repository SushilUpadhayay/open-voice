(() => {
  // DOM Elements
  const statusEl = document.getElementById("connectionStatus");
  const polishedDisplay = document.getElementById("polishedTextDisplay");
  const tailDisplay = document.getElementById("inFlightTailDisplay");
  const wordCountBadge = document.getElementById("wordCountBadge");
  const micBtn = document.getElementById("micBtn");
  const micCaption = document.getElementById("micCaption");
  const waveformEl = document.getElementById("waveform");
  const copyBtn = document.getElementById("copyBtn");
  const clearBtn = document.getElementById("clearBtn");
  const demoNepaliBtn = document.getElementById("demoNepaliBtn");
  const demoEnglishBtn = document.getElementById("demoEnglishBtn");

  // Telemetry elements
  const telemetryBypass = document.getElementById("telemetryBypass");
  const telemetryCalls = document.getElementById("telemetryCalls");
  const telemetryAvgLat = document.getElementById("telemetryAvgLat");
  const engineState = document.getElementById("engineState");

  // Audio & WebSocket state
  let ws = null;
  let isRecording = false;
  let audioContext = null;
  let mediaStream = null;
  let processorNode = null;
  let sourceNode = null;

  // Telemetry counters
  let bypassCount = 0;
  let callCount = 0;
  let latencies = [];

  // WebSocket Connection
  function connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/dictate`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      statusEl.classList.remove("disconnected");
      statusEl.querySelector(".status-text").textContent = "Connected";
    };

    ws.onclose = () => {
      statusEl.classList.add("disconnected");
      statusEl.querySelector(".status-text").textContent = "Disconnected (Retrying...)";
      setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = (err) => {
      console.error("WebSocket error:", err);
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleServerMessage(data);
      } catch (e) {
        console.error("Failed to parse message:", e);
      }
    };
  }

  function handleServerMessage(data) {
    if (data.type === "raw_tail") {
      const tail = data.tail || "";
      if (tail) {
        tailDisplay.textContent = tail;
      } else {
        tailDisplay.innerHTML = isRecording
          ? '<span class="tail-placeholder">Listening... speak now.</span>'
          : '<span class="tail-placeholder">Microphone off. Click the mic button to speak.</span>';
      }
    } else if (data.type === "commit_chunk") {
      const fullPolished = data.full_polished || "";
      polishedDisplay.textContent = fullPolished;
      updateWordCount(fullPolished);

      const tail = data.tail || "";
      if (tail) {
        tailDisplay.textContent = tail;
      } else {
        tailDisplay.innerHTML = isRecording
          ? '<span class="tail-placeholder">Listening... speak now.</span>'
          : '<span class="tail-placeholder">Microphone off. Click the mic button to speak.</span>';
      }

      // Update telemetry
      if (data.bypassed) {
        bypassCount++;
        telemetryBypass.textContent = bypassCount;
      } else {
        callCount++;
        telemetryCalls.textContent = callCount;
        if (data.latency_ms) {
          latencies.push(data.latency_ms);
          const avg = latencies.reduce((a, b) => a + b, 0) / latencies.length;
          telemetryAvgLat.textContent = `Avg: ${Math.round(avg)}ms`;
        }
      }
    } else if (data.type === "finalized") {
      const finalized = data.full_text || "";
      if (finalized) {
        polishedDisplay.textContent = finalized;
        updateWordCount(finalized);
      }
      tailDisplay.innerHTML = '<span class="tail-placeholder">Dictation complete. Click microphone to speak again.</span>';
      micCaption.textContent = "Click to start streaming";
      engineState.textContent = "Idle";
    }
  }

  function updateWordCount(text) {
    const words = text.trim().split(/\s+/).filter(Boolean);
    wordCountBadge.textContent = `${words.length} words`;
  }

  // Audio Capture & Downsampling (16kHz PCM)
  async function startRecording() {
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000,
      });

      sourceNode = audioContext.createMediaStreamSource(mediaStream);
      // ScriptProcessor for 16-bit PCM streaming chunks
      processorNode = audioContext.createScriptProcessor(4096, 1, 1);

      processorNode.onaudioprocess = (e) => {
        if (!isRecording || !ws || ws.readyState !== WebSocket.OPEN) return;

        const inputData = e.inputBuffer.getChannelData(0);
        // Convert Float32 to Int16 PCM
        const pcm16 = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        ws.send(pcm16.buffer);
      };

      sourceNode.connect(processorNode);
      processorNode.connect(audioContext.destination);

      isRecording = true;
      micBtn.classList.add("recording");
      waveformEl.classList.add("active");
      micCaption.textContent = "Recording... Click to stop";
      tailDisplay.innerHTML = '<span class="tail-placeholder">Listening... speak now.</span>';
      engineState.textContent = "Listening";
    } catch (err) {
      console.error("Microphone access error:", err);
      alert("Could not access microphone: " + err.message);
      stopRecording();
    }
  }

  function stopRecording() {
    isRecording = false;
    micBtn.classList.remove("recording");
    waveformEl.classList.remove("active");
    micCaption.textContent = "Processing final speech...";
    tailDisplay.innerHTML = '<span class="tail-placeholder">Processing speech and polishing...</span>';
    engineState.textContent = "Finalizing";

    if (processorNode) {
      processorNode.disconnect();
      processorNode = null;
    }
    if (sourceNode) {
      sourceNode.disconnect();
      sourceNode = null;
    }
    if (audioContext) {
      audioContext.close();
      audioContext = null;
    }
    if (mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
    }

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
    }
  }

  // Event Listeners
  micBtn.addEventListener("click", () => {
    if (isRecording) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  copyBtn.addEventListener("click", () => {
    const text = polishedDisplay.textContent.trim();
    if (text) {
      navigator.clipboard.writeText(text);
      const originalText = copyBtn.innerHTML;
      copyBtn.innerHTML = '<span style="font-size:12px;color:#10b981;">Copied!</span>';
      setTimeout(() => (copyBtn.innerHTML = originalText), 1500);
    }
  });

  clearBtn.addEventListener("click", () => {
    polishedDisplay.innerHTML = '<span class="placeholder-text">Polished sentences will lock in here as you speak...</span>';
    tailDisplay.innerHTML = '<span class="tail-placeholder">Microphone is off. Click the mic button below to dictate.</span>';
    wordCountBadge.textContent = "0 words";
    bypassCount = 0;
    callCount = 0;
    latencies = [];
    telemetryBypass.textContent = "0";
    telemetryCalls.textContent = "0";
    telemetryAvgLat.textContent = "Avg: 0ms";
    engineState.textContent = "Idle";
  });

  // Simulated Speech Demonstrations
  async function runSimulation(wordsWithPauses) {
    if (isRecording) stopRecording();
    clearBtn.click();
    engineState.textContent = "Simulating";

    for (let i = 0; i < wordsWithPauses.length; i++) {
      const item = wordsWithPauses[i];
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: "text_chunk",
            text: item.word,
            pause: item.pause || false,
          })
        );
      }
      await new Promise((r) => setTimeout(r, item.delay || 350));
    }

    // Stop and reconcile
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
    }
  }

  demoNepaliBtn.addEventListener("click", () => {
    const nepaliSequence = [
      { word: "नमस्ते", delay: 300 },
      { word: "मेरो", delay: 250 },
      { word: "नाम", delay: 250 },
      { word: "उम्", delay: 400 },
      { word: "आकाश", delay: 300, pause: true },
      { word: "हो", delay: 300 },
      { word: "र", delay: 250 },
      { word: "म", delay: 250 },
      { word: "अहिले", delay: 300 },
      { word: "काठमाडौँमा", delay: 350 },
      { word: "बस्छु", delay: 400, pause: true },
    ];
    runSimulation(nepaliSequence);
  });

  demoEnglishBtn.addEventListener("click", () => {
    const englishSequence = [
      { word: "hello", delay: 300 },
      { word: "my", delay: 250 },
      { word: "name", delay: 250 },
      { word: "um", delay: 350 },
      { word: "is", delay: 250 },
      { word: "aakash", delay: 400, pause: true },
      { word: "and", delay: 250 },
      { word: "i", delay: 250 },
      { word: "am", delay: 250 },
      { word: "working", delay: 300 },
      { word: "on", delay: 250 },
      { word: "open", delay: 300 },
      { word: "voice", delay: 350, pause: true },
    ];
    runSimulation(englishSequence);
  });

  // Initialize WebSocket
  connectWebSocket();
})();
