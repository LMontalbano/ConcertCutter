# Command-line reference

English · [Français](ligne-de-commande.md)

The CLI is intended for batch processing, manual correction of JSON files and
advanced checks. The graphical interface remains the recommended workflow for
interactive work.

## Installation

From the repository root:

```powershell
python -m pip install -r requirements.txt
python -m concertcutter --help
```

The documented audio inputs are WAV files. Audio outputs are WAV files. MP4
export requires ffmpeg.

## Common workflows

Analyze and export in one step:

```powershell
python -m concertcutter run concert.wav -d output --expected-tracks 24
```

Run analysis and rendering separately so you can edit the JSON in between:

```powershell
python -m concertcutter analyze concert.wav
python -m concertcutter render concert.segments.json -d output
```

Add track titles from a text file:

```powershell
python -m concertcutter run concert.wav -d output --tracklist titles.txt
```

The track list contains one title per line. Empty lines and lines beginning
with `#` are ignored. A mismatch between the number of titles and detected
tracks produces a warning.

## `analyze`

```text
python -m concertcutter analyze [options] concert.wav
```

By default, the command writes these files next to the source:

- `concert.segments.json`, the segmentation that can be reopened by `render`
  and the graphical interface;
- `concert.labels.txt`, markers that can be imported into Audacity.

| Option | Default | Effect |
|---|---:|---|
| `--cache FILE` | — | Read or write a `.npz` feature cache |
| `--method hmm\|energy` | `hmm` | Adaptive HMM detector, or the older energy threshold for comparison |
| `--frame S` | `0.25` | Analysis resolution in seconds |
| `--smooth S` | `0.75` with HMM, `2.0` with energy | Level smoothing before classification |
| `--min-gap S` | `6` | Minimum duration of a section to remove |
| `--min-song S` | `75` | Minimum track duration |
| `--stay-prob P` | `0.999` | Persistence of HMM states |
| `--refine-window S` | `2.5` | Window used to refine HMM boundaries |
| `--expected-tracks N` | — | Merge the least convincing gaps until the requested count is reached |
| `--drop-db DB` | `14` | Distance below the reference level for the `energy` method |
| `--hysteresis-db DB` | `4` | Margin for returning to music with the `energy` method |
| `-o`, `--segments FILE` | `<input>.segments.json` | Path of the generated JSON file |
| `--labels FILE` | `<input>.labels.txt` | Path of the Audacity labels file |

`--expected-tracks` can reduce an excessive number of tracks by merging gaps.
It cannot create a boundary when a segue without a level drop was not detected.

## `render`

```text
python -m concertcutter render [options] concert.segments.json
```

The command reopens the source WAV referenced by the JSON file, then creates a
subfolder named after the concert in the location given with `-d`.

| Option | Default | Effect |
|---|---:|---|
| `-d`, `--out-dir FOLDER` | `sortie` | Location that receives the concert folder |
| `--tracklist FILE` | titles from the JSON | One title per line |
| `--fade-ms MS` | `40` | Anti-click fades at track boundaries |
| `--crossfade S` | `0` | Crossfade between tracks in the continuous WAV |
| `--video-crossfade S` | value of `--crossfade` | Separate crossfade for the full-length video |
| `--pad-start S` | `0.5` | Lead-in retained before each track |
| `--pad-end S` | `0.6` | Tail retained after each track |
| `--video-image IMAGE` | — | Create MP4 files with this background image |
| `--video pistes\|album\|les-deux` | `pistes` | Select videos produced with `--video-image` |
| `--no-wav` | false | Produce only MP4 files |
| `--only N[,N...]` | all | Limit the export, for example `1,4,7` or `3-9` |
| `--overwrite` | false | Replace files from a previous export |

`--only` preserves the original track numbers: an export limited to track 7
produces a filename beginning with `07`.

The CLI accepts a single background image. Slideshows and one-image-per-track
mode are available in the graphical interface. The literal values accepted by
`--video` remain French because they are part of the existing CLI contract.

Without `--overwrite`, an existing export causes an error before anything is
written. The command then suggests another location or the explicit use of
`--overwrite`.

## `run`

```text
python -m concertcutter run [options] concert.wav
```

`run` executes `analyze` followed by `render`. It accepts all the detection and
rendering options described above. The JSON file and labels are written next to
the source, then exported files are written under `sortie/` or the folder given
with `-d`.

## `verify`

```text
python -m concertcutter verify [options] concert.segments.json
```

The command creates short WAV files around the boundaries. A beep marks the
exact time of each proposed cut.

| Option | Default | Effect |
|---|---:|---|
| `-d`, `--out-dir FOLDER` | `verification` | Folder for the excerpts |
| `--context S` | `6` | Duration retained before and after the boundary |
| `--no-beep` | false | Do not add the beep |
| `--max-confidence C` | `1.0` | Keep only boundaries below this confidence |
| `--at T[,T...]` | — | Check specified times instead of detected boundaries |

Examples:

```powershell
python -m concertcutter verify concert.segments.json --max-confidence 0.70
python -m concertcutter verify concert.segments.json --at 27:14,36:10
```

With the default context, each excerpt can be up to twelve seconds long. The
formats `12:34`, `1:02:14` and `93.5` are accepted by `--at`.

## `segues`

```text
python -m concertcutter segues [options] concert.segments.json
```

This command searches within already detected tracks for harmonic changes that
may indicate a segue without silence. Its result is a ranked list to review by
ear, not an automatic correction.

| Option | Default | Effect |
|---|---:|---|
| `--cache FILE` | — | Read or write the `.npz` spectral feature cache |
| `--kernel S` | `12` | Context compared on either side of a time |
| `--threshold V` | `0.45` | Minimum height of a novelty peak |
| `--with-rhythm` | false | Also require a rhythm change |
| `--top N` | `5` | Number of candidates retained; `0` keeps all of them |
| `--apply JSON` | — | Write a new segmentation with the candidates applied |

Start without `--apply`, listen to the suggested times with `verify --at`, then
optionally write a new JSON file instead of replacing the original:

```powershell
python -m concertcutter segues concert.segments.json --cache concert-features.npz
python -m concertcutter verify concert.segments.json --at 36:10
python -m concertcutter segues concert.segments.json --apply concert-reviewed.segments.json
```

`--with-rhythm` is disabled by default because it improves precision at the
cost of missing some real segues.

## Output tree

Depending on the selected options:

```text
sortie/
└── concert/
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

`concert_clean.cue` is written only when the continuous album WAV is requested.
Markers, segmentation and the manifest are written for every export.

To inspect the values supported by the installed version:

```powershell
python -m concertcutter analyze --help
python -m concertcutter render --help
python -m concertcutter verify --help
python -m concertcutter segues --help
```
