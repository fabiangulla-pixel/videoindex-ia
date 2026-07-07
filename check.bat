@echo off
REM CI local: lint + formato + tests. Correr antes de cada commit.
setlocal enabledelayedexpansion
set FALLO=0

echo [1/3] ruff check...
.venv\Scripts\ruff.exe check src tests
if errorlevel 1 set FALLO=1

echo [2/3] ruff format --check...
.venv\Scripts\ruff.exe format --check src tests
if errorlevel 1 set FALLO=1

echo [3/3] pytest (suite rapida)...
.venv\Scripts\python.exe -m pytest -q
if errorlevel 1 set FALLO=1

if !FALLO! == 1 (
    echo.
    echo [FALLO] Alguna verificacion no paso.
    exit /b 1
) else (
    echo.
    echo [OK] Todo en orden.
    exit /b 0
)
