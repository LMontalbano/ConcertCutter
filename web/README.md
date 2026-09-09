# Frontend development

English · [Français](README.fr.md)

The interface uses Svelte, TypeScript and Vite. It is built into
`../concertcutter/web/static/`, then served by the Python server and bundled by
PyInstaller.

For the overall architecture, tests and publishing process, see the
[development guide](../docs/development.md).

## Install and build

From `web/`:

```powershell
npm ci
npm run check
npm run build
```

`build_exe.bat` runs `npm ci` and `npm run build` again before PyInstaller.

## Development with Vite

First start the Python server from the repository root:

```powershell
python gui.py --headless --port 8722 test/faux_concert.wav
```

Then start Vite from `web/`:

```powershell
npm run dev
```

Open the address shown by Vite. Requests to `/api` are proxied to
`http://127.0.0.1:8722`.

The Python server protects the API with a token injected into the
`<meta name="cc-token">` tag. In Vite mode, `index.html` is served directly and
keeps the `__CC_TOKEN__` placeholder: temporarily replace it with the token
shown by the headless server, then restore the placeholder before committing.

## Checks

```powershell
npm test
npm run check
npm run build
```

Run the end-to-end HTTP check from the repository root with:

```powershell
python tools/check_all.py
```

It checks the token, WAV range requests, edits, saving and project recovery,
among other behavior.

## Structure

| Location | Role |
|---|---|
| `src/lib/api.ts` | HTTP client and types exchanged with Python |
| `src/lib/session.svelte.ts` | Display state, playback, zoom and navigation |
| `src/lib/wave.ts` | Waveform rendering on canvas |
| `src/components/` | Welcome screen, tracks, editing, transport, options and export |
| `src/tokens.css` | Shared colors, dimensions and themes |
| `public/` | Bundled fonts and favicon |

Persistent project state, editing rules and exports remain on the Python side.
The frontend requests operations; it does not reimplement those rules.
