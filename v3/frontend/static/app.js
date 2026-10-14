/**
 * Open Voice v3 — Frontend Client
 * Bi-directional Web Audio 16kHz streamer & Wispr Flow dual-buffer visualizer
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

    this.sentences = [];
    this.rawHistory = [];

    this.initElements();
    this.initEvents();
    this.initWebSocket();
    this.initCanvas();
    this.fetchSystemStatus();
  }

  initElements() {
    this.recordBtn = document.getElementById('recordBtn');
    this.recordBtnText = document.getElementById('recordBtnText');
    this.micIcon = document.getElementById('micIcon');
    this.stopSquare = document.getElementById('stopSquare');

    this.wsStatusPill = document.getElementById('wsStatusPill');
    this.wsDot = document.getElementById('wsDot');
    this.wsStatusText = document.getElementById('wsStatusText');

    this.vadBadge = document.getElementById('vadBadge');
    this.vadStatus = document.getElementById('vadStatus');

    this.canvas = document.getElementById('waveformCanvas');
    this.ctx = this.canvas.getContext('2d');
    this.visualizerOverlay = document.getElementById('visualizerOverlay');

    this.statRtf = document.getElementById('statRtf');
    this.statAsrLat = document.getElementById('statAsrLat');
    this.statLlmLat = document.getElementById('statLlmLat');

    this.rawTextEl = document.getElementById('rawText');
    this.polishedTextEl = document.getElementById('polishedText');
    this.polishedStatsEl = document.getElementById('polishedStats');

    this.sentenceFeedEl = document.getElementById('sentenceFeed');
    this.sentenceCountEl = document.getElementById('sentenceCount');

    this.copyBtn = document.getElementById('copyBtn');
    this.clearBtn = document.getElementById('clearBtn');
    this.toastEl = document.getElementById('toast');

    this.tabBtns = document.querySelectorAll('.tab-btn');
    this.tabContents = document.querySelectorAll('.tab-content');

    this.runSimBtn = document.getElementById('runSimBtn');
    this.testHi3Btn = document.getElementById('testHi3Btn');
    this.wavFileInput = document.getElementById('wavFileInput');
  }

  initEvents() {
    this.recordBtn.addEventListener('click', () => this.toggleRecording());

    // Spacebar shortcut to start/stop dictation (when not focused on editable text)
    window.addEventListener('keydown', (e) => {
      if (e.code === 'Space' && e.target !== this.polishedTextEl && e.target.tagName !== 'INPUT') {
        e.preventDefault();
        this.toggleRecording();
      }
    });

    this.copyBtn.addEventListener('click', () => this.copyToClipboard());
    this.clearBtn.addEventListener('click', () => this.clearAll());

    // Tab switching
    this.tabBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetId = btn.getAttribute('data-tab');
        this.tabBtns.forEach((b) => b.classList.remove('active'));
        this.tabContents.forEach((c) => c.classList.remove('active'));
        btn.classList.add('active');
        document.getElementById(targetId).classList.add('active');
      });
    });

    // Presets
    document.querySelectorAll('.preset-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.preset-btn').forEach((b) => (b.style.borderColor = ''));
        btn.style.borderColor = 'var(--accent-primary)';
        this.selectedPreset = btn.getAttribute('data-preset');
      });
    });

    this.runSimBtn.addEventListener('click', () => this.runSimulation());
    this.testHi3Btn.addEventListener('click', () => this.runHi3Test());
    this.wavFileInput.addEventListener('change', (e) => this.handleFileUpload(e));

    this.polishedTextEl.addEventListener('input', () => this.updateWordCount());
  }

  initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/dictate`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.wsDot.classList.add('connected');
      this.wsStatusText.textContent = 'Server Ready';
    };

    this.ws.onclose = () => {
      this.wsDot.classList.remove('connected', 'recording');
      this.wsStatusText.textContent = 'Disconnected';
      setTimeout(() => this.initWebSocket(), 2000);
    };

    this.ws.onerror = () => {
      this.wsStatusText.textContent = 'Connection Error';
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
      this.updateRawTail(msg.tail, msg.asr_latency_ms, msg.rtf);
    } else if (msg.type === 'sentence_polished') {
      this.addPolishedSentence(msg);
    } else if (msg.type === 'finalized') {
      this.handleFinalized(msg);
    } else if (msg.type === 'error') {
      this.showToast(`Error: ${msg.message}`);
    }
  }

  updateRawTail(tail, latencyMs, rtf) {
    if (this.rawTextEl.querySelector('.placeholder-text')) {
      this.rawTextEl.innerHTML = '';
    }
    this.rawHistory.push(tail);
    this.rawTextEl.textContent = this.rawHistory.slice(-4).join(' ');
    this.rawTextEl.scrollTop = this.rawTextEl.scrollHeight;

    if (latencyMs) this.statAsrLat.textContent = `${latencyMs} ms`;
    if (rtf) this.statRtf.textContent = `${rtf}x`;
  }

  addPolishedSentence(data) {
    this.sentences.push(data.polished_sentence);
    this.renderPolishedDocument();

    if (data.latency_ms) {
      this.statLlmLat.textContent = `${data.latency_ms} ms`;
    }

    // Add card to Inspector Feed
    this.addInspectorCard(data);
  }

  renderPolishedDocument() {
    this.polishedTextEl.textContent = this.sentences.join(' ');
    this.updateWordCount();
  }

  updateWordCount() {
    const text = this.polishedTextEl.textContent.trim();
    const count = text ? text.split(/\s+/).length : 0;
    this.polishedStatsEl.textContent = `${count} word${count === 1 ? '' : 's'}`;
  }

  addInspectorCard(data) {
    const emptyState = this.sentenceFeedEl.querySelector('.feed-empty-state');
    if (emptyState) emptyState.remove();

    const card = document.createElement('div');
    card.className = 'sentence-card';
    card.innerHTML = `
      <div class="card-meta">
        <span>Sentence #${data.sentence_index}</span>
        <span>⚡ ${data.latency_ms} ms</span>
      </div>
      <div class="card-raw">${this.escapeHtml(data.raw_sentence)}</div>
      <div class="card-polished">✨ ${this.escapeHtml(data.polished_sentence)}</div>
    `;

    this.sentenceFeedEl.prepend(card);
    this.sentenceCountEl.textContent = this.sentences.length;
  }

  handleFinalized(msg) {
    this.showToast(`Dictation finished: ${msg.sentences_count} sentences polished!`);
    this.recordBtn.classList.remove('recording');
    this.recordBtnText.textContent = 'Start Dictating';
    this.micIcon.classList.remove('hidden');
    this.stopSquare.classList.add('hidden');
    this.wsDot.classList.remove('recording');
    this.visualizerOverlay.style.display = 'block';
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

      const source = this.audioContext.createMediaStreamSource(this.mediaStream);
      this.analyser = this.audioContext.createAnalyser();
      this.analyser.fftSize = 256;
      source.connect(this.analyser);

      // 4096 frames = ~256ms chunk buffer
      this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.isRecording) return;
        const inputData = e.inputBuffer.getChannelData(0);
        const pcm16 = this.floatTo16BitPCM(inputData);
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          this.ws.send(pcm16.buffer);
        }
      };

      source.connect(this.processor);
      this.processor.connect(this.audioContext.destination);

      this.isRecording = true;
      this.recordBtn.classList.add('recording');
      this.recordBtnText.textContent = 'Stop Dictating';
      this.micIcon.classList.add('hidden');
      this.stopSquare.classList.remove('hidden');
      this.wsDot.classList.add('recording');
      this.visualizerOverlay.style.display = 'none';

      this.drawWaveform();
      this.showToast('Microphone live — speak now!');
    } catch (err) {
      this.showToast('Microphone access denied or unavailable.');
      console.error(err);
    }
  }

  stopRecording() {
    this.isRecording = false;

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'stop' }));
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
    }
    if (this.processor) this.processor.disconnect();
    if (this.audioContext) this.audioContext.close();

    cancelAnimationFrame(this.animationFrameId);
    this.clearCanvas();
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
    this.clearCanvas();
  }

  clearCanvas() {
    this.ctx.fillStyle = '#0f121d';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    this.ctx.strokeStyle = 'rgba(99, 102, 241, 0.2)';
    this.ctx.lineWidth = 1;
    this.ctx.beginPath();
    this.ctx.moveTo(0, this.canvas.height / 2);
    this.ctx.lineTo(this.canvas.width, this.canvas.height / 2);
    this.ctx.stroke();
  }

  drawWaveform() {
    if (!this.isRecording || !this.analyser) return;

    this.animationFrameId = requestAnimationFrame(() => this.drawWaveform());

    const bufferLength = this.analyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    this.analyser.getByteTimeDomainData(dataArray);

    this.ctx.fillStyle = 'rgba(15, 18, 29, 0.3)';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    this.ctx.lineWidth = 2.5;
    const gradient = this.ctx.createLinearGradient(0, 0, this.canvas.width, 0);
    gradient.addColorStop(0, '#6366f1');
    gradient.addColorStop(0.5, '#06b6d4');
    gradient.addColorStop(1, '#a855f7');
    this.ctx.strokeStyle = gradient;

    this.ctx.beginPath();
    const sliceWidth = this.canvas.width / bufferLength;
    let x = 0;
    let sumRms = 0;

    for (let i = 0; i < bufferLength; i++) {
      const v = dataArray[i] / 128.0;
      const y = (v * this.canvas.height) / 2;
      sumRms += Math.abs(v - 1.0);

      if (i === 0) {
        this.ctx.moveTo(x, y);
      } else {
        this.ctx.lineTo(x, y);
      }
      x += sliceWidth;
    }

    this.ctx.lineTo(this.canvas.width, this.canvas.height / 2);
    this.ctx.stroke();

    // VAD activity detection for badge
    const avgVolume = sumRms / bufferLength;
    if (avgVolume > 0.04) {
      this.vadBadge.classList.add('speaking');
      this.vadStatus.textContent = 'Speaking';
    } else {
      this.vadBadge.classList.remove('speaking');
      this.vadStatus.textContent = 'Pause / Silence';
    }
  }

  async runSimulation() {
    const preset = this.selectedPreset || 'backtracking';
    let chunks = [];
    let pauseIndices = [];

    if (preset === 'backtracking') {
      chunks = [
        'hello so um basically',
        'let us meet at two',
        'no wait actually three pm.',
      ];
      pauseIndices = [2];
    } else if (preset === 'fillers') {
      chunks = [
        'also uh please bring',
        'twenty five dollars for the tickets.',
      ];
      pauseIndices = [1];
    } else {
      chunks = [
        'hello um so basically let us meet at two no wait actually three pm.',
        'also please uh bring twenty five dollars for the tickets.',
      ];
      pauseIndices = [0, 1];
    }

    this.showToast('Running simulation with Gemini Asia Mumbai...');

    try {
      const res = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chunks, pause_after_indices: pauseIndices }),
      });
      const data = await res.json();

      this.rawTextEl.textContent = data.raw_text;
      this.polishedTextEl.textContent = data.polished_text;
      this.sentences = [data.polished_text];
      this.updateWordCount();

      // Render cards
      this.sentenceFeedEl.innerHTML = '';
      data.sentence_events.forEach((evt) => this.addInspectorCard(evt));
      this.showToast('Simulation complete!');
    } catch (e) {
      this.showToast('Simulation failed: ' + e.message);
    }
  }

  async runHi3Test() {
    this.showToast('Running Nemotron 3.5 Vulkan on hi3.wav...');
    try {
      // Fetch hi3.wav directly from static or backend
      const wavRes = await fetch('/static/../static/../../hi3.wav').catch(() => null);
      if (!wavRes || !wavRes.ok) {
        // Run simulator as fallback test
        this.runSimulation();
        return;
      }
      const blob = await wavRes.blob();
      const formData = new FormData();
      formData.append('file', blob, 'hi3.wav');

      const res = await fetch('/api/transcribe-file', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      this.rawTextEl.textContent = data.raw_text;
      this.polishedTextEl.textContent = data.polished_text;
      this.statAsrLat.textContent = `${Math.round(data.asr_latency_ms)} ms`;
      this.statRtf.textContent = `${data.rtf.toFixed(2)}x`;
      this.showToast('hi3.wav transcription & polish complete!');
    } catch (e) {
      this.showToast('Test error: ' + e.message);
    }
  }

  async handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    this.showToast(`Processing ${file.name}...`);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/transcribe-file', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      this.rawTextEl.textContent = data.raw_text;
      this.polishedTextEl.textContent = data.polished_text;
      this.statAsrLat.textContent = `${Math.round(data.asr_latency_ms)} ms`;
      this.statRtf.textContent = `${data.rtf.toFixed(2)}x`;
      this.showToast('Transcription & polish complete!');
    } catch (err) {
      this.showToast('File processing error: ' + err.message);
    }
  }

  async fetchSystemStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      if (data.asr.available) {
        document.getElementById('asrStatusPill').style.borderColor = 'rgba(16, 185, 129, 0.4)';
      }
      if (data.cleaner.key_file_exists) {
        document.getElementById('llmStatusPill').style.borderColor = 'rgba(6, 182, 212, 0.4)';
      }
    } catch (e) {
      console.warn('Status check warning:', e);
    }
  }

  copyToClipboard() {
    const text = this.polishedTextEl.textContent.trim();
    if (!text) {
      this.showToast('Nothing to copy!');
      return;
    }
    navigator.clipboard.writeText(text).then(() => {
      this.showToast('Copied clean transcript to clipboard!');
    });
  }

  clearAll() {
    this.sentences = [];
    this.rawHistory = [];
    this.polishedTextEl.textContent = '';
    this.rawTextEl.innerHTML = '<span class="placeholder-text">Awaiting speech input...</span>';
    this.sentenceFeedEl.innerHTML = '<div class="feed-empty-state"><p>Sentences will be analyzed here in real-time as you pause or speak punctuation.</p></div>';
    this.sentenceCountEl.textContent = '0';
    this.updateWordCount();
    this.statAsrLat.textContent = '-- ms';
    this.statLlmLat.textContent = '-- ms';
    this.statRtf.textContent = '--';
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
