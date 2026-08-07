# -*- mode: python ; coding: utf-8 -*-
# EDITADO A MANO — no regenerar con pyi-makespec, se perderían estos ajustes.
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = [('C:\\Users\\Lenovo\\VideoIndexIA\\.venv\\Lib\\site-packages\\es_core_news_md', 'es_core_news_md'), ('src\\videoindex\\infrastructure\\db\\schema.sql', 'videoindex\\infrastructure\\db')]
binaries = []
# Módulos que solo se importan dentro de funciones o en try/except: el
# análisis estático los encuentra casi siempre, pero listarlos es barato y
# evita un .exe que arranca y falla al abrir una ventana concreta.
hiddenimports = [
    'keyring.backends.Windows',
    'videoindex.presentation.ask_view',
    'videoindex.presentation.transcript_dialog',
    'videoindex.presentation.url_dialog',
    'videoindex.infrastructure.diarization.ecapa_provider',
]
for _paquete in (
    'faster_whisper',
    'ctranslate2',
    'faiss',
    'keyring',
    # Diarización: speechbrain carga sus hiperparámetros desde archivos YAML
    # que no son código, así que sin collect_all el .exe no puede instanciar
    # el modelo de voz.
    'speechbrain',
    # yt-dlp resuelve sus extractores por import dinámico: sin collect_all
    # solo funcionarían los sitios que PyInstaller alcance a ver.
    'yt_dlp',
):
    tmp_ret = collect_all(_paquete)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# python-docx trae la plantilla .docx por defecto como dato, no como código.
datas += collect_data_files('docx')


a = Analysis(
    ['src\\videoindex\\app.py'],
    pathex=['src'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VideoIndexIA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VideoIndexIA',
)
