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

- **Ingesta** de carpetas locales de video (mp4/mkv/avi/webm/mov + audio),
  idempotente por checksum sha256: re-escanear no duplica, mover archivos no rompe.
- **Transcripción** 100 % local con faster-whisper (CPU, int8, $0) con
  timestamps absolutos (ADR-002) y confianza por segmento.
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
- **`QT_MEDIA_BACKEND=windows`** (lo fija `app.py`): el backend ffmpeg de Qt
  crashea al renderizar video en esta máquina; el nativo WMF funciona. El seek
  se hace 300 ms después de `play()` o WMF lo pisa.
- **FAISS serializado vía Python** (`serialize_index`/`deserialize_index`):
  `write_index` de C++ falla con rutas Windows con tildes.
- **Embeddings versionados** (tabla `embedding_versions`): migrar de modelo es
  crear una versión nueva y regenerar, nunca sobrescribir.
- **FTS5 con `remove_diacritics 2`**: «cancion» encuentra «canción».
