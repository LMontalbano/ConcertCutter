# Référence en ligne de commande

[English](command-line.md) · Français

La CLI sert au traitement par lot, à la correction manuelle de fichiers JSON et
aux contrôles avancés. L'interface graphique reste le parcours recommandé pour
un travail interactif.

## Installation

Depuis la racine du dépôt :

```powershell
python -m pip install -r requirements.txt
python -m concertcutter --help
```

Les entrées audio documentées sont des fichiers WAV. Les sorties audio sont des
WAV. L'export MP4 demande ffmpeg.

## Parcours courants

Analyser et exporter en une passe :

```powershell
python -m concertcutter run concert.wav -d sortie --expected-tracks 24
```

Séparer l'analyse du rendu pour corriger le JSON entre les deux :

```powershell
python -m concertcutter analyze concert.wav
python -m concertcutter render concert.segments.json -d sortie
```

Ajouter des titres depuis un fichier texte :

```powershell
python -m concertcutter run concert.wav -d sortie --tracklist titres.txt
```

La tracklist contient un titre par ligne. Les lignes vides et celles qui
commencent par `#` sont ignorées. Un écart entre le nombre de titres et le
nombre de morceaux produit un avertissement.

## `analyze`

```text
python -m concertcutter analyze [options] concert.wav
```

La commande écrit par défaut, à côté de la source :

- `concert.segments.json`, la segmentation relisible par `render` et
  l'interface ;
- `concert.labels.txt`, les repères à importer dans Audacity.

| Option | Défaut | Effet |
|---|---:|---|
| `--cache FICHIER` | — | Relire ou écrire un cache `.npz` de descripteurs |
| `--method hmm\|energy` | `hmm` | Détecteur adaptatif HMM, ou ancien seuil d'énergie pour comparaison |
| `--frame S` | `0.25` | Résolution de l'analyse en secondes |
| `--smooth S` | `0.75` en HMM, `2.0` en energy | Lissage du niveau avant décision |
| `--min-gap S` | `6` | Durée minimale d'une zone à retirer |
| `--min-song S` | `75` | Durée minimale d'un morceau |
| `--stay-prob P` | `0.999` | Persistance des états du HMM |
| `--refine-window S` | `2.5` | Fenêtre de recalage des frontières HMM |
| `--expected-tracks N` | — | Fusionner les blancs les moins convaincants jusqu'au compte demandé |
| `--drop-db DB` | `14` | Écart sous la référence pour la méthode `energy` |
| `--hysteresis-db DB` | `4` | Marge de retour en musique pour la méthode `energy` |
| `-o`, `--segments FICHIER` | `<entrée>.segments.json` | Chemin du JSON produit |
| `--labels FICHIER` | `<entrée>.labels.txt` | Chemin des labels Audacity |

`--expected-tracks` peut réduire un excès de morceaux en fusionnant des blancs.
Il ne crée pas une frontière lorsqu'un enchaînement sans baisse de niveau n'a
pas été détecté.

## `render`

```text
python -m concertcutter render [options] concert.segments.json
```

La commande relit la source WAV indiquée dans le JSON, puis crée un sous-dossier
portant le nom du concert dans l'emplacement donné par `-d`.

| Option | Défaut | Effet |
|---|---:|---|
| `-d`, `--out-dir DOSSIER` | `sortie` | Emplacement qui recevra le dossier du concert |
| `--tracklist FICHIER` | titres du JSON | Un titre par ligne |
| `--fade-ms MS` | `40` | Fondus anti-clic aux extrémités des pistes |
| `--crossfade S` | `0` | Fondu entre morceaux du WAV continu |
| `--video-crossfade S` | valeur de `--crossfade` | Fondu propre à la vidéo complète |
| `--pad-start S` | `0.5` | Amorce conservée avant chaque morceau |
| `--pad-end S` | `0.6` | Queue conservée après chaque morceau |
| `--video-image IMAGE` | — | Créer des MP4 avec cette image de fond |
| `--video pistes\|album\|les-deux` | `pistes` | Choisir les vidéos produites avec `--video-image` |
| `--no-wav` | faux | Produire uniquement les MP4 |
| `--only N[,N...]` | tous | Limiter l'export, par exemple `1,4,7` ou `3-9` |
| `--overwrite` | faux | Remplacer les fichiers d'un export précédent |

`--only` conserve les numéros originaux : un export limité à la piste 7 produit
un nom commençant par `07`.

La CLI accepte une seule image de fond. Le diaporama à plusieurs images et le
mode une image par morceau sont disponibles dans l'interface graphique.

Sans `--overwrite`, un export existant provoque une erreur avant toute écriture.
La commande suggère alors un autre emplacement ou l'utilisation explicite de
`--overwrite`.

## `run`

```text
python -m concertcutter run [options] concert.wav
```

`run` enchaîne `analyze` puis `render`. Il accepte toutes les options de
détection et de rendu présentées ci-dessus. Le JSON et les labels sont écrits à
côté de la source, puis les fichiers exportés sous `sortie/` ou sous le dossier
indiqué par `-d`.

## `verify`

```text
python -m concertcutter verify [options] concert.segments.json
```

La commande produit de courts WAV autour des frontières. Un bip marque
l'instant exact de la coupe proposée.

| Option | Défaut | Effet |
|---|---:|---|
| `-d`, `--out-dir DOSSIER` | `verification` | Dossier des extraits |
| `--context S` | `6` | Durée conservée avant et après la frontière |
| `--no-beep` | faux | Ne pas ajouter le bip |
| `--max-confidence C` | `1.0` | Garder uniquement les frontières sous cette confiance |
| `--at T[,T...]` | — | Vérifier des instants imposés plutôt que les frontières |

Exemples :

```powershell
python -m concertcutter verify concert.segments.json --max-confidence 0.70
python -m concertcutter verify concert.segments.json --at 27:14,36:10
```

Avec le contexte par défaut, chaque extrait peut durer jusqu'à douze secondes.
Les formats `12:34`, `1:02:14` et `93.5` sont acceptés par `--at`.

## `segues`

```text
python -m concertcutter segues [options] concert.segments.json
```

Cette commande cherche, à l'intérieur des morceaux déjà détectés, des
changements harmoniques qui pourraient signaler un enchaînement sans blanc. Le
résultat est une liste classée à écouter, pas une correction automatique.

| Option | Défaut | Effet |
|---|---:|---|
| `--cache FICHIER` | — | Relire ou écrire les descripteurs spectraux `.npz` |
| `--kernel S` | `12` | Contexte comparé de part et d'autre d'un instant |
| `--threshold V` | `0.45` | Hauteur minimale d'un pic de nouveauté |
| `--with-rhythm` | faux | Exiger également un changement de rythme |
| `--top N` | `5` | Nombre de candidats retenus ; `0` les conserve tous |
| `--apply JSON` | — | Écrire une nouvelle segmentation avec les candidats appliqués |

Commencez sans `--apply`, écoutez les instants proposés avec `verify --at`, puis
écrivez éventuellement un nouveau JSON au lieu de remplacer l'original :

```powershell
python -m concertcutter segues concert.segments.json --cache concert-features.npz
python -m concertcutter verify concert.segments.json --at 36:10
python -m concertcutter segues concert.segments.json --apply concert-revu.segments.json
```

`--with-rhythm` est désactivé par défaut car il augmente la précision au prix
d'une perte de vrais enchaînements.

## Arborescence de sortie

Selon les options choisies :

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

`concert_clean.cue` n'est écrit que si l'album WAV continu est demandé. Les
repères, la segmentation et le manifeste sont écrits pour chaque export.

Pour vérifier les valeurs de la version installée :

```powershell
python -m concertcutter analyze --help
python -m concertcutter render --help
python -m concertcutter verify --help
python -m concertcutter segues --help
```
