@echo off
echo ========================================
echo   RESET COMPLET - Pokemon Lot Manager
echo ========================================
echo.
echo ATTENTION : Cette action va supprimer TOUTES les donnees !
echo.
pause

del data.json 2>nul
del lots_archives.json 2>nul
del cards_cache.json 2>nul
del pokemon_names_cache.json 2>nul
del popup_*.json 2>nul

echo.
echo ========================================
echo   Data supprimee avec succes !
echo ========================================
echo Vous pouvez relancer l'app proprement.
echo.
pause
