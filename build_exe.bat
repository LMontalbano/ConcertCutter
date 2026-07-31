@echo off
setlocal

rem Construit ConcertCutter.exe : un executable autonome, qui embarque Python,
rem numpy, soundfile et sa DLL libsndfile. La machine cible n'a donc besoin de
rem rien d'installe.
rem
rem --onefile   : un seul fichier a transmettre. Le demarrage prend quelques
rem               secondes de plus qu'en --onedir, le temps de se decompresser
rem               dans un dossier temporaire ; a l'echelle d'un concert de deux
rem               heures a analyser, c'est negligeable.
rem --windowed  : pas de fenetre noire derriere l'interface.
rem --collect-all soundfile : libsndfile_x64.dll vit dans un sous-dossier de
rem               donnees du paquet, que la detection automatique rate.
rem --add-data  : les images de l'interface (fonds de boutons, icones, logo).
rem               Ce sont des donnees, pas des modules : sans cette ligne
rem               l'executable demarre mais sans icone ni boutons arrondis.
rem --icon      : icone de l'executable lui-meme, dans l'explorateur.
rem
rem Ces reglages vivent ici et non dans ConcertCutter.spec : --noconfirm
rem reecrit le .spec a chaque construction, et il est de toute facon ignore
rem par git. Tout ce qu'on y ecrirait a la main serait perdu.

cd /d "%~dp0"

echo.
echo === Verification de PyInstaller ===
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller absent, installation...
    python -m pip install pyinstaller
    if errorlevel 1 goto echec
)

echo.
echo === Construction ===
python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name ConcertCutter ^
    --collect-all soundfile ^
    --add-data "concertcutter/ui/assets;concertcutter/ui/assets" ^
    --icon concertcutter/ui/assets/icon.ico ^
    --exclude-module matplotlib ^
    --exclude-module scipy ^
    --exclude-module PIL ^
    --exclude-module pytest ^
    gui.py
if errorlevel 1 goto echec

echo.
echo === Termine ===
echo Executable : %cd%\dist\ConcertCutter.exe
for %%F in ("dist\ConcertCutter.exe") do echo Taille     : %%~zF octets
echo.
echo Ce fichier se suffit a lui-meme : il peut etre copie sur une autre
echo machine Windows, sans Python ni aucune bibliotheque.
goto fin

:echec
echo.
echo La construction a echoue. Voir les messages ci-dessus.
exit /b 1

:fin
endlocal
