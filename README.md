# GolaClips MVP

Sube un video largo de deportes. La IA detecta los momentos más emocionantes y genera clips cortos para descargar.

## Requisitos

- Python 3.11+
- **ffmpeg** instalado y disponible en PATH
  - Windows: https://ffmpeg.org/download.html → agregar `bin/` al PATH
  - Mac: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg`

## Instalación y arranque

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

El servidor queda en `http://localhost:8000`

### Frontend

Abrí `frontend/index.html` directamente en el navegador, o servilo con cualquier servidor estático:

```bash
cd frontend
python -m http.server 3000
# Abrí http://localhost:3000
```

## Cómo funciona la detección

Para el MVP se usa análisis de audio:
1. Se extrae el audio del video (mono, 16kHz)
2. Se calcula el RMS (volumen) por cada segundo
3. Se identifican los 5 picos de mayor volumen (gritos, música intensa, impactos)
4. Se genera un clip de 30 segundos centrado en cada pico

Funciona bien para deportes de acción donde hay reacciones del público o comentaristas.

## Estructura

```
GolaClips/
├── frontend/
│   ├── index.html    # Pantalla de subida
│   ├── clips.html    # Pantalla de resultados
│   ├── style.css     # Estilos compartidos
│   ├── upload.js     # Lógica de subida
│   └── clips.js      # Lógica de resultados + polling
└── backend/
    ├── main.py        # API FastAPI
    ├── processor.py   # Detección + corte de clips
    ├── requirements.txt
    ├── uploads/       # Videos temporales (se borran al procesar)
    └── clips/         # Clips generados
```
