const API_BASE = '';

const processingState = document.getElementById('processing-state');
const resultsState = document.getElementById('results-state');
const errorState = document.getElementById('error-state');
const statusText = document.getElementById('status-text');
const statusBar = document.getElementById('status-bar');
const clipsGrid = document.getElementById('clips-grid');
const clipsCount = document.getElementById('clips-count');
const errorDetail = document.getElementById('error-detail');

const params = new URLSearchParams(window.location.search);
const jobId = params.get('job');

if (!jobId) {
  window.location.href = 'index.html';
}

const STATUS_MESSAGES = {
  queued: 'En cola...',
  compressing: 'Comprimiendo video a 720p...',
  uploading_to_gemini: 'Subiendo video a Gemini...',
  gemini_processing: 'Gemini está procesando el video...',
  gemini_analyzing: 'Gemini detectando momentos emocionantes...',
  cutting_clips: 'Cortando clips del video original...',
  done: 'Listo',
  error: 'Error',
};

const STATUS_PROGRESS = {
  queued: 5,
  compressing: 12,
  uploading_to_gemini: 28,
  gemini_processing: 50,
  gemini_analyzing: 75,
  cutting_clips: 90,
  done: 100,
};

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

let allClips = [];
let sortMode = 'time';

function setSort(mode) {
  sortMode = mode;
  document.getElementById('sort-time').classList.toggle('active', mode === 'time');
  document.getElementById('sort-score').classList.toggle('active', mode === 'score');
  renderClips();
}

function renderClips() {
  const sorted = [...allClips].sort((a, b) =>
    sortMode === 'score' ? (b.score || 5) - (a.score || 5) : a.start - b.start
  );

  clipsGrid.innerHTML = sorted.map((clip, i) => `
    <div class="clip-card">
      <video class="clip-video" controls preload="metadata">
        <source src="${API_BASE}/clips/${jobId}/${clip.filename}" type="video/mp4">
      </video>
      <div class="clip-info">
        <div class="clip-info-left">
          <div class="clip-label-row">
            <span class="clip-label">Clip ${i + 1}</span>
            <span class="clip-score">★ ${clip.score || 5}/10</span>
          </div>
          ${clip.description ? `
          <div class="clip-desc" id="desc-${i}">${clip.description}</div>
          <button class="btn-ver-mas" onclick="toggleDesc(${i}, this)">ver más</button>` : ''}
          <div class="clip-time">${formatTime(clip.start)} – ${formatTime(clip.end)}</div>
        </div>
        <a class="btn-download" href="${API_BASE}/clips/${jobId}/${clip.filename}" download="${clip.filename}">
          ↓ Descargar
        </a>
      </div>
    </div>
  `).join('');
}

function showResults(clips) {
  allClips = clips;
  processingState.classList.add('hidden');
  resultsState.classList.remove('hidden');
  clipsCount.textContent = `${clips.length} clip${clips.length !== 1 ? 's' : ''} encontrado${clips.length !== 1 ? 's' : ''}`;
  renderClips();
}

function showError(msg) {
  processingState.classList.add('hidden');
  errorState.classList.remove('hidden');
  errorDetail.textContent = msg;
}

async function pollStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/status/${jobId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const msg = STATUS_MESSAGES[data.status] || data.status;
    const pct = STATUS_PROGRESS[data.status] ?? 0;
    statusText.textContent = msg;
    statusBar.style.width = `${pct}%`;

    if (data.status === 'done') {
      showResults(data.clips);
    } else if (data.status === 'error') {
      showError(data.error || 'Error desconocido al procesar el video');
    } else {
      setTimeout(pollStatus, 2000);
    }
  } catch (err) {
    showError(`No se pudo conectar con el servidor: ${err.message}`);
  }
}

function toggleDesc(i, btn) {
  const desc = document.getElementById(`desc-${i}`);
  const open = desc.classList.toggle('visible');
  btn.textContent = open ? 'ver menos' : 'ver más';
}

pollStatus();
