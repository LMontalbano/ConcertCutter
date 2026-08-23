# L'interface

Svelte + TypeScript + Vite. Le résultat de la compilation part dans
`../concertcutter/web/static`, que le serveur Python sert et que PyInstaller
embarque — il n'y a pas de dossier `dist` intermédiaire qu'on oublierait de
recopier.

## Compiler

```bash
npm install
npm run build
```

C'est l'étape qui précède `build_exe.bat` : un exécutable construit sans elle
embarque l'interface précédente, ou aucune.

## Travailler dessus

Deux processus. Le serveur Python d'un côté, sur un port fixe :

```bash
python gui_web.py --headless --port 8722 "test/faux_concert.wav"
```

Vite de l'autre, qui sert la page avec rechargement à chaud et renvoie `/api`
vers le premier :

```bash
npm run dev
```

L'adresse à ouvrir est celle de Vite. Le jeton, lui, vient de la page servie
par Python : en développement, `index.html` n'est pas réécrit, donc il faut
l'ajouter à la main dans la balise `<meta name="cc-token">` — celui qu'affiche
le serveur au lancement.

## Vérifier

```bash
npm run check
```

`svelte-check` relit les types à travers les composants. Le contrôle de bout en
bout, lui, est côté Python :

```bash
PYTHONPATH=. python tools/check_web_api.py test/faux_concert.wav
```

## Ce qui est où

| Fichier | Rôle |
|---|---|
| `src/lib/api.ts` | le seul endroit qui parle au serveur |
| `src/lib/session.svelte.ts` | l'état de l'écran — pas celui du travail, qui vit côté Python |
| `src/lib/wave.ts` | le tracé, en canvas impératif |
| `src/lib/format.ts` | horaires : `hms`, `tenths`, et leur relecture |
| `src/components/Ribbon.svelte` | le concert entier, en une bande |
| `src/components/TrackList.svelte` | morceaux et blancs, avec leurs vignettes |
| `src/components/EditCard.svelte` | le segment sous la loupe et ses deux coupes |
| `src/components/ExportDialog.svelte` | les trois questions de l'export |
| `src/tokens.css` | ce qui remplace `ui/theme.py`, `ui/skin.py` et trente PNG |
| `public/fonts/` | Instrument Sans et JetBrains Mono, embarquées |
