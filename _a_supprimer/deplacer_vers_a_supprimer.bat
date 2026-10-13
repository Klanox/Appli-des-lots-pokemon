@echo off
setlocal
rem Deplace (ne supprime rien) les elements valides A + C2 vers _a_supprimer\ en gardant l'arborescence.
cd /d "%~dp0.."
if not exist app.py (echo ERREUR: lancer ce script depuis _a_supprimer\ du projet & pause & exit /b 1)
set OK=0
set ABS=0
set LOG=_a_supprimer\deplacement_log.txt
echo Deplacement du %date% %time% > "%LOG%"

call :mv "_tmp_streamlit.png" ""
call :mv "cleanup_deleted_log.txt" ""
call :mv "cleanup_moved_log.txt" ""
call :mv "streamlit_estimations_polish_test.out.log" ""
call :mv "streamlit_market_test.err.log" ""
call :mv "streamlit_market_test.out.log" ""
call :mv "streamlit_p0_test.err.log" ""
call :mv "streamlit_p0_test.out.log" ""
call :mv "streamlit_p8k_test.err.log" ""
call :mv "streamlit_p8k_test.out.log" ""
call :mv "streamlit_p8l_final.err.log" ""
call :mv "streamlit_p8l_final.out.log" ""
call :mv "streamlit_p8l_test.err.log" ""
call :mv "streamlit_p8l_test.out.log" ""
call :mv "streamlit_p8m_test.err.log" ""
call :mv "streamlit_p8m_test.out.log" ""
call :mv "backups\app.py.backup_20261011_priceloss" "backups"
call :mv "backups\app.py.backup_20261011_cloudbg" "backups"
call :mv "backups\app.py.backup_20261011" "backups"
call :mv "backups\estimations.py.bak_20261013_1130_avant_fragment_alertes" "backups"
call :mv "backups\estimations.py.bak_20261012_2210_avant_doublon_champ_nom" "backups"
call :mv "backups\estimations.py.bak_20261012_2105_avant_perf_caches" "backups"
call :mv "backups\estimations.py.bak_20261012_2045_avant_retrait_boutons_cartes" "backups"
call :mv "backups\estimations.py.bak_20261012_2030_avant_images_nom_en_place" "backups"
call :mv "backups\estimations.py.bak_20261012_2025_avant_images_perso_cardmarket_prefixe" "backups"
call :mv "backups\estimations.py.bak_20261012_2010_avant_pause_frappe_nom_vignettes" "backups"
call :mv "backups\estimations.py.bak_20261012_1950_avant_reset_ajout" "backups"
call :mv "backups\estimations.py.bak_20261012_1940_avant_cardmarket_jp" "backups"
call :mv "backups\estimations.py.bak_20261012_1925_avant_japonais_tuiles" "backups"
call :mv "backups\estimations.py.bak_20261012_1915_avant_cardmarket_vignettes" "backups"
call :mv "backups\estimations.py.bak_20261012_1900_avant_fix_cote_auto" "backups"
call :mv "backups\estimations.py.bak_20261012_1850_avant_autosave" "backups"
call :mv "backups\estimations.py.bak_20261012_1830_avant_parties_ABC" "backups"
call :mv "backups\estimations.py.bak_20261012_1800_avant_refonte" "backups"
call :mv "backups\estimations.py.bak_20261012_1745_avant_cartes_compactes" "backups"
call :mv "backups\estimations.py.bak_20261012_1710" "backups"
call :mv "backups\vinted_drops_service.py.backup_20261011" "backups"
call :mv "backups\vinted_listings.py.backup_20261011" "backups"
call :mvdir ".cache\smoke_input" ".cache"
call :mvdir ".cache\photo_recognition\drop_sessions\browser_uploads\drop-smoke" ".cache\photo_recognition\drop_sessions\browser_uploads"

echo.
echo Deplaces : %OK%   Deja absents : %ABS%
echo Deplaces : %OK%   Deja absents : %ABS% >> "%LOG%"
echo Journal : %LOG%
pause
exit /b 0

:mv
if not exist "%~1" (set /a ABS+=1 & echo ABSENT %~1 >> "%LOG%" & goto :eof)
if "%~2"=="" (set "D=_a_supprimer") else (set "D=_a_supprimer\%~2")
if not exist "%D%" mkdir "%D%"
move "%~1" "%D%\" >nul && (set /a OK+=1 & echo OK %~1 >> "%LOG%") || (echo ECHEC %~1 & echo ECHEC %~1 >> "%LOG%")
goto :eof

:mvdir
if not exist "%~1" (set /a ABS+=1 & echo ABSENT %~1 >> "%LOG%" & goto :eof)
set "D=_a_supprimer\%~2"
if not exist "%D%" mkdir "%D%"
move "%~1" "%D%\" >nul && (set /a OK+=1 & echo OK %~1 >> "%LOG%") || (echo ECHEC %~1 & echo ECHEC %~1 >> "%LOG%")
goto :eof
