@echo off
chcp 65001 >nul
title Auditoria de balancetes
cd /d "%~dp0"

echo.
echo  Auditoria de balancetes
echo  ==============
echo.
echo  [1/3] Subindo o banco de dados...
docker compose up -d >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Nao consegui subir o banco. Abra o Docker Desktop, espere ele ficar pronto e tente de novo.
  echo.
  pause
  exit /b 1
)

echo  [2/3] Aguardando o banco ficar pronto...
set /a TENTATIVAS=0
:espera
docker compose exec -T db pg_isready -U auditoria -d auditoria >nul 2>&1
if not errorlevel 1 goto pronto
set /a TENTATIVAS+=1
if %TENTATIVAS% geq 30 (
  echo  O banco nao respondeu em 30 segundos. Verifique o Docker Desktop.
  pause
  exit /b 1
)
timeout /t 1 >nul
goto espera
:pronto

rem Usa a porta 8500; se estiver ocupada, a 8501.
set PORTA=8500
netstat -ano | findstr /r /c:"127.0.0.1:8500 .*LISTENING" >nul && set PORTA=8501

echo  [3/3] Iniciando o site em http://127.0.0.1:%PORTA%
echo.
echo  O navegador abre sozinho em alguns segundos.
echo  Para parar o site, feche esta janela (ou aperte Ctrl+C).
echo.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:%PORTA%"
".venv\Scripts\python.exe" -m uvicorn web.app:app --host 127.0.0.1 --port %PORTA%

echo.
echo  O site parou.
pause
