# ConcertCutter

English · [Français](README.fr.md)

ConcertCutter automatically splits a recorded concert into tracks. It detects
sections to remove—applause, talking and tuning—then lets you adjust every cut
before exporting WAV or MP4 files.

Analysis and files stay on your computer. The interface uses a protected local
server accessible only from your machine.

## Download

**[Download ConcertCutter.exe](https://github.com/LMontalbano/ConcertCutter/releases/latest/download/ConcertCutter.exe)**
for Windows 10 or 11.

The executable is self-contained: put it wherever you like and double-click it.
It does not install Python or system dependencies. To remove it, delete the file.

Windows SmartScreen may warn you when you first run an unsigned version. Select
**More info**, then **Run anyway**, if the file came from the link above.

## Language

Open **Options** from the welcome screen or the concert toolbar, then select
**Automatic (Windows)**, **Français** or **English** and click **Save options**.
The interface changes immediately without restarting or losing your work.
**Cancel** keeps the previous language.

Automatic is the default. It uses French when your Windows display language is
French, and English for all other languages or if detection fails. A manual
choice takes priority and is remembered across launches, independently of your
projects. Returning to Automatic uses the Windows language detected at startup.

Your preference is stored in `%LOCALAPPDATA%\ConcertCutter\preferences.json`.
Track titles and exported filenames are preserved when switching languages.
Native Windows dialog buttons follow Windows settings.

## Updates

The Windows executable checks for new stable releases at launch without
delaying the interface. When a version is available, a banner can download it,
verify its SHA-256 checksum and restart ConcertCutter on the current project.
Automatic checks can be disabled or run manually from **Options**.

## First export

1. Click **Open a WAV recording** and choose your concert.
2. Click **Analyze**. Tracks appear in the list on the left, with the selected
   segment in the editing card.
3. Listen to transitions, move boundaries as needed and name your tracks.
4. Click **Export**, select the tracks, output formats and destination.

No output format is selected in advance. Explicitly choose the concert in one
file, individual tracks, their video equivalents, or any combination.

## Adjust the cuts

- Select a track or a section to remove from the list on the left.
- Click the detailed waveform to position the playhead.
- Drag a boundary handle, enter an exact time, or use `−` and `+` in 0.5-second steps.
- Use **Keep** or **Remove** to change what happens to the segment.
- Use **Split here** to add a boundary and **Merge** to remove the selected
  segment's end boundary.
- Click the title in the editing card, or double-click it in the list, to rename it.

Undo changes with `Ctrl+Z` and redo them with `Ctrl+Y`.

| Shortcut | Action |
|---|---|
| `Space` | Play or pause |
| `←` / `→` | Previous or next boundary |
| `Home` | Start of the current section, then the previous section |
| `B` | Loop the segment under the playhead |
| `C` | Split at the playhead |
| `Shift+C` | Split a track into two tracks |
| `Delete` | Merge at the selected boundary |
| `Escape` | Stop playback |

Your work is saved automatically after analysis and edits. The welcome screen
lets you resume a recent project without analyzing it again.

The [user guide](docs/user-guide.en.md) covers playback, editing, resuming projects
and every export option.

## Output files

ConcertCutter creates a folder named after the recording in your chosen destination:

```text
Concert Antidote/
├── audio/
│   ├── concert_clean.wav
│   ├── 01 - Ouverture.wav
│   └── 02 - Le Long Chemin.wav
├── video/
│   ├── concert_clean.mp4
│   ├── 01 - Ouverture.mp4
│   └── 02 - Le Long Chemin.mp4
└── infos/
    ├── concert_clean.cue
    ├── reperes.txt
    └── segments.json
```

Only the requested files are written. Video requires at least one background
image and **ffmpeg**. If ffmpeg is missing, the export dialog offers to install
it. These downloads, like an application update, start only after you click.

An existing export is never overwritten silently. The application offers to
write alongside it, replace the previous export or cancel. Files you added to
the folder manually are preserved.

## Known limitations

- The graphical interface accepts WAV recordings.
- Detection works best when music is noticeably louder than audience sounds.
  Room or phone recordings usually need more manual adjustment.
- Two tracks with no drop in volume between them cannot be automatically
  separated by the interface.
- The expected track count helps merge false cuts, but cannot invent a missing boundary.
- Speech over music may remain in the track.

## Command line

For batch processing and advanced controls:

```powershell
python -m pip install -r requirements.txt
python -m concertcutter run concert.wav -d output --expected-tracks 24
```

The `analyze`, `render`, `run`, `verify` and `segues` commands, their options and
their outputs are documented in the [command-line reference](docs/command-line.md).

## Development

The core uses Python. The compiled Svelte interface is served locally by the
Python application and displayed in a WebView2 window, with a fallback to the
default browser.

```powershell
python -m pip install -r requirements.txt
python gui.py test/faux_concert.wav
python tools/check_all.py
```

See the [development guide](docs/development.md) for setup, Vite, tests,
executable builds and releases.

## Documentation

- [User guide](docs/user-guide.en.md)
- [Command-line reference](docs/command-line.md)
- [Development guide](docs/development.md)
- [Frontend development](web/README.md)

## License

[MIT](LICENSE). ffmpeg, when installed through the application, remains distributed
by its authors under its own terms.
