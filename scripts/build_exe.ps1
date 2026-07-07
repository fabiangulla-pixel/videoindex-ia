# Compila VideoIndexIA.exe con PyInstaller.
# LECCIONES aprendidas en otros proyectos del usuario:
#  - compilar SIEMPRE en disco local C: (nunca Google Drive I:)
#  - SIEMPRE --clean (la cache vieja de PyInstaller ha dado exe desactualizados)
#  - spaCy va como datos (spacy_loader ya sabe encontrarlo en _MEIPASS)
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

$spacyModel = .\.venv\Scripts\python.exe -c "import es_core_news_md, pathlib; print(pathlib.Path(es_core_news_md.__file__).parent)"

.\.venv\Scripts\pyinstaller.exe --clean --noconfirm --windowed --name VideoIndexIA `
    --paths src `
    --add-data "$spacyModel;es_core_news_md" `
    --add-data "src\videoindex\infrastructure\db\schema.sql;videoindex\infrastructure\db" `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all faiss `
    --collect-all keyring `
    --hidden-import keyring.backends.Windows `
    --hidden-import videoindex.presentation.ask_view `
    src\videoindex\app.py

Write-Host ""
Write-Host "Build listo en dist\VideoIndexIA\VideoIndexIA.exe"
Write-Host "Smoke test: dist\VideoIndexIA\VideoIndexIA.exe"
