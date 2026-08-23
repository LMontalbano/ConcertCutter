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
rem --add-data  : l'interface compilee -- la page, son script, sa feuille de
rem               style et les deux polices -- plus les icones. Ce sont des
rem               donnees, pas des modules : sans cette ligne l'executable
rem               demarre et sert une fenetre vide.
rem
rem L'interface se compile a part, avant : `cd web && npm install && npm run
rem build` depose le resultat dans concertcutter\web\static. Un exe construit
rem sans cette etape embarque la version precedente de l'interface, ou aucune.
rem --icon      : icone de l'executable lui-meme, dans l'explorateur.
rem
rem ffmpeg n'est pas embarque : une centaine de Mo, contre 27 pour tout
rem ConcertCutter, pour une sortie -- la video -- dont on se passe la plupart du
rem temps. L'export video le cherche a cote de l'executable, puis dans le PATH :
rem deposer ffmpeg.exe dans dist\ suffit a l'activer, et son absence grise
rem simplement l'option.
rem
rem libsndfile_x64.dll n'a pas besoin d'etre reclamee : soundfile est un module
rem isole, pas un paquet, et --collect-all n'y trouvait rien -- il se contentait
rem d'afficher deux avertissements. C'est le hook soundfile livre avec
rem PyInstaller qui va chercher la DLL dans _soundfile_data, a cote du module.
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
    --add-data "concertcutter/web/static;concertcutter/web/static" ^
    --add-data "concertcutter/assets;concertcutter/assets" ^
    --icon concertcutter/assets/icon.ico ^
    --exclude-module matplotlib ^
    --exclude-module scipy ^
    --exclude-module PIL ^
    --exclude-module pytest ^
    gui_web.py
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
