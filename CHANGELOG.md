# Changelog

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
que el botón nuevo se crea y conecta sin errores. No se probó aún generando
un bundle real sobre los 12 videos ya cargados en la biblioteca del usuario.

### Pendiente / próxima sesión
1. Generar un bundle OKF real sobre la biblioteca existente (12 videos) y
   abrir un par de archivos `.md` para confirmar que los links entre
   video↔entidad resuelven de verdad en el explorador de archivos/editor.
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
