@echo off
echo ========================================
echo   Pokemon Lot Manager Pro - Lancement
echo ========================================
echo.
echo Demarrage de Streamlit...
echo.

REM Activer l'environnement virtuel si il existe
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

REM Lancer Streamlit
streamlit run app.py

pause
