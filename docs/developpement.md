# Guide de développement

ConcertCutter associe un cœur Python à une interface Svelte servie localement.
Ce guide couvre l'installation, le développement, les contrôles, la
construction Windows et la publication.

## Prérequis

- Python 3.12 ;
- Node.js 24 et npm pour l'interface ;
- ffmpeg uniquement pour tester l'export vidéo ;
- Windows pour produire `ConcertCutter.exe` avec PyInstaller.

Depuis la racine du dépôt :

```powershell
python -m pip install -r requirements.txt
Set-Location web
npm ci
Set-Location ..
```

## Architecture

Le traitement audio, la segmentation, les éditions, les projets et le rendu
vivent dans `concertcutter/`.

L'interface Svelte vit dans `web/`. Vite la compile dans
`concertcutter/web/static/`, dossier ignoré par git. Le serveur Python :

- sert cette interface sur `127.0.0.1` ;
- injecte un jeton propre au lancement dans la page ;
- expose l'état de la session et les opérations d'édition sous `/api/` ;
- sert le WAV par requêtes partielles pour ne pas le charger en mémoire.

`gui.py` démarre ce serveur puis ouvre une fenêtre WebView2. Si la fenêtre
native est indisponible, le navigateur par défaut prend le relais.

Les traitements longs — ouverture, analyse, export et installation de ffmpeg —
sont exécutés comme des tâches suivies et interruptibles plutôt que dans la
requête HTTP elle-même.

## Lancer l'application

Avec un sélecteur de fichier au démarrage :

```powershell
python gui.py
```

Avec le faux concert du dépôt :

```powershell
python gui.py test/faux_concert.wav
```

Pour forcer le navigateur :

```powershell
python gui.py --browser test/faux_concert.wav
```

Le mode de développement avec rechargement à chaud est décrit dans
[`web/README.md`](../web/README.md).

## Vérifications

Le point d'entrée automatisé est :

```powershell
python tools/check_all.py
```

Il exécute successivement :

1. la compilation syntaxique de `concertcutter/`, `tools/` et `tests/` ;
2. les tests de régression Python ;
3. le contrôle HTTP de bout en bout sur un concert généré temporairement ;
4. `svelte-check` ;
5. la construction Vite.

Le script configure lui-même `PYTHONPATH` pour les outils. Il fonctionne depuis
PowerShell, `cmd` et les shells Unix tant que Python et npm sont disponibles.

Les contrôles vidéo sont séparés car ils demandent ffmpeg et créent des fichiers
plus lourds. Pour vérifier l'export MP4 avec le faux concert :

```powershell
$env:PYTHONPATH = "."
python tools/check_video_export.py test/faux_concert.segments.json test/sortie-video
```

Pour exécuter un test unitaire seul :

```powershell
python -m unittest tests.test_regressions.ExportTests -v
```

## Construire l'exécutable Windows

```powershell
.\build_exe.bat
```

Le script :

1. exécute `npm ci` puis `npm run build` dans `web/` ;
2. vérifie la présence de l'interface compilée ;
3. installe PyInstaller si nécessaire ;
4. produit un exécutable autonome dans `dist/ConcertCutter.exe`.

Le build embarque Python, les dépendances audio, l'interface compilée, les
polices et les icônes. ffmpeg n'est pas embarqué.

`build/`, `dist/` et `concertcutter/web/static/` sont des artefacts ignorés par
git. Ils peuvent être régénérés depuis les sources.

## Intégration continue

Le workflow de vérification s'exécute sous Windows à chaque push et pull
request. Il installe Python et Node puis appelle `python tools/check_all.py`.

Le workflow de publication répond à deux déclencheurs :

- un tag `v*` construit l'exécutable et crée une release GitHub ;
- un lancement manuel construit le même exécutable comme artefact, sans créer
  de release.

## Publier une version

La mise à jour des numéros de version et des notes de release doit être faite et
relue avant le tag. Une fois la branche principale vérifiée :

```powershell
git tag v3.0
git push origin v3.0
```

Le workflow reconstruit l'application sur Windows, contrôle que l'exécutable a
une taille plausible, le joint à la release et génère les notes depuis GitHub.
La pièce jointe conserve le nom `ConcertCutter.exe`, ce qui maintient le lien
`releases/latest/download/ConcertCutter.exe` utilisé par le README.

Le tag n'est pas créé automatiquement par les scripts locaux : cette étape
reste une décision de publication explicite.

## Conventions utiles

- Les changements de segmentation passent par `concertcutter/edits.py`, afin
  que l'interface HTTP et les appels directs partagent les mêmes règles.
- L'état du projet appartient au serveur Python ; le frontend ne conserve que
  l'état d'affichage.
- Les fichiers exportés sont écrits dans un dossier provisoire puis remplacent
  la destination seulement après réussite.
- Toute nouvelle sortie doit être ajoutée au manifeste d'export pour préserver
  la sécurité du réexport.
- Une modification du frontend doit être validée par `npm run check` et
  `npm run build` avant la construction PyInstaller.

La carte détaillée des fichiers frontend est maintenue dans
[`web/README.md`](../web/README.md#organisation).
