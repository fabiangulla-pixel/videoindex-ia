# Changelog

## 2026-08-07 — Quién dijo qué (diarización) e ingesta desde YouTube

Dos features pedidas juntas, con un destino concreto: convertir una charla
grabada en un texto publicable (transcripción editada para la revista
*Anales* de la U. de Chile).

### Separación de voces (quién habla y cuándo)

- **`domain/diarization.py`** (lógica pura, sin modelos): asignación de
  hablante por **solapamiento temporal máximo** — los cortes de Whisper y los
  de la diarización nunca coinciden, así que no se puede casar por igualdad
  de tiempos. Un segmento sin turno hereda el hablante del anterior (las
  interjecciones cortas no deben partir una intervención en tres).
  `agrupar_intervenciones()` convierte segmentos sueltos en las
  intervenciones legibles que son la unidad de una transcripción publicable.
- **`infrastructure/diarization/ecapa_provider.py`**: embeddings de voz
  ECAPA-TDNN + agrupamiento jerárquico. 100 % local, $0, sin API.
  **Por qué no pyannote** (el estándar del campo): su pipeline depende de
  `pyannote/segmentation-3.0`, modelo *gated* que devuelve 401 sin token de
  HF — rompía la promesa de "descarga y funciona". Se verificó con HEAD
  requests antes de decidir. **Limitación aceptada**: no detecta habla
  superpuesta.
- **`infrastructure/media/audio.py`**: decodificación a PCM mono 16 kHz con
  PyAV (sin ffmpeg). Se guarda int16 y se convierte tramo a tramo: una
  grabación de 2 h son 230 MB en int16 y el doble en float32.
- **Migración v5**: `transcript_segments.speaker`, `semantic_chunks.speakers`,
  tabla `video_speakers` (el nombre REAL que el usuario le pone a cada voz) y
  `videos.source_url/source_channel/source_published_at`.
- **Segmentación**: un cambio de hablante es **frontera dura** de chunk y no
  respeta `chunk_min_s` — un chunk que mezcla voces atribuye mal las citas, y
  eso pesa más que quedarse corto. Desactivable (`cortar_por_hablante`).
- **El pipeline nunca se cae por la diarización**: si el modelo de voz falla,
  se registra y el video se completa sin etiquetas. Perder las etiquetas
  degrada el resultado; perder una hora de transcripción, no.
- **GUI**: menú contextual → "🗣 Transcripción y hablantes…", ventana
  **no-modal** (se usa contra el reproductor: doble clic en una intervención
  salta a ese minuto para verificarla de oído). Renombrar guarda al vuelo.

### Ingesta desde URL

- **`infrastructure/media/youtube.py`**: baja **solo audio**
  (`bestaudio[ext=m4a]`, sin postproceso → **no requiere ffmpeg**) y devuelve
  título, canal y fecha reales. `noplaylist`: una URL con `list=` baja ese
  video, no el curso entero; para varios, una URL por línea.
- Localiza el archivo por id cuando el servidor sirve otra extensión que la
  que `prepare_filename` había predicho (m4a pedido → webm servido).
- **Idempotente por checksum**, igual que el escaneo de carpeta. Si el audio
  ya estaba como archivo local, no se re-transcribe: se le **añade** la
  procedencia (el UPSERT usa COALESCE, nunca borra la que ya había).
- Una URL rota no tumba el lote; se reportan al final.

### Exportación editorial

- **`application/transcript_export_service.py`**: la transcripción como
  documento de trabajo en **Word** (estilos reales, no texto plano en .docx),
  **Markdown** y **SRT**. Los tres llevan ficha de procedencia (fuente,
  canal, fecha, duración) y la advertencia de que es transcripción automática
  pendiente de cotejo con el audio.

### Modelo de Whisper configurable

- Antes estaba cableado a `small`. Ahora se elige en Configuración →
  Transcripción, con el costo en tiempo de cada modelo a la vista. `small`
  alcanza para buscar; para publicar, `large-v3-turbo`.
- Las preferencias de las dos pestañas se **mezclan** en el JSON en vez de
  reemplazarlo: guardar una pestaña ya no borra la otra.
- El ETA usa el factor del modelo elegido + el sobrecosto de diarizar.

### Identificación nominal: de "SPEAKER_01" a "CARLA ULLOA"

La diarización solo dice que una voz es distinta de otra. El nombre no está
en el audio: está en la imagen, en el rótulo sobreimpreso. Se añadió el
cruce de las tres fuentes — turnos de voz × rótulos en pantalla × menciones
verbales — con nivel de confianza y la evidencia que respalda cada nombre.

- **`infrastructure/media/frames.py`**: muestreo de fotogramas con PyAV.
- **`infrastructure/ocr/tesseract_ocr.py`**: OCR por LÍNEAS (en un rótulo el
  nombre y el cargo son datos distintos; unirlos pierde la estructura).
  Filtro de tokens calibrado con material real: las palabras de un rótulo
  salen con confianza 72-93 y el ruido de las texturas con 4-66.
- **`application/rotulos_service.py`**: consenso temporal. El OCR de un
  fotograma suelto no es fiable — el mismo rótulo se leyó «SOLEDAD BIANCHI»,
  «%LEDAD BIANCHI», «IANCHI» y «TE SOLEDAD BIANCHI» en cuadros consecutivos.
  De cada familia de lecturas se toma la **más larga** y se le limpian los
  bordes: la lectura parcial es texto que falta, el ruido del gráfico es
  texto añadido y corto. (Quedarse con la más repetida, que parecía lo
  sensato, devolvía «ULLOA» en vez de «CARLA ULLOA».)
- **`application/identificacion_service.py`**: asigna cada rótulo a quien más
  habla en esa ventana; marca conflictos (un mismo nombre sobre dos voces
  sugiere que la diarización partió a una persona); trata como voz en off a
  la voz que habla mucho y nunca se rotula; y **rechaza las tarjetas de
  cita** para no atribuirle a nadie el título de un libro.
- **`domain/limpieza.py`**: versión de lectura. La lista de muletillas es
  corta a propósito: solo interjecciones sin contenido. "o sea" y "este" se
  quedan porque muchas veces articulan el argumento.
- **`application/entrega_editorial.py`**: paquete de ocho documentos
  (literal, limpia, txt, srt, dos xlsx, incertidumbres, proceso técnico).

Regla que vertebra todo: **es peor inventar un nombre que dejar una voz sin
identificar**. Sin evidencia se usa identificación funcional y el caso va a
`incertidumbres.md`.

### Transcripción reanudable

Transcribir 54 min con `large-v3-turbo` son ~65 min de CPU. La máquina se
suspendió al 84 % y no quedó nada aprovechable, porque los segmentos solo se
guardaban al terminar. Un proceso largo sin checkpoint no es lento: es
**frágil**.

- `TranscriptionProvider` gana `desde_s` (reanudar) y `al_segmento`
  (persistir conforme se produce). `FasterWhisperProvider` reanuda con
  `clip_timestamps`; verificado sobre audio real que los timestamps siguen
  siendo **absolutos** (con `desde_s=600` el primer segmento vuelve con
  `start=600.0`), así que ADR-002 se mantiene.
- `PipelineService` vuelca a la BD cada 25 segmentos (~2 min de audio, que es
  lo máximo que se puede perder) y al arrancar continúa desde donde quedó.
- `_limpiar_derivados` gana `conservar_segmentos`: el borrado idempotente
  destruía justo el trabajo parcial que se quería reanudar.

### Pase de Modo Ingeniero

- **`VideoIndexIA.spec` ahora se versiona**: el `.gitignore` lo excluía con
  la regla genérica `*.spec`, pero está editado a mano y sin él no se
  reconstruye el `.exe`. Actualizado además con `collect_all` de speechbrain
  (sus hiperparámetros son YAML, no código) y yt-dlp (extractores dinámicos).
- **Dependencias declaradas** en `pyproject.toml`: speechbrain, yt-dlp,
  python-docx y, explícitamente, `torch` y `scikit-learn`, que se usan
  directo aunque lleguen como transitivas de sentence-transformers.
- **Prueba negativa del hook de pre-commit** (nunca se había hecho):
  se intentó commitear un archivo con lint en rojo y el hook **abortó** el
  commit. De paso se documentó que pre-commit hace *stash* de lo no indexado,
  así que commitear un subconjunto corre los tests contra un árbol incompleto.
- 179 tests (antes 130), ruff limpio, `check.bat` en verde.

**Pendiente real**: la diarización **no se ha probado con una grabación real**
— solo con audio sintético (que no sirve para validar el umbral automático) y
con fakes deterministas. La primera grabación real es también la calibración
del umbral.

## 2026-07-19 — Soporte ampliado de formatos multimedia

El usuario pidió que la app admitiera más formatos además de mp4 (mp3, wav,
etc.). El pipeline (transcripción, indexado, reproductor, recorte) ya era
agnóstico al contenedor vía PyAV/faster-whisper — el único punto real de
bloqueo era la lista blanca de extensiones en `es_video()`.

- **`infrastructure/media/probe.py`**: `EXTENSIONES_VIDEO` pasa de 9 a 20
  extensiones — video (mp4, mkv, avi, webm, mov, m4v, wmv, flv, mpg, mpeg,
  ts, 3gp) y audio puro (mp3, m4a, wav, flac, ogg, opus, aac, wma).
- **`infrastructure/media/trimmer.py`** (bug encontrado de paso): el
  callback `progreso()` del recorte solo se emitía en paquetes del stream
  "video" — en un archivo de solo audio nunca se llamaba, dejando la barra
  de progreso del recorte congelada en 0% aunque el recorte terminara bien.
  Fix: stream guía (video si existe, si no el primero de audio).
- **GUI**: texto del diálogo de escaneo actualizado ("Carpeta con videos o
  audios").
- **Tests nuevos**: `es_video()` con las 20 extensiones (`test_probe.py`),
  ingesta de un `.mp3` real ignorando archivos no-multimedia
  (`test_ingest.py`), progreso creciente en recorte de audio puro
  (`test_trimmer_real.py`, slow). 124 tests rápidos en verde, ruff limpio.

**Pendiente**: no se probó el pipeline completo (transcripción→segmentación→
NER→embeddings→índice) con un archivo de audio real (solo wav sintéticos de
segundos, silenciosos, para los tests unitarios). El usuario decidió no
hacer esa prueba en esta sesión — queda para la próxima vez que cargue un
mp3/wav real a la biblioteca.

### Despliegue
`.exe` recompilado con `scripts\build_exe.ps1` (`--clean`); verificado
extrayendo el bytecode del PYZ compilado (`ZlibArchiveReader`) que
`probe.py`/`trimmer.py` contienen los cambios — no se confió solo en el log
del build. Smoke test (~8s vivo, 166 MB, sin stderr) OK. Sincronizado con
`robocopy /MIR /XD data` a
`I:\Mi unidad\00_Programas y macros\VideoIndex IA\Para usar en cualquier PC\VideoIndexIA\`
(5481/5662 archivos copiados — el resto ya estaba al día por un intento
anterior interrumpido por corte de sesión; 0 errores, `data\` con la
biblioteca real de 12 videos intacta).

## 2026-07-13 — Exportación como bundle OKF (Open Knowledge Format)

Sesión disparada por una pregunta del usuario sobre un estándar nuevo que
Google Cloud anunció el 12-jun-2026 (OKF): empaquetar conocimiento como un
directorio de archivos Markdown con frontmatter YAML, para que cualquier
agente de IA lo lea sin depender de una base de datos ni SDK propietario.
Verificado con la spec real en GitHub antes de implementar (no se asumió
nada): OKF deja embeddings/búsqueda/indexación fuera de su alcance a
propósito — es una capa de **portabilidad**, no reemplaza a `SearchEngine`
(FAISS+FTS5+entidades+confianza, que sigue siendo la única puerta al
conocimiento, ADR-003).

- **`application/okf_export_service.py`** (nuevo): `exportar_video_okf` y
  `exportar_proyecto_okf` generan un bundle (`index.md` + `videos/*.md` +
  `entities/*.md`) a partir de lo que ya hay en SQLite — mismo espíritu $0
  y mismo alcance que `export_service.py` (JSON), sin llamadas a LLM.
  Entidades repetidas entre varios videos de un proyecto se funden en UN
  solo archivo con todas sus apariciones (no se duplican). Slugs con
  sufijo del id (nunca colisionan, a diferencia del saneo simple que ya
  usaba el export JSON) porque aquí los archivos se enlazan entre sí y una
  colisión rompería los links.
- **GUI**: botón "🗂 Exportar bundle OKF…" en la barra de Biblioteca
  (proyecto activo) + entrada en el menú contextual por video, en paralelo
  exacto a "📦 Exportar corpus JSON…" ya existente.
- **Tests**: `tests/unit/test_okf_export_service.py` (7 nuevos) — estructura
  del bundle, slugs sin colisión, escape de frontmatter (comillas/saltos de
  línea), fusión de entidades entre videos, filtrado de no-completados,
  contenido del índice.

125 tests (118→125), ruff limpio. Smoke offscreen de `LibraryView` confirma
que el botón nuevo se crea y conecta sin errores.

### Despliegue
`.exe` recompilado con `scripts\build_exe.ps1` (`--clean`), verificado que el
PYZ contiene `okf_export_service`, smoke test (~8s vivo, ~160MB RAM, sin
stderr) OK. Sincronizado con `robocopy /MIR /XD data` (1.11 GB, 5662 archivos,
0 errores, ~39 min por ser hacia Google Drive) a
`I:\Mi unidad\00_Programas y macros\VideoIndex IA\Para usar en cualquier PC\VideoIndexIA\`
— `data\videoindex.db` (la biblioteca de 12 videos del usuario) quedó intacta.
Segundo smoke test sobre el binario ya desplegado, también limpio.

### Pendiente / próxima sesión
1. Generar un bundle OKF real sobre la biblioteca existente (12 videos) y
   abrir un par de archivos `.md` para confirmar que los links entre
   video↔entidad resuelven de verdad en el explorador de archivos/editor
   (solo se probó con datos sintéticos de test hasta ahora).
2. El prompt para replicar este mismo patrón en otros proyectos (Bashkar
   Station, con su propio modelo de entidades canónicas/relaciones) quedó
   redactado y entregado al usuario — pendiente de que lo ejecute él
   cuando quiera en ese repo.
3. Pendientes heredados de sesiones anteriores (API key de LLM para probar
   la fase 2 del Dossier, E2E histórica con la carpeta real de "Agentes de
   IA para abogadxs") siguen sin resolver — ver entradas anteriores de este
   changelog.

## 2026-07-08 — Reproductor confiable, recorte de video, corpus por proyecto y export JSON

Sesión guiada por la prueba real del usuario con la carpeta "Agentes de IA
para abogadxs" (proyecto "Prueba SSD-P", archivos copiados a un SSD nuevo).

- **Reproductor**: fix de fondo — el salto al timestamp se disparaba con un
  timer fijo de 300 ms sin esperar a que el video cargara; en esta máquina
  (sin GPU, archivos de 600 MB-1 GB) el seek se perdía y había que darle
  Play a mano. Ahora escucha `mediaStatusChanged` y reproduce+salta cuando
  el video está realmente listo ("⏳ Cargando…" mientras tanto). Controles
  nuevos: ⏪/⏩ 10 s, volumen con mute (no existía), velocidad 0.75x–2x.
- **✂ Recorte antes de transcribir** (`infrastructure/media/trimmer.py` +
  `TrimDialog` + `TrimWorker`): remux PyAV sin re-codificar (una grabación
  de 2 h se recorta en segundos aun sin GPU; corte en el keyframe más
  cercano). El original en disco NUNCA se toca: el recorte es archivo nuevo
  que reemplaza al original en la biblioteca (hereda proyecto/curso). Menú
  contextual, solo pending/failed. El detector de negro inicial pre-llena
  la marca de inicio.
- **Fix crítico de proyectos**: re-escanear archivos ya conocidos (mismo
  checksum, p. ej. copiados a otro disco) bajo un proyecto NO los asignaba
  → tabla vacía bajo el filtro del proyecto nuevo. Ahora el escaneo adopta
  al proyecto activo los videos huérfanos (sin robar los de otro proyecto).
- **Corpus por proyecto**: Buscar y Preguntar respetan el selector de
  proyecto — cada proyecto es un corpus aparte (FTS filtra en SQL; FAISS
  sobre-pide x3 y descarta otros proyectos). "Todos los proyectos" mantiene
  el comportamiento anterior.
- **📦 Export de corpus a JSON** (`application/export_service.py`): un JSON
  por video (metadatos + chunks con timestamps/entidades + anotaciones
  manuales), por video (menú contextual) o por proyecto completo (botón en
  Biblioteca). UTF-8 sin escapar, listo para otro RAG/GPT.
- También: `VideoDeletionService` acepta embedder/faiss None para borrado
  ligero de pendientes sin cargar modelos.

118 tests rápidos + 4 slow nuevos del trimmer (mp4 sintéticos reales),
ruff limpio, smoke GUI OK.

## 2026-07-07 (cierre de sesión) — Verificación del Dossier + commit de features pendientes

Sesión de retomada desde TarotCultural (se evaluó si VideoIndex IA sirve
para extraer el contenido de clases en video — sí, y de hecho ya reutiliza
`transcribir.py` de ese proyecto). Al revisar el repo, se encontró que el
Dossier del video (ver entrada de abajo) ya estaba implementado, más otros
9 archivos con trabajo sin commitear encima:

- **Proyectos**: tabla `projects` (migración v4), `Video.project_id`,
  agrupador real de videos en la Biblioteca (antes solo `course_name`
  como texto libre sin uso en la GUI).
- **Eliminación de video**: `application/video_deletion_service.py` +
  `EliminarVideoWorker` — borra transcripción/chunks/entidades/embeddings
  FAISS/anotaciones de un video.
- **LM Studio como proveedor local** ($0): `LMStudioProvider` en
  `infrastructure/llm/providers.py`, API compatible OpenAI
  (`/v1/chat/completions`), catálogo de modelos consultado en vivo vía
  `/v1/models` (no hay lista fija: depende de lo que el usuario cargó).
- **Progreso granular de transcripción**: `TranscriptionProvider.transcribir()`
  gana un callback `progreso(fraccion)` opcional.

Verificado todo antes de commitear: 97→103 tests verdes (unit+integration),
ruff limpio. Commit `744fd6e`.

### Prueba E2E del Dossier (parcial)

La biblioteca ya tiene 12 videos reales procesados (grabaciones Zoom
`GMT2026...` + `S1`/`S2`). Se ejecutó la fase 1 del Dossier
(`recopilar_evidencia_por_entidad`, sin costo) sobre "S1" real: 172
chunks, 143 entidades, estimación agregada correcta ($0.548 USD). La
fase 2 (llamada real al LLM) quedó **bloqueada por falta de API key** —
no hay ninguna guardada en Credential Manager ni en variables de entorno.
Pendiente: configurar una key (Gemini, ya es el default) y completar la
prueba con una llamada real acotada (2-3 entidades, ~$0.01 USD).

Nota: "S1"/"S2" no son las clases de tarot cultural (entidades como
"Home Center", "John McCarty" sugieren otro curso) — la ruta de esos
videos aún no se ha identificado.

## 2026-07-07 — Dossier del video

**Feature nueva** pedida por el usuario: dado un video ya transcrito e
indexado, agrupar TODO su contenido por entidad detectada (cobertura
completa vía una sola query JOIN, no un top-k de búsqueda como el RAG
puntual) y que el LLM escriba un resumen narrativo por entidad, con el
mismo contrato de evidencia/citas `[n]`→timestamp que `RAGService`, costo
estimado antes/real después, exportable a Markdown.

**Diseño clave**: se reutilizan las funciones puras de `rag_service.py`
(`SYSTEM_PROMPT`, `construir_prompt_usuario`, `parsear_citas`) y de
`costos.py` (`estimar_pregunta_rag`, `costo_real_desde_usages`) sin
modificar ninguno de los dos archivos — el dossier vive en un módulo
nuevo (`application/dossier_service.py`) que aplica ese mismo contrato N
veces (una por entidad), sobre una única instancia de `LLMProvider` para
que `usages()` acumule correctamente. El costo real se calcula UNA sola
vez al final, agregado — no se prorratea por entidad.

### Archivos modificados/creados
| Archivo | Cambio |
|---|---|
| `infrastructure/db/repositories.py` | `ChunkRepo.por_video()` (todos los chunks de un video, orden temporal) + `EntityRepo.catalogo_de_video()` (todas las entidades del video con sus chunks, una sola query, evita N+1) |
| `domain/models.py` | Nuevo dataclass `DossierEntidad` (envuelve `RAGAnswer` sin modificarlo) |
| `application/dossier_service.py` | **Nuevo.** `DossierService` (recopilar evidencia por entidad, estimar costo agregado, generar, exportar a Markdown) + `EstimacionDossier` |
| `presentation/workers.py` | `DossierRecopilarWorker` + `DossierGenerarWorker` (QThread, conexión SQLite propia por hilo, sin `ServiciosCache`) |
| `presentation/dossier_view.py` | **Nuevo.** `DossierConfirmDialog` (selector proveedor/modelo propio, independiente del default de Preguntar) + `DossierResultDialog` (visor + exportar) |
| `presentation/library_view.py` | Menú contextual "📄 Generar dossier del video…" en la tabla de Biblioteca (solo si `completed`) |
| `tests/unit/test_dossier.py` | **Nuevo.** 5 tests con `FakeLLMSecuencial` (respuesta distinta por llamada) |
| `tests/unit/test_repositories.py` | +3 tests para `catalogo_de_video`/`por_video` |

82 tests verdes, ruff limpio, smoke GUI OK. Commit `0cb9c14`.

### Despliegue
`.exe` recompilado con `scripts/build_exe.ps1`, verificado que el PYZ
contiene `dossier_service`/`dossier_view`, smoke test (~15s vivo, ~200MB
RAM) OK. Sincronizado a
`I:\Mi unidad\00_Programas y macros\VideoIndex IA\Para usar en cualquier PC\VideoIndexIA\`.

**⚠️ Incidente durante el deploy**: el primer `robocopy /MIR` sin excluir
`data\` empezó a **purgar la carpeta de datos del deploy portable** (BD,
índice FAISS, checkpoints) porque `/MIR` sincroniza en ambas direcciones
y esa carpeta no existía en el origen (`dist/`). Se detuvo el proceso a
tiempo (`Stop-Process robocopy`); la verificación posterior mostró que la
BD portable ya estaba vacía de antes (0 videos), así que no se perdió
trabajo real, pero pudo haberlo hecho. Se repitió el robocopy con
`/XD data` para excluir esa carpeta. Ver memoria
`feedback_exe_deploy.md` — regla añadida para futuros despliegues.

### Pendiente / próxima sesión
1. **E2E manual del Dossier** con un video real `completed`: clic derecho
   en Biblioteca → "Generar dossier" → elegir proveedor/modelo → confirmar
   costo → ver resultado con citas → exportar a `.md` y abrir el archivo.
2. Confirmar que un video **sin entidades** detectadas muestra el mensaje
   informativo sin llamar al LLM (costo $0).
3. Retomar la prueba E2E pendiente de sesiones anteriores con la carpeta
   real del usuario (`I:\...\Agentes de IA para abogadxs`, 2 videos, 3.47
   GB en Drive) — ya con todos los fixes de threading/embeddings offline
   y todas las features nuevas (config API keys, anotaciones, salto de
   negro inicial, dossier).
4. Verificar que la sincronización a la carpeta portable con `/XD data`
   terminó sin errores (quedó corriendo en background al cerrar esta
   sesión).

## Sesiones anteriores

Ver memoria `project_videoindex.md` para el historial completo desde el
MVP inicial (E0–E6), fixes críticos de threading/embeddings offline, y
features de configuración de API keys / anotaciones / salto de
negro-silencio inicial.
