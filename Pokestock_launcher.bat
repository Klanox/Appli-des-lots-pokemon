@echo off
cd /d "C:\Users\User\Desktop\Appli des lots pokemon"

start "" /min cmd /c "python -m streamlit run app.py --server.headless true --server.port 8501"

timeout /t 3 /nobreak >nul

start "" "C:\Users\User\AppData\Local\Programs\Opera GX\opera.exe" --app="http://localhost:8501"

exit