const API_BASE = '';

const uploadArea = document.getElementById('upload-area');
const fileInput = document.getElementById('file-input');
const optionsArea = document.getElementById('options-area');
const progressArea = document.getElementById('progress-area');
const progressBar = document.getElementById('progress-bar');
const progressText = document.getElementById('progress-text');
const fileName = document.getElementById('file-name');
const fileSize = document.getElementById('file-size');
const errorMsg = document.getElementById('error-msg');

const DURATION_MAP = {
  short:  { min: 10, max: 30 },
  medium: { min: 30, max: 60 },
  long:   { min: 60, max: 120 },
};

let selectedFile = null;

// Drag & drop
uploadArea.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadArea.classList.add('drag-over');
});

uploadArea.addEventListener('dragleave', () => {
  uploadArea.classList.remove('drag-over');
});

uploadArea.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadArea.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});

document.getElementById('btn-elegir').addEventListener('click', (e) => {
  e.stopPropagation();
  fileInput.click();
});

uploadArea.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

document.getElementById('btn-analizar').addEventListener('click', () => {
  if (selectedFile) startUpload(selectedFile);
});

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove('hidden');
  progressArea.classList.add('hidden');
  optionsArea.classList.remove('hidden');
  uploadArea.classList.add('hidden');
}

const VIDEO_EXTENSIONS = ['mp4', 'mov', 'avi', 'mkv', 'webm', 'wmv', 'flv', 'ts', 'mts'];

function isVideo(file) {
  if (file.type.startsWith('video/')) return true;
  const ext = file.name.split('.').pop().toLowerCase();
  return VIDEO_EXTENSIONS.includes(ext);
}

function handleFile(file) {
  if (!isVideo(file)) {
    showError('El archivo debe ser un video (MP4, MOV, AVI, MKV...)');
    return;
  }
  selectedFile = file;
  errorMsg.classList.add('hidden');
  uploadArea.classList.add('hidden');
  optionsArea.classList.remove('hidden');

  fileName.textContent = file.name;
  fileSize.textContent = formatBytes(file.size);
}

function startUpload(file) {
  const durationVal = document.querySelector('input[name="duration"]:checked').value;
  const { min, max } = DURATION_MAP[durationVal];
  const numClips = document.getElementById('num-clips').value;
  const customPrompt = document.getElementById('custom-prompt').value;

  optionsArea.classList.add('hidden');
  progressArea.classList.remove('hidden');

  const formData = new FormData();
  formData.append('file', file);
  formData.append('duration_min', min);
  formData.append('duration_max', max);
  formData.append('num_clips', numClips);
  formData.append('custom_prompt', customPrompt);

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
      const data = JSON.parse(xhr.responseText);
      progressBar.style.width = '100%';
      progressText.textContent = 'Listo. Redirigiendo...';
      setTimeout(() => {
        window.location.href = `clips.html?job=${data.job_id}`;
      }, 600);
    } else {
      let msg = 'Error al subir el video';
      try { msg = JSON.parse(xhr.responseText).detail || msg; } catch (_) {}
      showError(msg);
    }
  });

  xhr.addEventListener('error', () => {
    showError('No se pudo conectar con el servidor. ¿Está corriendo el backend?');
  });

  xhr.addEventListener('abort', () => {
    showError('La subida fue cancelada. Intentá de nuevo.');
  });

  xhr.open('POST', `${API_BASE}/api/upload`);
  xhr.send(formData);
}
