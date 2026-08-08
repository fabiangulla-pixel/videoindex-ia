"""Regresión: diarizar y luego indexar en el MISMO proceso no debe romperse.

Bug real encontrado con la app entera corriendo (no lo veían ni los tests con
fakes ni los scripts sueltos, porque en ellos las dos pilas nunca convivían):

  1. la diarización carga speechbrain;
  2. la segmentación importa después sentence_transformers;
  3. su cadena llega a torch._dynamo, que recorre sys.modules mirando los
     atributos de cada módulo cargado;
  4. ese recorrido despierta un módulo perezoso de speechbrain para una
     integración opcional (k2, no instalada) y lanza ImportError.

Resultado: el video fallaba en "segmenting", después de diarizar bien, con un
mensaje que no mencionaba ni speechbrain ni la diarización.

Se prueba en un SUBPROCESO porque lo que se verifica es el orden de
importación, y dentro de pytest los módulos ya podrían estar cargados.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.slow

_GUION = """
import sys
sys.path.insert(0, {ruta!r})
{cuerpo}
print("SIN_ERROR")
"""


def _correr(cuerpo: str) -> tuple[int, str]:
    guion = _GUION.format(ruta="src", cuerpo=textwrap.dedent(cuerpo))
    proc = subprocess.run(
        [sys.executable, "-c", guion], capture_output=True, text=True, timeout=900
    )
    return proc.returncode, (proc.stdout + proc.stderr)


def test_el_provider_de_diarizacion_deja_importar_los_embeddings_despues():
    """Con el arreglo puesto, el orden real de la app funciona."""
    codigo, salida = _correr(
        """
        from videoindex.infrastructure.diarization.ecapa_provider import _codificador
        import inspect
        # No se descarga el modelo: basta con ejecutar los imports del provider,
        # que es donde vive la protección de orden.
        fuente = inspect.getsource(_codificador)
        assert "torch._dynamo" in fuente, "se perdió la protección de orden"
        import torch._dynamo  # lo que hace _codificador antes de speechbrain
        from speechbrain.inference.speaker import EncoderClassifier  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
        """
    )
    assert "SIN_ERROR" in salida, salida[-2000:]
    assert codigo == 0


def test_sin_la_proteccion_el_orden_de_la_app_si_rompe():
    """Prueba negativa: documenta que el problema es real y no imaginario.

    Si algún día speechbrain deja de fallar así, este test empezará a fallar y
    sabremos que la protección ya no hace falta.
    """
    codigo, salida = _correr(
        """
        from speechbrain.inference.speaker import EncoderClassifier  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
        """
    )
    assert codigo != 0 or "SIN_ERROR" not in salida, (
        "speechbrain ya no rompe el orden: la protección de _codificador podría retirarse"
    )
    assert "k2" in salida or "Lazy import" in salida, salida[-1500:]
