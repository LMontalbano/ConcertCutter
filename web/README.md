# Développement du frontend

L'interface utilise Svelte, TypeScript et Vite. Elle est compilée dans
`../concertcutter/web/static/`, puis servie par le serveur Python et embarquée
par PyInstaller.

Pour l'architecture générale, les tests et la publication, consultez le
[guide de développement](../docs/developpement.md).

## Installer et compiler

Depuis `web/` :

```powershell
npm ci
npm run check
npm run build
```

`build_exe.bat` relance lui-même `npm ci` et `npm run build` avant PyInstaller.

## Développement avec Vite

Lancez d'abord le serveur Python depuis la racine du dépôt :

```powershell
python gui.py --headless --port 8722 test/faux_concert.wav
```

Puis Vite depuis `web/` :

```powershell
npm run dev
```

Ouvrez l'adresse affichée par Vite. Les appels `/api` sont redirigés vers
`http://127.0.0.1:8722`.

Le serveur Python protège l'API avec un jeton injecté dans la balise
`<meta name="cc-token">`. En mode Vite, `index.html` est servi directement et
garde le gabarit `__CC_TOKEN__` : remplacez temporairement cette valeur par le
jeton affiché par le serveur headless, puis restaurez le gabarit avant de
committer.

## Contrôles

```powershell
npm run check
npm run build
```

Le contrôle HTTP de bout en bout se lance depuis la racine avec :

```powershell
python tools/check_all.py
```

Il vérifie notamment le jeton, la lecture partielle du WAV, les éditions, la
sauvegarde et la reprise.

## Organisation

| Emplacement | Rôle |
|---|---|
| `src/lib/api.ts` | Client HTTP et types échangés avec Python |
| `src/lib/session.svelte.ts` | État d'affichage, lecture, zoom et navigation |
| `src/lib/wave.ts` | Dessin des formes d'onde sur canvas |
| `src/components/` | Accueil, pistes, édition, transport, options et export |
| `src/tokens.css` | Couleurs, dimensions et thèmes partagés |
| `public/` | Polices et favicon embarquées |

L'état persistant du travail, les règles d'édition et les exports restent côté
Python. Le frontend demande des opérations ; il ne réimplémente pas ces règles.
