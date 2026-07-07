# Crea el venv del proyecto con Python 3.12 (ctranslate2 no soporta 3.14)
# y verifica los requisitos críticos. Falla ruidosamente si algo no está.
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install faster-whisper sentence-transformers faiss-cpu spacy PySide6 `
    google-genai openai anthropic keyring av numpy pytest ruff pre-commit pyinstaller
.\.venv\Scripts\python.exe -m spacy download es_core_news_md

# Verificaciones E0
.\.venv\Scripts\python.exe -c "import ctranslate2; print('ctranslate2 OK', ctranslate2.__version__)"
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect(':memory:'); c.execute(""CREATE VIRTUAL TABLE t USING fts5(x)""); print('FTS5 OK')"
Write-Host "venv listo. Corre los tests: .venv\Scripts\python.exe -m pytest"
