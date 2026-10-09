@echo off
echo ============================================
echo   PILOTO - Compilador automatico
echo ============================================
echo.

REM ---- 1) Verifica se Python esta instalado ----
python --version >nul 2>&1
if errorlevel 1 (
    echo [1/4] Python nao encontrado. Baixando instalador...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%TEMP%\python_install.exe'"
    echo       Instalando Python (aguarde, pode demorar 2 min)...
    "%TEMP%\python_install.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    if errorlevel 1 (
        echo.
        echo [ERRO] Nao consegui instalar o Python automaticamente.
        echo        Instale manualmente em https://python.org e rode esse .bat de novo.
        pause
        exit /b 1
    )
    echo       Python instalado. Fechando e reabrindo...
    echo       Rode esse .bat de novo (precisa recarregar o PATH).
    pause
    exit /b 0
) else (
    echo [1/4] Python OK.
)

REM ---- 2) Instala as dependencias ----
echo [2/4] Instalando dependencias...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install flask pycaw comtypes pyinstaller
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias.
    pause
    exit /b 1
)

REM ---- 3) Limpa builds antigos ----
echo [3/4] Limpando builds antigos...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist piloto.spec del /q piloto.spec

REM ---- 4) Compila ----
echo [4/4] Compilando o exe (pode demorar 1-2 min)...
python -m PyInstaller --noconsole --onefile --name piloto ^
  --hidden-import=pycaw ^
  --hidden-import=pycaw.pycaw ^
  --hidden-import=pycaw.api ^
  --hidden-import=pycaw.utils ^
  --hidden-import=pycaw.constants ^
  --hidden-import=comtypes ^
  --hidden-import=comtypes.client ^
  --hidden-import=comtypes.stream ^
  piloto.py

if errorlevel 1 (
    echo.
    echo [ERRO] Falha na compilacao. Veja as mensagens acima.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   PRONTO!
echo   Seu exe esta em: dist\piloto.exe
echo ============================================
echo.
pause