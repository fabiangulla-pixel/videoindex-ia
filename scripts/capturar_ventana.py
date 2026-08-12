"""Captura la ventana de la app REAL para ver qué muestra de verdad.

Usa PrintWindow(hwnd), que le pide a la ventana que se dibuje en un contexto
propio. No mueve el ratón, no hace clic y no depende de que la ventana esté
en primer plano ni de las coordenadas de pantalla — nada de CopyFromScreen.

Sirve para responder "¿el .exe tiene de verdad lo nuevo?" mirando el
resultado, en vez de deducirlo del log de compilación.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

TITULO = "VideoIndex IA"
DESTINO = Path(r"C:\Users\Lenovo\AppData\Local\Temp\claude\ventana_videoindex.png")
PW_RENDERFULLCONTENT = 0x00000002


def ventanas_del_proceso(pid: int, espera_s: float = 90.0) -> list[tuple[int, str]]:
    """Todas las ventanas visibles de un proceso, con su título.

    Buscar por título no basta: la app abre un QMessageBox modal ANTES de
    mostrar la ventana principal, y ese diálogo se llama de otra manera. Por
    el PID se ve lo que el ejecutable está enseñando de verdad.
    """

    def _una_pasada() -> list[tuple[int, str]]:
        # La lista vive dentro de esta función y no del bucle: una closure
        # que captura una variable del bucle exterior es una trampa clásica.
        encontradas: list[tuple[int, str]] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cada(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            suyo = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(suyo))
            if suyo.value == pid:
                largo = user32.GetWindowTextLengthW(hwnd)
                buffer = ctypes.create_unicode_buffer(largo + 1)
                user32.GetWindowTextW(hwnd, buffer, largo + 1)
                encontradas.append((hwnd, buffer.value))
            return True

        user32.EnumWindows(_cada, 0)
        return encontradas

    limite = time.time() + espera_s
    while time.time() < limite:
        if encontradas := _una_pasada():
            return encontradas
        time.sleep(1.0)
    return []


def buscar_ventana(fragmento: str, espera_s: float = 60.0) -> int:
    """hwnd de la primera ventana visible cuyo título contenga `fragmento`."""
    encontrado = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cada(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        largo = user32.GetWindowTextLengthW(hwnd)
        if largo:
            buffer = ctypes.create_unicode_buffer(largo + 1)
            user32.GetWindowTextW(hwnd, buffer, largo + 1)
            if fragmento.lower() in buffer.value.lower():
                encontrado.append((hwnd, buffer.value))
                return False
        return True

    limite = time.time() + espera_s
    while time.time() < limite:
        user32.EnumWindows(_cada, 0)
        if encontrado:
            return encontrado[0]
        time.sleep(1.0)
    return (0, "")


def capturar(hwnd: int, destino: Path) -> tuple[int, int]:
    from PIL import Image

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    ancho, alto = rect.right - rect.left, rect.bottom - rect.top

    dc_ventana = user32.GetWindowDC(hwnd)
    dc_memoria = gdi32.CreateCompatibleDC(dc_ventana)
    mapa = gdi32.CreateCompatibleBitmap(dc_ventana, ancho, alto)
    gdi32.SelectObject(dc_memoria, mapa)
    # PW_RENDERFULLCONTENT: sin esto, las superficies aceleradas (como el
    # reproductor de video) salen en negro.
    user32.PrintWindow(hwnd, dc_memoria, PW_RENDERFULLCONTENT)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    cabecera = BITMAPINFOHEADER()
    cabecera.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    cabecera.biWidth = ancho
    cabecera.biHeight = -alto  # negativo = filas de arriba abajo
    cabecera.biPlanes = 1
    cabecera.biBitCount = 32
    buffer = ctypes.create_string_buffer(ancho * alto * 4)
    gdi32.GetDIBits(dc_memoria, mapa, 0, alto, buffer, ctypes.byref(cabecera), 0)

    imagen = Image.frombuffer("RGB", (ancho, alto), buffer, "raw", "BGRX", 0, 1)
    destino.parent.mkdir(parents=True, exist_ok=True)
    imagen.save(destino)

    gdi32.DeleteObject(mapa)
    gdi32.DeleteDC(dc_memoria)
    user32.ReleaseDC(hwnd, dc_ventana)
    return ancho, alto


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1].isdigit():
        ventanas = ventanas_del_proceso(int(sys.argv[1]))
        if not ventanas:
            print("El proceso no tiene ninguna ventana visible")
            sys.exit(1)
        for i, (hwnd, titulo) in enumerate(ventanas):
            destino = DESTINO.with_stem(f"{DESTINO.stem}_{i}")
            ancho, alto = capturar(hwnd, destino)
            print(f"  «{titulo}»  {ancho}x{alto} -> {destino}")
        sys.exit(0)
    fragmento = sys.argv[1] if len(sys.argv) > 1 else TITULO
    hwnd, titulo = buscar_ventana(fragmento)
    if not hwnd:
        print(f"No se encontró ninguna ventana visible con «{fragmento}»")
        sys.exit(1)
    print(f"Ventana: «{titulo}» (hwnd {hwnd})")
    ancho, alto = capturar(hwnd, DESTINO)
    print(f"Capturada {ancho}x{alto} -> {DESTINO}")
