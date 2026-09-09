# User guide

[Français](guide-utilisateur.md) · English

This guide describes the ConcertCutter graphical interface. To make your first
export without exploring every option, start with the
[README](../README.en.md#first-export).

## Choose your language

Open **Options** from the welcome screen or the concert toolbar. Under
**Language**, choose **Automatic (Windows)**, **Français** or **English**, then
click **Save options**. The change takes effect immediately and preserves your
open project. **Cancel** keeps the previous language.

Automatic is the default: a French Windows display language selects French;
any other language, or failed detection, selects English. Windows is checked at
each launch. A manual choice overrides detection and persists for all projects
in `%LOCALAPPDATA%\ConcertCutter\preferences.json`.

Changing language does not rename tracks or exported files. Native dialog buttons
are translated by Windows itself. Technical details reported by external tools
may appear in their original language beneath a translated error message.

## Open or resume a concert

The welcome screen offers three ways to start:

- **Open a WAV recording** opens the native file picker.
- **Resume a project…** opens a ConcertCutter project or an exported `segments.json`.
- **Recent projects** immediately reopens a saved analysis.

The recording is not uploaded. Once it is open, the overview waveform appears
and you can listen before running analysis.

Click **Analyze** to detect tracks and sections to remove. Adjust detection
settings in **Options & Settings**:

| Setting | Initial value | Effect |
|---|---:|---|
| Minimum silence | 6 s | Shorter gaps remain within the track |
| Minimum track | 75 s | Shorter passages are not considered tracks |
| Expected tracks | 0 | Zero lets detection choose the number of tracks |
| Lead-in | 0.5 s | Audio kept before each exported track |
| Tail | 0.6 s | Audio kept after each exported track |
| Anti-click fades | 40 ms | Very short fades at track edges |

Run analysis again after changing the first three settings. Editing settings
apply to the next export.

## Understand the workspace

The **concert overview** shows the entire recording. Clicking it positions the
playhead and moves the detailed view around that moment.

**Tracks & Segments** lists the numbered tracks you are keeping, with any titles,
and the automatically detected gaps or applause marked **To remove**.

Click a row to select it. The editing card shows the segment, its two boundaries,
duration, confidence and current action.

Adjacent segments of the same type stay separate in the editor, but contiguous
kept segments form a single track at export. Original track numbers remain
stable when other tracks are removed or excluded from a partial export.

## Listen and navigate

| Action | Result |
|---|---|
| Play button or `Space` | Play or pause at the playhead |
| Click or drag inside the detailed waveform | Move the playhead without starting playback |
| A row's `▶` button | Select and play that segment from its start |
| Click the overview | Position the playhead and recenter the detailed view |
| Mouse wheel over the waveform | Zoom around the pointer |
| `←` / `→` | Previous or next boundary |
| `Home` | Start of the section; repeat to return to the previous section |
| `B` | Loop the segment under the playhead |
| `Escape` | Stop playback |

The detailed view follows playback until you position it manually. After clicking
inside that view, it stays fixed so you can adjust a cut without losing the passage.

Listening to the orange margins keeps the selected segment and its two boundaries.
Select a neighboring section in the list or overview to edit it.

## Adjust segments

### Move a boundary

A boundary is shared by the two segments it separates. Moving the first segment's
end also moves the next segment's start.

You can drag the boundary anywhere along its height or by a handle, enter a time
in **Section start** or **Section end**, or use `−` and `+` to move it by 0.5 seconds.

Times such as `12:34`, `1:02:14` and `754` are accepted. Decimal times accept both
a comma and a period, including `754,5` and `754.5`. An invalid value is rejected
and the existing boundary is kept.

The pointer becomes a hand over the playhead and a horizontal double arrow over
a boundary. When the lines overlap, grab the middle to move playback, or a top
or bottom handle to move the boundary.

### Keep or remove

**Keep** and **Remove** change the selected segment's action. The list also has
a **Keep** button to restore a section marked for removal.

This does not immediately delete audio: it changes the segmentation used for
the next export and can be undone.

### Split or merge

- **Split here** or `C` adds a boundary at the playhead. Both halves keep the original type.
- `Shift+C` splits a track into two tracks by inserting the necessary gap.
- **Merge** or `Delete` removes the selected segment's end boundary.

### Name tracks

Click the title in the editing card, or double-click it in the list. `Enter`
confirms the title and `Escape` cancels.

Untitled tracks retain the existing export names `Piste 01`, `Piste 02`, etc.,
regardless of interface language. Sections to remove cannot be named. Titles
remain attached to tracks when their boundaries change.

### Undo

The toolbar buttons, `Ctrl+Z` and `Ctrl+Y` undo and redo the last fifty editing
states. Running a new analysis resets the history.

## Save and resume

The project saves automatically about two seconds after an edit and when the
application closes. It preserves segmentation, titles, analysis and editing
settings, and the last export's track selection, destination and images.

The four output-format checkboxes are deliberately not remembered; choose them
for each export.

Recent projects are stored in ConcertCutter's user data. If the WAV recording
has moved, the application asks you to locate it instead of analyzing again.

## Export

The export dialog has three steps.

### 1. Choose tracks

All tracks are selected for the first export. Later exports restore your last
saved selection. Change it manually or use **Select all** and **Deselect all**.

Selection does not change the concert or its track numbers. Exporting only
track 7 still produces a filename beginning with `07`.

### 2. Choose files

None of the four outputs is selected automatically:

- **The concert in one file** produces `audio/concert_clean.wav` and its cue sheet.
- **One file per track** produces a numbered WAV for each track.
- **One MP4 of the entire concert** produces a video whose title follows the current track.
- **One MP4 per track** produces a titled video for each track.

The full-concert WAV and video each have their own **Crossfade** setting. These
settings do not affect individual track files. At zero, tracks play back to back.

### Video images

MP4 output requires at least one image. The picker supports JPEG, PNG, BMP and
WebP. Reorder images by dragging or with the left and right arrow keys while a
thumbnail has keyboard focus.

By default, images advance in order every eight seconds and repeat. With
**One image per track**, the first image goes to the first selected track, the
second to the next, and so on. If there are too few images, they repeat; if there
are too many, the extras are ignored. The dialog warns about mismatched counts
before exporting.

**Image transition** controls the fade between images. With one image per track,
it applies at track boundaries in the full-concert video; individual track videos
keep a still image.

The image transition starts with the incoming track. If both video crossfade and
image transition are two seconds, they start and end together, provided the
tracks are long enough. A short chapter limits only its own transition.

The track title is overlaid on every video. Images keep their proportions, with
unused space filled in black.

### ffmpeg

Video export requires ffmpeg. If it is missing, the dialog offers **Install ffmpeg**
and shows progress. Downloading starts only after you click that button.

The application also recognizes `ffmpeg.exe` specified by `CONCERTCUTTER_FFMPEG`,
placed next to `ConcertCutter.exe`, installed in user data, or available in `PATH`.

### 3. Choose the destination

Choose a destination. ConcertCutter creates a subfolder named after the source WAV:

```text
<destination>/
└── Concert name/
    ├── audio/
    │   ├── concert_clean.wav
    │   └── 01 - Piste 01.wav
    ├── video/
    │   ├── concert_clean.mp4
    │   └── 01 - Piste 01.mp4
    └── infos/
        ├── concert_clean.cue
        ├── reperes.txt
        ├── segments.json
        └── .concertcutter-export.json
```

Only selected outputs are created. The cue sheet points to
`../audio/concert_clean.wav`. `reperes.txt` contains Audacity markers, and
`segments.json` lets you reopen or inspect the cuts.

### Export again or stop

If an export already exists, you can write alongside it in a suffixed folder,
replace the previous export, or do nothing.

The hidden manifest in `infos/` lets the application replace only files produced
by ConcertCutter. Manually added files are preserved.

You can stop an export from its progress screen. A stopped export preserves the
previous export and cleans up temporary files.

## Troubleshooting and limitations

- **SmartScreen blocks the executable:** check that it came from the official
  GitHub release, then select **More info** and **Run anyway**.
- **The native window does not open:** the application can fall back to your
  default browser. Enter paths manually when native pickers are unavailable.
- **Video is unavailable:** install ffmpeg through the export dialog, or provide
  a build with the `drawtext` filter and an MP4 encoder.
- **Too many cuts need adjustment:** room recordings, phones and tracks without
  a volume drop between them are the hardest cases. Set **Expected tracks** when
  you know the count, then listen to each boundary.
- **A transition is still undetected:** the advanced `segues` command can produce
  a list of moments to listen to without modifying the project by default.

For this command and batch processing, see the
[command-line reference (French)](ligne-de-commande.md).
