/**
 * Open Voice Dictation — Frontend Client
 * Bi-directional Web Audio 16kHz streamer & Wispr Flow sentence-level polish
 */

class DictationApp {
  constructor() {
    this.isRecording = false;
    this.ws = null;
    this.audioContext = null;
    this.mediaStream = null;
    this.processor = null;
    this.analyser = null;
    this.animationFrameId = null;

    this.sentenceMap = new Map();
    this.liveTail = '';
    this.displayCounter = 0;
    this.generation = 0;
    this.lastClearTime = 0;
    this.isWavStreaming = false;
    this.latestAsrMs = null;
    this.latestLlmMs = null;
    this.smoothedVolume = 0;
    this.vadIsSpeaking = false;

    this.initElements();
    this.initEvents();
    this.initWebSocket();
    this.initCanvas();
    this.fetchSystemStatus();
  }

  initElements() {
    this.recordBtn = document.getElementById('recordBtn');
    this.bar = document.getElementById('bar');
    this.wave = document.getElementById('wave');

    this.pill = document.getElementById('pill');
    this.pillText = document.getElementById('pillText');
    this.gear = document.getElementById('gear');
    this.drawer = document.getElementById('drawer');
    this.closeDrawer = document.getElementById('closeDrawer');

    this.vadStatus = document.getElementById('vadStatus');

    this.statRtf = document.getElementById('statRtf');
    this.statAsrLat = document.getElementById('statAsrLat');
    this.statAsrTps = document.getElementById('statAsrTps');
    this.statLlmLat = document.getElementById('statLlmLat');
    this.statLlmTps = document.getElementById('statLlmTps');
    this.statFooter = document.getElementById('statFooter');

    this.page = document.getElementById('page');
    this.emptyState = document.getElementById('emptyState');
    this.polishedTextEl = document.getElementById('polishedText');
    this.countEl = document.getElementById('count');
    this.actionsEl = document.getElementById('actions');
    this.directTextInput = document.getElementById('directTextInput');
    this.directSendBtn = document.getElementById('directSendBtn');

    this.copyBtn = document.getElementById('copyBtn');
    this.clearBtn = document.getElementById('clearBtn');
    this.toastEl = document.getElementById('toast');

    this.testHi3Btn = document.getElementById('testHi3Btn');
    this.wavFileInput = document.getElementById('wavFileInput');
    this.dropZone = document.getElementById('dropZone');

    // Generate real-time waveform bars
    if (this.wave) {
      this.wave.innerHTML = '<i></i>'.repeat(36);
      this.waveBars = Array.from(this.wave.children);
    }

    // Tail element created; attached to DOM only when it has text
    this.inFlightTailEl = document.createElement('span');
    this.inFlightTailEl.className = 'in-flight-tail';

    this.rawLog = document.getElementById('rawLog');
  }

  initEvents() {
    this.recordBtn.addEventListener('click', () => this.toggleRecording());

    if (this.gear) this.gear.addEventListener('click', () => this.drawer.classList.add('open'));
    if (this.closeDrawer) this.closeDrawer.addEventListener('click', () => this.drawer.classList.remove('open'));

    // Spacebar shortcut to start/stop dictation (when not focused on editable text or buttons)
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Space') {
        if (e.repeat) return;
        const target = e.target;
        if (
          target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'BUTTON' ||
          target.isContentEditable ||
          target.closest('#polishedText') ||
          target.closest('button') ||
          this.isWavStreaming
        ) {
          return;
        }
        e.preventDefault();
        this.toggleRecording();
      }
    });

    this.copyBtn.addEventListener('click', () => this.copyToClipboard());
    this.clearBtn.addEventListener('click', () => this.clearAll());

    if (this.directSendBtn) {
      this.directSendBtn.addEventListener('click', () => this.sendDirectText());
    }
    if (this.directTextInput) {
      this.directTextInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          this.sendDirectText();
        }
      });
    }

    // User edit detection: inspect anchorNode of current selection in contenteditable
    this.polishedTextEl.addEventListener('input', () => {
      const sel = window.getSelection();
      if (sel && sel.anchorNode) {
        const node =
          sel.anchorNode.nodeType === Node.ELEMENT_NODE
            ? sel.anchorNode
            : sel.anchorNode.parentElement;
        const sentenceEl = node ? node.closest('.sentence-item') : null;
        if (sentenceEl && sentenceEl.dataset.id) {
          const sent = this.sentenceMap.get(sentenceEl.dataset.id);
          if (sent) {
            sent.userEdited = true;
          }
        }
      }
      this.updateWordCount();
      this.updateStatusPill();
    });

    if (this.testHi3Btn) {
      this.testHi3Btn.addEventListener('click', () => this.runHi3Test());
    }
    if (this.wavFileInput) {
      this.wavFileInput.addEventListener('change', (e) => this.handleFileUpload(e));
    }

    if (this.dropZone) {
      ['dragenter', 'dragover'].forEach((name) => {
        this.dropZone.addEventListener(name, (e) => {
          e.preventDefault();
          this.dropZone.classList.add('drag-over');
        });
      });
      ['dragleave', 'drop'].forEach((name) => {
        this.dropZone.addEventListener(name, (e) => {
          e.preventDefault();
          this.dropZone.classList.remove('drag-over');
        });
      });
      this.dropZone.addEventListener('drop', (e) => {
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
          this.handleFileUpload({ target: { files: [e.dataTransfer.files[0]] } });
        }
      });
    }
  }

  initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/dictate`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.updateButtonStates();
      this.updateStatusPill();
    };

    this.ws.onclose = () => {
      this.updateButtonStates();
      this.updateStatusPill();
      setTimeout(() => this.initWebSocket(), 2000);
    };

    this.ws.onerror = () => {
      this.updateButtonStates();
      this.updateStatusPill();
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleServerMessage(msg);
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };
  }

  handleServerMessage(msg) {
    if (msg.type === 'raw_tail') {
      this.updateRawTail(msg.tail, msg.asr_latency_ms, msg.rtf, msg.tps);
    } else if (msg.type === 'sentence_cleaning') {
      this.handleSentenceCleaning(msg);
    } else if (msg.type === 'sentence_polished') {
      this.handleSentencePolished(msg);
    } else if (msg.type === 'finalized' || msg.type === 'session_ended') {
      this.handleFinalized(msg);
    } else if (msg.type === 'error') {
      this.showToast(`Error: ${msg.message}`);
    }
  }

  updateButtonStates() {
    const busy = this.isRecording || this.isWavStreaming;
    if (this.directSendBtn) this.directSendBtn.disabled = busy;
    if (this.directTextInput) this.directTextInput.disabled = busy;
    if (this.recordBtn) this.recordBtn.disabled = this.isWavStreaming;
    if (this.testHi3Btn) this.testHi3Btn.disabled = busy;
    if (this.wavFileInput) this.wavFileInput.disabled = busy;
  }

  setPill(state, label) {
    if (this.pill) this.pill.dataset.s = state;
    if (this.pillText) this.pillText.textContent = label;
  }

  updateStatusPill() {
    if (!this.ws || this.ws.readyState === WebSocket.CONNECTING) {
      this.setPill('connecting', 'Connecting...');
      return;
    }
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.setPill('offline', 'Offline');
      return;
    }

    // Priority: 1. Listening, 2. Cleaning, 3. Done, 4. Ready
    if (this.isRecording) {
      this.setPill('listening', 'Listening');
      return;
    }

    let isCleaning = false;
    for (const sent of this.sentenceMap.values()) {
      if (sent.state === 'cleaning') {
        isCleaning = true;
        break;
      }
    }
    if (isCleaning) {
      this.setPill('cleaning', 'Cleaning');
      return;
    }

    const hasText = this.getFullTranscriptText().length > 0;
    if (hasText) {
      this.setPill('done', 'Done');
      return;
    }

    this.setPill('ready', 'Ready');
  }

  updateRawTail(tail, latencyMs, rtf, tps) {
    console.log(`[raw_tail @ ${performance.now().toFixed(0)}ms] latency: ${latencyMs}ms | text: "${tail}"`);

    if (this.rawLog) {
      const timeStr = new Date().toLocaleTimeString();
      const newEntry = `[${timeStr}] ${tail}`;
      const current = this.rawLog.textContent === '(No raw speech received yet)' ? [] : this.rawLog.textContent.split('\n');
      current.unshift(newEntry);
      if (current.length > 50) current.length = 50;
      this.rawLog.textContent = current.join('\n');
    }

    const trimmed = tail.trim();
    if (!trimmed) return;

    this.liveTail = (this.liveTail ? this.liveTail + ' ' : '') + trimmed;
    if (!this.inFlightTailEl.parentNode) {
      this.polishedTextEl.appendChild(this.inFlightTailEl);
    }
    this.inFlightTailEl.textContent = ' ' + this.liveTail;
    this.updateWordCount();

    if (latencyMs) {
      this.latestAsrMs = latencyMs;
      if (this.statAsrLat) this.statAsrLat.textContent = `${Math.round(latencyMs)} ms`;
    }
    if (rtf && this.statRtf) this.statRtf.textContent = `${rtf}x`;

    if (tps != null && this.statAsrTps) {
      this.statAsrTps.textContent = `${Math.round(tps)} tps`;
    } else if (latencyMs && latencyMs > 0 && this.statAsrTps) {
      const words = trimmed.split(/\s+/).length;
      const estTps = Math.round((words * 1.33) / (latencyMs / 1000));
      this.statAsrTps.textContent = `${estTps} tps`;
    }

    this.updateFooterStat();
  }

  removeSentenceFromTail(rawSentence) {
    if (!this.liveTail || !rawSentence) return;
    const rawWords = rawSentence.toLowerCase().match(/[a-z0-9']+/g) || [];
    if (rawWords.length === 0) return;

    const tailWords = this.liveTail.toLowerCase().match(/[a-z0-9']+/g) || [];
    const tailTokens = this.liveTail.trim().split(/\s+/);

    // Check if the beginning of the live tail matches rawWords
    let matchesPrefix = true;
    for (let i = 0; i < rawWords.length; i++) {
      if (i >= tailWords.length || tailWords[i] !== rawWords[i]) {
        matchesPrefix = false;
        break;
      }
    }

    if (matchesPrefix) {
      tailTokens.splice(0, rawWords.length);
      this.liveTail = tailTokens.join(' ').trim();
    } else {
      const rawTrimmed = rawSentence.trim();
      const idx = this.liveTail.indexOf(rawTrimmed);
      if (idx !== -1) {
        this.liveTail = (
          this.liveTail.slice(0, idx) +
          ' ' +
          this.liveTail.slice(idx + rawTrimmed.length)
        ).trim();
      } else if (rawWords.length >= tailWords.length) {
        // If raw_sentence has at least as many words as the tail, clear remaining tail
        this.liveTail = '';
      }
    }

    if (this.liveTail) {
      this.inFlightTailEl.textContent = ' ' + this.liveTail;
    } else {
      this.inFlightTailEl.textContent = '';
      if (this.inFlightTailEl.parentNode && this.sentenceMap.size === 0) {
        this.inFlightTailEl.remove();
      }
    }
    this.updateWordCount();
  }

  getOrCreateSentenceSpan(sentenceId, sentenceIndex, initialText, initialState) {
    if (this.sentenceMap.has(sentenceId)) {
      return this.sentenceMap.get(sentenceId);
    }

    const span = document.createElement('span');
    span.className = `sentence-item state-${initialState}`;
    span.dataset.id = sentenceId;
    span.dataset.index = sentenceIndex;

    this.displayCounter += 1;
    span.dataset.order = this.displayCounter;
    span.textContent = initialText.endsWith(' ') ? initialText : initialText + ' ';

    // Append in arrival order before in-flight tail so new sessions never precede old sentences
    if (this.inFlightTailEl.parentNode) {
      this.polishedTextEl.insertBefore(span, this.inFlightTailEl);
    } else {
      this.polishedTextEl.appendChild(span);
    }

    const entry = {
      id: sentenceId,
      index: sentenceIndex,
      displayOrder: this.displayCounter,
      raw: initialText,
      polished: null,
      state: initialState,
      element: span,
      timer: null,
      userEdited: false,
      generation: this.generation,
    };
    this.sentenceMap.set(sentenceId, entry);
    this.updateWordCount();
    return entry;
  }

  handleSentenceCleaning(msg) {
    // Ignore events originating before clearAll
    if (msg.timestamp && msg.timestamp * 1000 < this.lastClearTime) {
      return;
    }

    this.removeSentenceFromTail(msg.raw_sentence);

    const entry = this.getOrCreateSentenceSpan(
      msg.sentence_id,
      msg.sentence_index,
      msg.raw_sentence,
      'cleaning'
    );

    if (entry.generation !== this.generation) {
      return;
    }

    if (entry.state !== 'clean') {
      entry.state = 'cleaning';
      entry.element.classList.remove('state-raw', 'state-clean');
      entry.element.classList.add('state-cleaning');
    }
    this.updateStatusPill();

    // 3s timeout fallback: keep raw text, transition to solid clean style
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = setTimeout(() => {
      if (entry.state === 'cleaning' && entry.generation === this.generation) {
        entry.state = 'timeout';
        entry.element.classList.remove('state-cleaning');
        entry.element.classList.add('state-clean');
        this.updateStatusPill();
      }
    }, 3000);
  }

  handleSentencePolished(msg) {
    // Ignore events originating before clearAll
    if (msg.timestamp && msg.timestamp * 1000 < this.lastClearTime) {
      return;
    }

    const entry = this.getOrCreateSentenceSpan(
      msg.sentence_id,
      msg.sentence_index,
      msg.raw_sentence,
      'cleaning'
    );

    if (entry.generation !== this.generation) {
      return;
    }

    if (entry.timer) {
      clearTimeout(entry.timer);
      entry.timer = null;
    }

    // Edit protection relies strictly on userEdited flag
    if (entry.userEdited) {
      entry.state = 'clean';
      entry.element.classList.remove('state-cleaning');
      entry.element.classList.add('state-clean');
      this.updateStatusPill();
      return;
    }

    entry.polished = msg.polished_sentence;
    entry.state = 'clean';

    // Highlight modified tokens comparing original case and punctuation
    const diffFragment = this.buildDiffFragment(msg.raw_sentence, msg.polished_sentence);
    entry.element.innerHTML = '';
    entry.element.appendChild(diffFragment);

    entry.element.classList.remove('state-cleaning', 'state-raw');
    entry.element.classList.add('state-clean');

    // After 700ms, unwrap diff-word spans so container contains plain text
    setTimeout(() => {
      if (entry.generation === this.generation) {
        const diffSpans = entry.element.querySelectorAll('.diff-word');
        diffSpans.forEach((diffSpan) => {
          const textNode = document.createTextNode(diffSpan.textContent);
          diffSpan.replaceWith(textNode);
        });
        entry.element.normalize();
      }
    }, 700);

    if (msg.latency_ms) {
      this.latestLlmMs = msg.latency_ms;
      if (this.statLlmLat) this.statLlmLat.textContent = `${Math.round(msg.latency_ms)} ms`;
    }

    if (msg.tps != null && this.statLlmTps) {
      this.statLlmTps.textContent = `${Math.round(msg.tps)} tps`;
    } else if (msg.latency_ms && msg.latency_ms > 0 && this.statLlmTps) {
      const words = (msg.polished_sentence || '').trim().split(/\s+/).length;
      const estTps = Math.round((words * 1.33) / (msg.latency_ms / 1000));
      this.statLlmTps.textContent = `${estTps} tps`;
    }

    this.updateFooterStat();
    this.updateWordCount();
    this.updateStatusPill();
  }

  buildDiffFragment(raw, polished) {
    const frag = document.createDocumentFragment();
    const rawTokens = new Set(raw.trim().split(/\s+/));
    const polishedTokens = (polished.trim() + ' ').split(/(?<=\s+)/);

    for (const token of polishedTokens) {
      if (!token) continue;
      const cleanToken = token.trim();
      const isModified = cleanToken && !rawTokens.has(cleanToken);

      const span = document.createElement('span');
      span.className = isModified ? 'diff-word highlight' : 'diff-word';
      span.textContent = token;
      frag.appendChild(span);
    }
    return frag;
  }

  getFullTranscriptText() {
    const spans = Array.from(this.polishedTextEl.querySelectorAll('.sentence-item'));
    const mainText = spans.map((s) => s.textContent.trim()).filter(Boolean).join(' ');
    const tailText = this.liveTail.trim();
    return (mainText + (tailText ? ' ' + tailText : '')).trim();
  }

  updateFooterStat() {
    if (!this.statFooter) return;
    const speechStr = this.latestAsrMs != null ? `${Math.round(this.latestAsrMs)} ms` : '-- ms';
    const cleanupStr = this.latestLlmMs != null ? `${(this.latestLlmMs / 1000).toFixed(1)} s` : '-- s';
    this.statFooter.innerHTML = `Speech ${speechStr} &nbsp; Cleanup ${cleanupStr}`;
  }

  updateWordCount() {
    const text = this.getFullTranscriptText();
    const count = text ? text.split(/\s+/).length : 0;
    const hasText = text.length > 0;

    if (this.countEl) {
      this.countEl.textContent = hasText ? `${count} word${count === 1 ? '' : 's'}` : '';
    }
    if (this.actionsEl) {
      this.actionsEl.hidden = !hasText;
    }
    if (this.page) {
      this.page.classList.toggle('has-content', hasText);
    }
  }

  handleFinalized(msg) {
    if (this.isRecording) {
      this.stopRecording(false);
    }
    const reasonText = msg.reason === 'pause_timeout' ? ' (1s pause)' : '';
    this.showToast(`Dictation finished${reasonText}: ${msg.sentences_count} sentences polished!`);
    if (this.bar) this.bar.classList.remove('rec');
    this.updateStatusPill();
  }

  sendDirectText() {
    if (this.isRecording || this.isWavStreaming) return;
    const text = this.directTextInput.value.trim();
    if (!text) return;

    // Reset tail on direct text submission
    this.liveTail = '';
    this.inFlightTailEl.textContent = '';
    if (this.inFlightTailEl.parentNode && this.sentenceMap.size === 0) {
      this.inFlightTailEl.remove();
    }

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'text_input', text }));
      this.directTextInput.value = '';
      this.updateStatusPill();
    } else {
      this.showToast('WebSocket not connected.');
    }
  }

  async toggleRecording() {
    if (!this.isRecording) {
      await this.startRecording();
    } else {
      this.stopRecording();
    }
  }

  async startRecording() {
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });

      this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000,
      });

      if (this.audioContext.state === 'suspended') {
        await this.audioContext.resume();
      }
      console.log(`[AudioContext] state: ${this.audioContext.state}, sampleRate: ${this.audioContext.sampleRate}`);

      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 128;
      source.connect(this.analyser);

      // 4096 frames = ~256ms chunk buffer
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.isRecording) return;
        const inputData = e.inputBuffer.getChannelData(0);
        const resampled = this.resampleTo16k(inputData, this.audioContext.sampleRate);
        const pcm16 = this.floatTo16BitPCM(resampled);
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(pcm16.buffer);
        }
      };

      source.connect(this.processor);
      // Mute audio output to prevent microphone feedback through computer speakers
      const muteNode = this.audioContext.createGain();
      muteNode.gain.value = 0;
      this.processor.connect(muteNode);
      muteNode.connect(this.audioContext.destination);

      this.isRecording = true;
      this.updateButtonStates();
      if (this.bar) this.bar.classList.add('rec');
      this.updateStatusPill();
      this.drawWaveform();
      this.showToast('Microphone live — speak now!');
    } catch (err) {
      this.showToast('Microphone access denied or unavailable.');
      console.error(err);
    }
  }

  stopRecording(sendStop = true) {
    this.isRecording = false;
    this.updateButtonStates();
    if (this.bar) this.bar.classList.remove('rec');
    this.updateStatusPill();

    if (sendStop && this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'stop' }));
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    if (this.audioContext) {
      this.audioContext.close();
      this.audioContext = null;
    }

    cancelAnimationFrame(this.animationFrameId);
    this.resetWaveform();
  }

  resampleTo16k(audioData, origSampleRate) {
    if (!origSampleRate || origSampleRate === 16000) return audioData;
    const ratio = origSampleRate / 16000;
    const newLength = Math.round(audioData.length / ratio);
    const result = new Float32Array(newLength);
    for (let i = 0; i < newLength; i++) {
      const origIndex = i * ratio;
      const indexFloor = Math.floor(origIndex);
      const indexCeil = Math.min(audioData.length - 1, Math.ceil(origIndex));
      const fraction = origIndex - indexFloor;
      result[i] = audioData[indexFloor] * (1 - fraction) + audioData[indexCeil] * fraction;
    }
    return result;
  }

  floatTo16BitPCM(float32Array) {
    const buffer = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      buffer[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return buffer;
  }

  initCanvas() {
    this.resetWaveform();
  }

  resetWaveform() {
    if (this.waveBars) {
      for (const bar of this.waveBars) {
        bar.style.height = '15%';
      }
    }
    this.smoothedVolume = 0;
    this.vadIsSpeaking = false;
    if (this.vadStatus) {
      this.vadStatus.textContent = 'Standby';
    }
  }

  drawWaveform() {
    if (!this.isRecording || !this.analyser || !this.waveBars) return;

    this.animationFrameId = requestAnimationFrame(() => this.drawWaveform());

    const bufferLength = this.analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    this.analyser.getByteFrequencyData(dataArray);

    const numBars = this.waveBars.length;
    let sumRms = 0;

    for (let i = 0; i < numBars; i++) {
      const dataIdx = Math.floor(i * (bufferLength / numBars));
      const val = dataArray[dataIdx] / 255.0;
      sumRms += val;
      const heightPct = Math.max(15, Math.min(100, Math.round(val * 100)));
      this.waveBars[i].style.height = `${heightPct}%`;
    }

    const avgVolume = sumRms / numBars;
    this.smoothedVolume = 0.85 * this.smoothedVolume + 0.15 * avgVolume;
    if (this.vadStatus) {
      if (!this.vadIsSpeaking && this.smoothedVolume > 0.06) {
        this.vadIsSpeaking = true;
      } else if (this.vadIsSpeaking && this.smoothedVolume < 0.025) {
        this.vadIsSpeaking = false;
      }
      this.vadStatus.textContent = this.vadIsSpeaking ? 'Speaking' : 'Silence / Pause';
    }
  }

  async runHi3Test() {
    if (this.isRecording || this.isWavStreaming) return;
    this.showToast('Fetching and streaming hi3.wav...');
    try {
      const wavRes = await fetch('/api/test-audio').catch(() => null);
      if (!wavRes || !wavRes.ok) {
        this.showToast('Could not load test audio file (hi3.wav).');
        return;
      }
      const blob = await wavRes.blob();
      await this.streamWavBlob(blob);
    } catch (e) {
      this.showToast('Test error: ' + e.message);
    }
  }

  async handleFileUpload(e) {
    if (this.isRecording || this.isWavStreaming) return;
    const file = e.target.files[0];
    if (!file) return;
    try {
      await this.streamWavBlob(file);
    } catch (err) {
      this.showToast('File processing error: ' + err.message);
    }
  }

  async ensureWebSocketOpen() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return { ws: this.ws, isDedicated: false };
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/dictate`;
    const dedicatedWs = new WebSocket(wsUrl);

    await new Promise((resolve, reject) => {
      dedicatedWs.onopen = () => resolve();
      dedicatedWs.onerror = (err) => reject(err);
      setTimeout(() => reject(new Error('WebSocket connection timeout')), 4000);
    });

    dedicatedWs.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleServerMessage(msg);
        if (msg.type === 'finalized') {
          dedicatedWs.close();
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    return { ws: dedicatedWs, isDedicated: true };
  }

  async streamWavBlob(blob) {
    this.isWavStreaming = true;
    this.updateButtonStates();
    this.updateStatusPill();
    this.showToast('Decoding and streaming WAV audio...');

    try {
      const arrayBuffer = await blob.arrayBuffer();
      const tempAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const audioBuffer = await tempAudioCtx.decodeAudioData(arrayBuffer);
      await tempAudioCtx.close();

      // Resample to 16 kHz mono Float32
      const targetRate = 16000;
      const offlineCtx = new OfflineAudioContext(
        1,
        Math.ceil(audioBuffer.duration * targetRate),
        targetRate
      );
      const src = offlineCtx.createBufferSource();
      src.buffer = audioBuffer;
      src.connect(offlineCtx.destination);
      src.start(0);
      const rendered = await offlineCtx.startRendering();
      const floatData = rendered.getChannelData(0);
      const pcm16 = this.floatTo16BitPCM(floatData);

      const { ws } = await this.ensureWebSocketOpen();

      // Stream in 4096-sample slices (sending Int16Array view directly, ~256ms pace)
      const chunkSize = 4096;
      for (let offset = 0; offset < pcm16.length; offset += chunkSize) {
        const chunk = pcm16.subarray(offset, Math.min(offset + chunkSize, pcm16.length));
        ws.send(chunk);
        await new Promise((r) => setTimeout(r, 256));
      }

      // Final flush
      ws.send(JSON.stringify({ type: 'stop' }));
    } finally {
      this.isWavStreaming = false;
      this.updateButtonStates();
      this.updateStatusPill();
    }
  }

  async fetchSystemStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      const asrModel = document.getElementById('asrModelName');
      const llmModel = document.getElementById('llmModelName');
      if (asrModel && data.asr && data.asr.model) {
        asrModel.textContent = data.asr.model_name || data.asr.model;
      }
      if (llmModel && data.cleaner && data.cleaner.model) {
        llmModel.textContent = 'Gemini 2.5 Flash (Mumbai)';
      }
    } catch (e) {
      console.warn('Status check warning:', e);
    }
  }

  copyToClipboard() {
    const text = this.getFullTranscriptText();
    if (!text) {
      this.showToast('Nothing to copy!');
      return;
    }
    navigator.clipboard.writeText(text).then(() => {
      this.showToast('Copied clean transcript to clipboard!');
    });
  }

  clearAll() {
    this.generation += 1;
    this.lastClearTime = Date.now();

    for (const sent of this.sentenceMap.values()) {
      if (sent.timer) clearTimeout(sent.timer);
      if (sent.element) sent.element.remove();
    }
    this.sentenceMap.clear();
    this.liveTail = '';
    this.inFlightTailEl.textContent = '';
    if (this.inFlightTailEl.parentNode) this.inFlightTailEl.remove();
    this.updateWordCount();
    this.updateStatusPill();
    if (this.statAsrLat) this.statAsrLat.textContent = '-- ms';
    if (this.statAsrTps) this.statAsrTps.textContent = '-- tps';
    if (this.statLlmLat) this.statLlmLat.textContent = '-- ms';
    if (this.statLlmTps) this.statLlmTps.textContent = '-- tps';
    if (this.statRtf) this.statRtf.textContent = '--';
    this.latestAsrMs = null;
    this.latestLlmMs = null;
    if (this.rawLog) this.rawLog.textContent = '(No raw speech received yet)';
    this.updateFooterStat();
    this.showToast('Cleared transcript.');
  }

  showToast(message) {
    this.toastEl.textContent = message;
    this.toastEl.classList.add('show');
    clearTimeout(this.toastTimeout);
    this.toastTimeout = setTimeout(() => {
      this.toastEl.classList.remove('show');
    }, 3000);
  }

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }
}

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  window.app = new DictationApp();
});
