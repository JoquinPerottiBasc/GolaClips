const API_BASE = '';

const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');
const optionsArea = document.getElementById('options-area');
const fileListSection = document.getElementById('file-list-section');
const fileListEl = document.getElementById('file-list');
const jobsSection = document.getElementById('jobs-section');
const errorMsg = document.getElementById('error-msg');
const btnAnalizar = document.getElementById('btn-analizar');
const historySection = document.getElementById('history-section');
const historyList = document.getElementById('history-list');

const DURATION_MAP = {
  short:  { min: 10, max: 30 },
  medium: { min: 30, max: 60 },
  long:   { min: 60, max: 120 },
};

const STATUS_MESSAGES = {
  queued:             'En cola...',
  compressing:        'Comprimiendo video...',
  uploading_to_gemini:'Subiendo a Gemini...',
  gemini_processing:  'Gemini procesando...',
  gemini_analyzing:   'Detectando momentos...',
  cutting_clips:      'Cortando clips...',
  done:               'Listo',
  error:              'Error',
};

const STATUS_PROGRESS = {
  queued:              5,
  compressing:        12,
  uploading_to_gemini:28,
  gemini_processing:  50,
  gemini_analyzing:   72,
  cutting_clips:      90,
  done:              100,
};

const VIDEO_EXTENSIONS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'wmv', 'flv', 'ts', 'mts'];

let selectedFiles = [];
let _currentUser = null;

// Version counter per clip for cache-busting after extend
const _clipVersions = {};
function getClipVersion(jobId, filename) {
  return _clipVersions[`${jobId}/${filename}`] || 0;
}
function bumpClipVersion(jobId, filename) {
  const key = `${jobId}/${filename}`;
  _clipVersions[key] = (_clipVersions[key] || 0) + 1;
}

// --- Auth ---
async function getToken() {
  const user = firebase.auth().currentUser;
  if (!user) return null;
  return user.getIdToken();
}

function signOut() {
  firebase.auth().signOut().then(() => {
    window.location.href = 'login.html';
  });
}

// Auth state observer — redirect to login if not signed in
firebase.auth().onAuthStateChanged(async (user) => {
  if (!user) {
    window.location.href = 'login.html';
    return;
  }
  _currentUser = user;

  // Show user info in header
  const headerUser = document.getElementById('header-user');
  const userAvatar = document.getElementById('user-avatar');
  const userName = document.getElementById('user-name');
  if (headerUser) {
    headerUser.classList.remove('hidden');
    if (user.photoURL) userAvatar.src = user.photoURL;
    userName.textContent = user.displayName || user.email;
  }

  // Load history
  loadHistory();
});

// --- History ---
async function loadHistory() {
  try {
    const token = await getToken();
    const res = await fetch(`${API_BASE}/api/me/history`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const jobs = await res.json();

    if (!jobs.length) return;

    historySection.classList.remove('hidden');
    historyList.innerHTML = '';

    jobs.forEach(job => renderHistoryJob(job));
  } catch (e) {
    console.warn('Could not load history:', e);
  }
}

function renderHistoryJob(job) {
  const date = new Date(job.created_at + 'Z').toLocaleDateString('es-AR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  });
  const expires = new Date(job.expires_at + 'Z');
  const expired = expires < new Date();

  const card = document.createElement('div');
  card.className = 'history-card';
  card.innerHTML = `
    <div class="history-card-header">
      <div class="history-card-meta">
        <span class="history-filename">${job.original_filename}</span>
        <span class="history-date">${date}</span>
      </div>
      <div class="history-card-right">
        ${expired
          ? '<span class="history-badge expired">Expirado</span>'
          : `<span class="history-badge">${job.clips.length} clip${job.clips.length !== 1 ? 's' : ''}</span>`
        }
        ${!expired ? `<button class="history-toggle-btn" onclick="toggleHistoryClips(this)">Ver clips</button>` : ''}
      </div>
    </div>
    ${!expired && job.clips.length ? `
      <div class="history-clips-grid hidden">
        ${job.clips.map((clip, i) => {
          const srcUrl = clip.url || `${API_BASE}/clips/${job.job_id}/${clip.filename}`;
          return `
          <div class="clip-card">
            <video class="clip-video" controls preload="none" ${clip.url ? `poster="${clip.url.replace('.mp4', '.jpg')}"` : ''}>
              <source src="${srcUrl}" type="video/mp4">
            </video>
            <div class="clip-info">
              <div class="clip-info-left">
                <div class="clip-label-row">
                  <span class="clip-label">Clip ${i + 1}</span>
                  <span class="clip-score">★ ${clip.score || 5}/10</span>
                </div>
                ${clip.description ? `<div class="clip-desc visible">${clip.description}</div>` : ''}
                <div class="clip-time">${formatTime(clip.start)} – ${formatTime(clip.end)}</div>
              </div>
              <a class="btn-download" href="${srcUrl}" download="${clip.filename}">↓ Descargar</a>
            </div>
          </div>
        `}).join('')}
      </div>
    ` : ''}
  `;
  historyList.appendChild(card);
}

function toggleHistoryClips(btn) {
  const grid = btn.closest('.history-card').querySelector('.history-clips-grid');
  const open = grid.classList.toggle('hidden');
  btn.textContent = open ? 'Ver clips' : 'Ocultar';
}

// --- Drag & drop ---
uploadArea.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadArea.classList.add('drag-over');
});
uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('drag-over'));
uploadArea.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadArea.classList.remove('drag-over');
  addFiles(Array.from(e.dataTransfer.files));
});
document.getElementById('btn-elegir').addEventListener('click', (e) => {
  e.stopPropagation();
  fileInput.click();
});
uploadArea.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
  addFiles(Array.from(fileInput.files));
  fileInput.value = '';
});
btnAnalizar.addEventListener('click', submitAll);

// --- Helpers ---
function isVideo(file) {
  if (file.type.startsWith('video/')) return true;
  return VIDEO_EXTENSIONS.includes(file.name.split('.').pop().toLowerCase());
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove('hidden');
  setTimeout(() => errorMsg.classList.add('hidden'), 5000);
}

// --- File selection ---
function addFiles(files) {
  const valid = files.filter(isVideo);
  if (valid.length === 0) {
    showError('Seleccioná al menos un video (MP4, MOV, AVI, MKV...)');
    return;
  }
  selectedFiles = [...selectedFiles, ...valid];
  renderFileList();
  uploadArea.classList.add('hidden');
  fileListSection.classList.remove('hidden');
  optionsArea.classList.remove('hidden');
}

function removeFile(index) {
  selectedFiles.splice(index, 1);
  if (selectedFiles.length === 0) {
    fileListSection.classList.add('hidden');
    optionsArea.classList.add('hidden');
    uploadArea.classList.remove('hidden');
  } else {
    renderFileList();
  }
}

function renderFileList() {
  fileListEl.innerHTML = selectedFiles.map((f, i) => `
    <div class="file-item">
      <span class="file-item-name">${f.name}</span>
      <span class="file-item-size">${formatBytes(f.size)}</span>
      <button class="file-item-remove" onclick="removeFile(${i})">✕</button>
    </div>
  `).join('');
  const n = selectedFiles.length;
  btnAnalizar.textContent = `Analizar ${n} video${n > 1 ? 's' : ''} ⚡`;
}

// --- Submit ---
async function submitAll() {
  if (selectedFiles.length === 0) return;

  const durationVal = document.querySelector('input[name="duration"]:checked').value;
  const { min, max } = DURATION_MAP[durationVal];
  const numClips = document.getElementById('num-clips').value;
  const customPrompt = document.getElementById('custom-prompt').value;

  fileListSection.classList.add('hidden');
  optionsArea.classList.add('hidden');
  jobsSection.classList.remove('hidden');

  const filesToSubmit = [...selectedFiles];
  selectedFiles = [];

  // Upload all files in parallel — backend queues processing serially
  await Promise.all(filesToSubmit.map(f => submitFile(f, min, max, numClips, customPrompt)));
}

async function submitFile(file, durationMin, durationMax, numClips, customPrompt) {
  // Get fresh auth token before starting upload
  const token = await getToken();
  if (!token) {
    window.location.href = 'login.html';
    return;
  }

  // Create job card
  const card = document.createElement('div');
  card.className = 'job-card';
  card.innerHTML = `
    <div class="job-header">
      <span class="job-filename">${file.name}</span>
      <span class="job-badge">Subiendo...</span>
    </div>
    <div class="job-progress">
      <div class="progress-bar-container">
        <div class="progress-bar" style="width: 0%"></div>
      </div>
      <span class="progress-text">Subiendo... 0%</span>
    </div>
    <div class="job-clips hidden"></div>
  `;
  jobsSection.appendChild(card);

  const progressBar = card.querySelector('.progress-bar');
  const progressText = card.querySelector('.progress-text');
  const jobBadge = card.querySelector('.job-badge');
  const jobClips = card.querySelector('.job-clips');

  // Upload via XHR to track progress
  const formData = new FormData();
  formData.append('file', file);
  formData.append('duration_min', durationMin);
  formData.append('duration_max', durationMax);
  formData.append('num_clips', numClips);
  formData.append('custom_prompt', customPrompt);

  const jobId = await new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        progressBar.style.width = `${pct}%`;
        progressText.textContent = `Subiendo... ${pct}%`;
      }
    });
    xhr.addEventListener('load', () => {
      if (xhr.status === 200) {
        resolve(JSON.parse(xhr.responseText).job_id);
      } else {
        let msg = 'Error al subir';
        try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (_) {}
        jobBadge.textContent = 'Error';
        jobBadge.className = 'job-badge error';
        progressText.textContent = msg;
        resolve(null);
      }
    });
    xhr.addEventListener('error', () => {
      progressText.textContent = 'Error de conexión';
      resolve(null);
    });
    xhr.open('POST', `${API_BASE}/api/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.send(formData);
  });

  if (!jobId) return;

  progressBar.style.width = '5%';
  pollJob(jobId, progressBar, progressText, jobBadge, jobClips);
}

// --- Polling ---
async function pollJob(jobId, progressBar, progressText, jobBadge, jobClips) {
  async function check() {
    try {
      const res = await fetch(`${API_BASE}/api/status/${jobId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const msg = STATUS_MESSAGES[data.status] || data.status;
      const pct = STATUS_PROGRESS[data.status] ?? 0;
      progressText.textContent = msg;
      progressBar.style.width = `${pct}%`;
      jobBadge.textContent = msg;

      if (data.status === 'done') {
        jobBadge.className = 'job-badge done';
        const n = data.clips.length;
        progressText.textContent = `${n} clip${n !== 1 ? 's' : ''} encontrado${n !== 1 ? 's' : ''}`;
        renderInlineClips(jobId, data.clips, jobClips);
        // Refresh history to include this new job
        loadHistory();
      } else if (data.status === 'error') {
        jobBadge.className = 'job-badge error';
        progressText.textContent = data.error || 'Error desconocido';
        progressBar.style.background = 'var(--error)';
      } else {
        setTimeout(check, 2000);
      }
    } catch (_) {
      setTimeout(check, 3000);
    }
  }
  setTimeout(check, 1000);
}

// --- Inline clip rendering ---
function renderInlineClips(jobId, clips, container) {
  container.classList.remove('hidden');
  container.innerHTML = `
    <div class="inline-clips-header">
      <div class="sort-toggle">
        <button class="sort-btn active" id="sort-time-${jobId}" onclick="setInlineSort('${jobId}', 'time', this)">Por tiempo</button>
        <button class="sort-btn" id="sort-score-${jobId}" onclick="setInlineSort('${jobId}', 'score', this)">Por puntuación</button>
      </div>
    </div>
    <div class="clips-grid" id="clips-grid-${jobId}"></div>
  `;
  window[`_clips_${jobId}`] = clips;
  window[`_sort_${jobId}`] = 'time';
  renderInlineGrid(jobId);
}

function setInlineSort(jobId, mode, btn) {
  window[`_sort_${jobId}`] = mode;
  document.getElementById(`sort-time-${jobId}`).classList.toggle('active', mode === 'time');
  document.getElementById(`sort-score-${jobId}`).classList.toggle('active', mode === 'score');
  renderInlineGrid(jobId);
}

function renderInlineGrid(jobId) {
  const clips = window[`_clips_${jobId}`];
  const mode = window[`_sort_${jobId}`];
  const sorted = [...clips].sort((a, b) =>
    mode === 'score' ? (b.score || 5) - (a.score || 5) : a.start - b.start
  );
  document.getElementById(`clips-grid-${jobId}`).innerHTML = sorted.map((clip, i) => {
    const srcUrl = clip.url || `${API_BASE}/clips/${jobId}/${clip.filename}?v=${getClipVersion(jobId, clip.filename)}`;
    return `
      <div class="clip-card">
        <video class="clip-video" controls preload="metadata" ${clip.thumb_url ? `poster="${clip.thumb_url}"` : ''}>
          <source src="${srcUrl}" type="video/mp4">
        </video>
        <div class="clip-info">
          <div class="clip-info-left">
            <div class="clip-label-row">
              <span class="clip-label">Clip ${i + 1}</span>
              <span class="clip-score">★ ${clip.score || 5}/10</span>
            </div>
            ${clip.description ? `
            <div class="clip-desc" id="idesc-${jobId}-${i}">${clip.description}</div>
            <button class="btn-ver-mas" onclick="toggleInlineDesc('${jobId}', ${i}, this)">ver más</button>` : ''}
            <div class="clip-time">${formatTime(clip.start)} – ${formatTime(clip.end)}</div>
            <div class="extend-controls">
              <button class="btn-extend" onclick="extendClip(event,'${jobId}','${clip.filename}',5,0)">← +5s</button>
              <button class="btn-extend btn-extend-end" onclick="extendClip(event,'${jobId}','${clip.filename}',0,5)">+5s →</button>
            </div>
          </div>
          <a class="btn-download" href="${srcUrl}" download="${clip.filename}">↓ Descargar</a>
        </div>
      </div>
    `;
  }).join('');
}

function toggleInlineDesc(jobId, i, btn) {
  const desc = document.getElementById(`idesc-${jobId}-${i}`);
  const open = desc.classList.toggle('visible');
  btn.textContent = open ? 'ver menos' : 'ver más';
}

// --- Extend clip ---
async function extendClip(event, jobId, filename, addStart, addEnd) {
  const btn = event.currentTarget;
  const card = btn.closest('.clip-card');

  const extendBtns = card.querySelectorAll('.btn-extend');
  extendBtns.forEach(b => b.disabled = true);
  card.classList.add('clip-loading');

  const overlay = document.createElement('div');
  overlay.className = 'clip-extend-overlay';
  overlay.innerHTML = '<div class="clip-extend-spinner"></div>';
  card.appendChild(overlay);

  try {
    const res = await fetch(`${API_BASE}/api/clips/${jobId}/${filename}/extend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add_start: addStart, add_end: addEnd }),
    });
    if (!res.ok) throw new Error('Error al extender');
    const data = await res.json();

    const clips = window[`_clips_${jobId}`];
    const clip = clips.find(c => c.filename === filename);
    if (clip) {
      clip.start = data.start;
      clip.end = data.end;
    }

    bumpClipVersion(jobId, filename);
    const newSrc = `${API_BASE}/clips/${jobId}/${filename}?v=${getClipVersion(jobId, filename)}`;

    const sourceEl = card.querySelector('.clip-video source');
    const videoEl  = card.querySelector('.clip-video');
    const timeEl   = card.querySelector('.clip-time');
    const dlLink   = card.querySelector('.btn-download');

    if (sourceEl) sourceEl.src = newSrc;
    if (videoEl)  videoEl.load();
    if (timeEl && clip) timeEl.textContent = `${formatTime(clip.start)} – ${formatTime(clip.end)}`;
    if (dlLink)   dlLink.href = newSrc;

  } catch (err) {
    console.error('extend error:', err);
  } finally {
    card.classList.remove('clip-loading');
    overlay.remove();
    extendBtns.forEach(b => b.disabled = false);
  }
}
