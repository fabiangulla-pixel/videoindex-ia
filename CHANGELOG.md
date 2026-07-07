# Changelog

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
