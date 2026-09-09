# Development guide

English · [Français](developpement.md)

ConcertCutter combines a Python core with a locally served Svelte interface.
This guide covers setup, development, checks, Windows builds and publishing.

## Requirements

- Python 3.12;
- Node.js 24 and npm for the interface;
- ffmpeg only for testing video export;
- Windows to produce `ConcertCutter.exe` with PyInstaller.

From the repository root:

```powershell
python -m pip install -r requirements.txt
Set-Location web
npm ci
Set-Location ..
```

## Architecture

Audio processing, segmentation, edits, projects and rendering live in
`concertcutter/`.

The Svelte interface lives in `web/`. Vite builds it into
`concertcutter/web/static/`, which is ignored by Git. The Python server:

- serves the interface on `127.0.0.1`;
- injects a launch-specific token into the page;
- exposes session state and editing operations under `/api/`;
- serves the WAV through range requests so it does not have to be loaded into
  memory.

`gui.py` starts this server and then opens a WebView2 window. If the native
window is unavailable, it falls back to the default browser.

Long-running operations—opening, analysis, export and ffmpeg installation—run
as tracked, interruptible jobs rather than inside the HTTP request itself.

## Run the application

Start with a file picker:

```powershell
python gui.py
```

Start with the repository's sample concert:

```powershell
python gui.py test/faux_concert.wav
```

Force the browser mode:

```powershell
python gui.py --browser test/faux_concert.wav
```

Hot-reload development is documented in
[`web/README.md`](../web/README.md).

## Checks

The automated entry point is:

```powershell
python tools/check_all.py
```

It runs, in order:

1. syntax compilation for `concertcutter/`, `tools/` and `tests/`;
2. Python regression tests;
3. an end-to-end HTTP check using a temporarily generated concert;
4. frontend selection and playback tests with `npm test`;
5. `svelte-check`;
6. the Vite build.

The script configures `PYTHONPATH` for the tools itself. It works from
PowerShell, `cmd` and Unix shells as long as Python and npm are available.

Video checks are separate because they require ffmpeg and create larger files.
The smaller fade-synchronization tests are part of the regression suite and run
when ffmpeg is available. To check MP4 export with the sample concert:

```powershell
$env:PYTHONPATH = "."
python tools/check_video_export.py test/faux_concert.segments.json test/sortie-video
```

To run a single unit test:

```powershell
python -m unittest tests.test_regressions.ExportTests -v
```

## Build the Windows executable

```powershell
.\build_exe.bat
```

The script:

1. runs `npm ci` and then `npm run build` in `web/`;
2. checks that the compiled interface is present;
3. installs PyInstaller if necessary;
4. produces a self-contained executable at `dist/ConcertCutter.exe`.

The build bundles Python, audio dependencies, the compiled interface, fonts
and icons. ffmpeg is not bundled.

`build/`, `dist/` and `concertcutter/web/static/` are ignored build artifacts.
They can be regenerated from source.

## Continuous integration

The checks workflow runs on Windows for every push and pull request. It
installs Python and Node, then calls `python tools/check_all.py`.

The publishing workflow has two triggers:

- a `v*` tag builds the executable and creates a GitHub release;
- a manual run builds the same executable as an artifact without creating a
  release.

## Publish a version

Update and review the version numbers and release notes before creating the
tag. Once the main branch has passed its checks:

```powershell
git tag v3.2
git push origin v3.2
```

The workflow rebuilds the application on Windows, checks that the executable
has a plausible size, attaches it to the release and generates notes from
GitHub. The attachment remains named `ConcertCutter.exe`, which keeps the
`releases/latest/download/ConcertCutter.exe` link used by the README stable.

Local scripts do not create the tag automatically: publishing remains an
explicit decision.

## Useful conventions

- Segmentation changes go through `concertcutter/edits.py` so the HTTP
  interface and direct calls share the same rules.
- Project state belongs to the Python server; the frontend stores only display
  state.
- Exported files are written to a temporary folder and replace the destination
  only after a successful export.
- Every new output must be added to the export manifest to keep re-exporting
  safe.
- Frontend changes must pass `npm run check` and `npm run build` before the
  PyInstaller build.

The detailed frontend file map is maintained in
[`web/README.md`](../web/README.md#structure).
