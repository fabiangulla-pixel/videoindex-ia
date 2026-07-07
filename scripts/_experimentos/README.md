# Experimentos archivados

Scripts de diagnóstico puntual, ya resueltos. Se conservan como referencia
histórica, no forman parte del flujo normal del proyecto.

- **smoke_player.py** / **smoke_player_min.py**: usados en la etapa E0 para
  diagnosticar por qué `QVideoWidget` crasheaba al renderizar video en esta
  máquina (Windows 10, sin GPU). Confirmaron que el backend `ffmpeg` de Qt
  Multimedia falla y que el backend nativo `windows` (WMF) funciona. La
  solución (`QT_MEDIA_BACKEND=windows`, fijado en `app.py`) ya está aplicada
  en el producto; ver README.md del proyecto, sección "Decisiones técnicas".
