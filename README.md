# VideoIndex IA

Plataforma **local-first** de inteligencia sobre conocimiento audiovisual: convierte
colecciones de videos en conocimiento navegable, verificable y reutilizable.
Transcribe, indexa, busca por texto y significado, responde con evidencia y
**abre el video en el instante exacto** donde se dijo cada cosa.

> VideoIndex IA no es un transcriptor de videos. Es una plataforma de
> inteligencia sobre conocimiento audiovisual. (00_Product_Vision)

La especificación completa (PRD, SAD, ADRs) vive en
`I:\Mi unidad\00_Programas y macros\VideoIndex IA\`.

## Qué hace el MVP

- **Ingesta** de carpetas locales de video (mp4/mkv/avi/webm/mov/wmv/flv/mpg/mpeg/ts/3gp)
  y audio puro (mp3/wav/m4a/flac/ogg/opus/aac/wma), idempotente por checksum
  sha256: re-escanear no duplica, mover archivos no rompe.
- **Ingesta desde URL** (YouTube y los ~1800 sitios de yt-dlp): baja solo la
  pista de audio y registra el título, canal y fecha de publicación reales —
  la ficha de procedencia que hace falta para citar la fuente. Misma
  identidad por checksum: bajar dos veces no duplica.
- **Transcripción** 100 % local con faster-whisper (CPU, int8, $0) con
  timestamps absolutos (ADR-002) y confianza por segmento. El modelo se
  elige desde la GUI (`small` para buscar, `large-v3-turbo` para publicar).
- **Separación de voces** ($0, local): quién dice qué y cuándo, con
  embeddings ECAPA y agrupamiento. Las etiquetas anónimas se renombran a
  mano ("SPEAKER_00" → "Marta Ríos") y ese nombre se usa en todo lo que se
  exporte. Un cambio de hablante corta el chunk, para no atribuir mal una cita.
- **Identificación nominal**: cruza los turnos de voz con los **rótulos
  sobreimpresos** que lee del video (OCR con consenso temporal) y con las
  presentaciones dichas en voz alta, para pasar de "SPEAKER_01" a
  "CARLA ULLOA — HISTORIADORA", con nivel de confianza y la evidencia que lo
  respalda. Nunca inventa: sin evidencia deja identificación funcional.
- **Exportación editorial** de la transcripción a Word / Markdown / SRT, con
  ficha de procedencia y la advertencia de que es transcripción automática
  sin cotejar. Y un paquete completo de ocho documentos (literal, limpia,
  txt, srt, participantes.xlsx, citas.xlsx, incertidumbres, proceso técnico).
- **Reanudable**: la transcripción se guarda cada 25 segmentos. Si se cierra
  el portátil a mitad de una hora de audio, al volver continúa donde quedó.
- **Segmentación semántica** local: pausas largas + caída de similitud coseno
  entre ventanas → Semantic Chunks (ADR-001), con `discourse_type` heurístico.
- **Entidades** (spaCy es) + **grafo simple** de co-ocurrencia (ADR-005).
- **Búsqueda híbrida**: FTS5 (BM25, insensible a tildes) + FAISS (MiniLM
  multilingüe 384d) + entidades + confianza, fusionados con los pesos de la
  spec (0.45/0.30/0.15/0.10).
- **RAG con evidencia obligatoria** (ADR-003): el LLM solo recibe lo que el
  Search Engine recuperó; sin evidencia no se llama a la IA. Multiproveedor
  (Gemini default / OpenAI / Claude / Ollama $0) con el estándar de costo IA:
  estimar → confirmar → costo real desde usage.
- **GUI PySide6**: biblioteca con ETA antes de procesar y reanudación tras
  cierre, búsqueda con tarjetas-evidencia, pregunta RAG con citas [n]
  clicables, reproductor integrado que salta al timestamp.

## Uso

```powershell
# primera vez
powershell -File scripts\setup_venv.ps1

# GUI
.venv\Scripts\python.exe -m videoindex.app

# CLI (mismo motor)
.venv\Scripts\python.exe -m videoindex.cli ingest "D:\mis videos" --curso "Seminario X"
.venv\Scripts\python.exe -m videoindex.cli search "aprendizaje supervisado"
.venv\Scripts\python.exe -m videoindex.cli status
```

API keys (solo para la pestaña Preguntar; indexar nunca las necesita):
variables de entorno `GEMINI_API_KEY`, `OPENAI_API_KEY` o `ANTHROPIC_API_KEY`.

## Desarrollo

```powershell
.venv\Scripts\python.exe -m pytest        # suite rápida (sin modelos)
.venv\Scripts\python.exe -m pytest -m slow  # con whisper real
.venv\Scripts\ruff.exe check src tests
powershell -File scripts\build_exe.ps1    # .exe (en C:, --clean)
```

Los datos del usuario (SQLite, índices FAISS) viven en `data\` (gitignored);
redirigibles con la variable `VIDEOINDEX_DATA`.

## Decisiones técnicas que no son obvias

- **Python 3.12 obligatorio** en el venv: ctranslate2 (faster-whisper) no
  soporta 3.14.
- **La diarización usa ECAPA (speechbrain), no pyannote**, que es el estándar
  del campo: el pipeline `pyannote/speaker-diarization-3.1` depende de
  `pyannote/segmentation-3.0`, un modelo *gated* que responde 401 sin token
  de Hugging Face y sin aceptar sus condiciones en la web. `speechbrain/
  spkrec-ecapa-voxceleb` es abierto y no pide cuenta. El precio: **no se
  detecta habla superpuesta** — cuando dos personas hablan a la vez, ese
  tramo se le atribuye a una sola.
- **El umbral automático de voces (0.65) NO está calibrado** con grabaciones
  reales: sale de la convención de speechbrain (similitud ≥ 0.25 = misma
  persona). Si sabes cuántas personas hablan, fijar el número en
  Configuración es bastante más fiable que el umbral.
- **No se valida la diarización con audio sintético**: los embeddings de
  tonos artificiales caen todos juntos en una zona del espacio donde las
  distancias no se parecen a las de voz real (medido: <0.28 entre dos
  "voces" sintéticas, frente a >0.6 entre dos personas). Los tests slow
  fijan `n_hablantes` por eso.
- **La descarga por URL no usa ffmpeg**: baja `bestaudio[ext=m4a]` sin
  postproceso, así que no hace falta tener ffmpeg instalado (PyAV decodifica).
- **`VideoIndexIA.spec` está versionado a propósito** pese al `*.spec` del
  `.gitignore`: está editado a mano y sin él no se reconstruye el `.exe`.
- **`QT_MEDIA_BACKEND=windows`** (lo fija `app.py`): el backend ffmpeg de Qt
  crashea al renderizar video en esta máquina; el nativo WMF funciona. El seek
  se hace 300 ms después de `play()` o WMF lo pisa.
- **FAISS serializado vía Python** (`serialize_index`/`deserialize_index`):
  `write_index` de C++ falla con rutas Windows con tildes.
- **Embeddings versionados** (tabla `embedding_versions`): migrar de modelo es
  crear una versión nueva y regenerar, nunca sobrescribir.
- **FTS5 con `remove_diacritics 2`**: «cancion» encuentra «canción».
