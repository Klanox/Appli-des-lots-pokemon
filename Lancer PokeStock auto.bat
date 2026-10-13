@echo off
cd /d "%~dp0"
chcp 65001 >nul
where python >nul 2>nul
if errorlevel 1 (
  echo Python est introuvable dans le PATH.
  pause
  exit /b 1
)
python "%~dp0pokestock_auto_restart.py"
echo.
echo Le lanceur est arrete. Appuie sur une touche pour fermer cette fenetre.
pause >nul
