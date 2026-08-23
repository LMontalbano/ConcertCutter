# Portage web — plan de travail

Document de référence pour le chantier « ConcertCutter passe du bureau au web ».
Décidé le 22 août 2026. Il se veut suffisant à lui seul : une séance de travail
qui l'ouvre sans rien connaître d'autre doit pouvoir commencer.

---

## 1. Ce qui a été décidé, et ce qui a été écarté

**L'algorithme reste en Python.** Il n'a jamais été le sujet du portage. Le
découpage cœur/interface est déjà propre : aucun module de `concertcutter/`
n'importe tkinter, la dépendance va toujours dans le sens `ui/ → cœur`. Mieux,
[`cli.py`](../concertcutter/cli.py) documente déjà la couture d'un backend —
`analyze` produit un JSON, `render` le consomme, et la séparation est
délibérée pour permettre la correction manuelle entre les deux.

**L'interface web est servie par un backend Python local**, pas par un serveur
distant. L'exécutable lance un petit serveur sur `127.0.0.1` et ouvre une
fenêtre ; aucun fichier ne quitte la machine.

Deux architectures ont été écartées, pour mémoire :

- **Le vrai SaaS, avec envoi du fichier.** Le WAV de test fait 1,997 Go pour
  2 h 05, et les morceaux exportés pèsent autant au retour. Sur une fibre
  grand public, c'est un quart d'heure d'attente avant que la moindre chose
  s'affiche — exactement ce que le README vend comme « la forme d'onde apparaît
  en 5 s, écoutable avant même d'analyser ». S'y ajoutent le stockage, le CPU
  (~1 min de calcul pour 30 min de concert), ffmpeg côté serveur, et la
  question de savoir chez qui vivent les enregistrements non publiés des gens.
- **L'hybride : calculer les descripteurs dans le navigateur et n'envoyer
  qu'eux.** Séduisant sur le papier — `antidote_feats.npz` pèse 4,1 Mo contre
  2 Go de WAV, un rapport de 1 à 500 — mais il faudrait réécrire
  `spectral.extract` en JS, c'est-à-dire dupliquer le seul code dont le
  comportement numérique *définit* le produit. Deux implémentations dérivent
  toujours, et la détection changerait sans qu'on sache pourquoi.

**Le design part de la variante 2a** du canevas « ConcertCutter redesign
moderne », avec l'évolution **A** de la carte d'édition (section 4).

**Le travail se fait sur une branche**, `portage-web`. L'application peut être
cassée entre deux étapes : la référence de non-régression n'est pas l'appli
Tkinter, elle est versionnée (section 6).

---

## 2. Ce que le portage supprime

Une bonne part de l'interface actuelle n'existe que pour compenser Tkinter :

| Module | Lignes | Devient |
|---|---|---|
| `ui/theme.py` + `ui/skin.py` + `ui/assets.py` | 607 | du CSS |
| `ui/card.py`, `ui/collapsible.py`, `ui/tooltip.py`, `ui/seekbar.py` | 475 | `<details>`, `title`, `<input type=range>` |
| `ui/player.py` | 164 | l'élément `<audio>` |

Soit ~1 250 lignes, plus les 30 PNG de `ui/assets/` — ces boutons en quatre
états sont des images parce que Tkinter ne sait pas styler un bouton.

Le cas de [`player.py`](../concertcutter/ui/player.py) mérite d'être signalé :
c'est du MCI Windows piloté par ctypes, et son en-tête dit lui-même « Windows
uniquement ». Le navigateur le remplace **et** rend la lecture portable, à
condition que le serveur local serve le WAV avec les requêtes `Range` — le
navigateur ne lit alors que ce qu'il joue, comme MCI ouvrait 1,86 Go en 0,06 s.

---

## 3. Ce que le design exige du back

C'est le design qui dicte l'API, pas l'inverse. Relevé pour 2a :

| Élément | Ce qu'il faut | État |
|---|---|---|
| Ruban « Le concert », 1196 px | `audio.envelope`, 4 pts/s (30 184 points sur le concert de test, ~120 Ko en Float32) | existe |
| Vignettes 88 × 26 des 25 morceaux | découpées dans la même enveloppe, zéro E/S supplémentaire | existe |
| Zoom à la molette sur le morceau | pics multi-résolution à la demande | à extraire |
| « confiance 95 % » | `Segment.confidence` | existe |
| Steppers au dixième de seconde | opérations d'édition pures | à extraire |
| « Enregistré à l'instant » | `project.py` | existe |
| Transport, lecture | `<audio>` + requêtes `Range` | remplace MCI |

Le zoom est le seul vrai manque, et il est à moitié résolu :
[`ui/waveform.py`](../concertcutter/ui/waveform.py) décrit déjà la bonne
stratégie dans son en-tête — l'enveloppe au-dessus de 90 s de fenêtre, les
échantillons réels relus à la volée en deçà. C'est du portage, pas de
l'invention.

---

## 4. Le design retenu

### 2a, l'écran principal

Ruban du concert entier en haut (cliquer y déplace la loupe), liste des
25 morceaux et 24 blancs à gauche sur 400 px — chaque ligne porte son numéro,
son titre, ses bornes et une vignette de forme d'onde — segment sous la loupe
à droite, transport en bas.

Deux décisions prises en cours de route :

- le **« Filtrer »** de l'en-tête de la colonne de gauche est supprimé ;
- les **réglages de détection** ne figurent pas sur cet écran : ils partent
  dans un écran **Options** à part (lot 5).

### Jetons

Thème **clair uniquement** pour l'instant.

| Rôle | Valeur |
|---|---|
| Fond de l'application | `#F7F8FA` |
| Surfaces | `#FFFFFF` |
| Bordure | `#E9ECF1` — filet interne `#F2F4F7` |
| Texte | `#1B2029` · secondaire `#5B6472` · sourdine `#8A929F` · indication `#A8B0BB` |
| Accent | `#1E7F8C` — fond clair `#E8F3F5` |
| Blancs (applaudissements) | `#B4603A` — fond de ligne `#FCF9F7`, filet `#E2C9B8` |
| Tracé | musique `#1E7F8C` sur `#E8F3F5` · blanc `#CE8B67` sur `#FAEDE6` |
| Poignées | `#1B2029`, 2 px, prises de 11 × 26 en haut et en bas |
| Typographie | Instrument Sans (400/500/600/700), JetBrains Mono (400/500) pour les chiffres et les temps |

Les deux polices viennent de Google Fonts. Une application locale ne peut pas
dépendre du réseau pour son texte : **les embarquer dans l'exécutable**.

### Évolution A de la carte d'édition

Le défaut de 2a : la carte s'appelle « Le morceau entier », donc ses deux
limites tombent exactement sur les bords gauche et droit du tracé. Impossible
de les saisir, et on ne voit jamais ce qu'il y a de l'autre côté de la coupe —
c'est-à-dire les applaudissements, la seule chose qui permette de juger si la
coupe est au bon endroit. En l'état, 2a est une régression sur ce que l'appli
Tkinter sait déjà faire (corriger les frontières à la souris).

**A** élargit la vue de 15 s sur les blancs voisins : les deux poignées
tombent à l'intérieur du tracé, avec la place de les attraper, et le contexte
devient visible. Les steppers au dixième restent comme recours de précision, le
zoom à la molette pour le reste.

S'y ajoute un bouton **« Caler sur l'attaque »**, qui ne demande aucun calcul
nouveau : le détecteur cherche déjà la vraie attaque dans une fenêtre de 2,5 s
autour du bord qu'il propose (`refine_window_s` dans
[`detect_hmm.py`](../concertcutter/detect_hmm.py)). Le bouton rejoue ce calcul
à la demande, sur la limite qu'on vient de déplacer.

Deux variantes ont été écartées et restent consultables si A déçoit à l'usage :
**B**, les deux coupes en gros plan à ± 4 s sans vue d'ensemble ; **C**, A plus
une loupe qui suit la poignée pendant qu'on la déplace.

Canevas des trois : <https://claude.ai/code/artifact/f4f07b7b-a25c-408c-ab68-93dbea14bd80>
Canevas d'origine (2a et les autres directions) : `~/Downloads/ConcertCutter redesign moderne/`

---

## 5. Les six lots

### Lot 1 — le cœur, sans interface

Aucune décision de design ne le bloque ; c'est par là qu'on commence.

- `concertcutter/edits.py` : extraire de [`ui/app.py`](../concertcutter/ui/app.py)
  les opérations sur les segments — `_cut`, `delete_boundary`, `split_here`,
  `split_track`, `_apply_kinds`, `go_boundary`, `go_section_start` — en
  fonctions pures `list[Segment] → list[Segment]`, à côté de
  [`segment.py`](../concertcutter/segment.py).
- `concertcutter/peaks.py` : extraire de `ui/waveform.py` la stratégie à deux
  sources, débarrassée de Tkinter.
- L'appli Tkinter est recâblée par-dessus et continue de tourner : c'est la
  vérification de l'extraction.

### Lot 2 — le serveur

`http.server` de la bibliothèque standard. Le `requirements.txt` tient en deux
lignes (numpy, soundfile) ; FastAPI et uvicorn ajouteraient une quinzaine de
mégaoctets à un exécutable qui en fait 25, pour six routes.

| Route | Rôle |
|---|---|
| `POST /open` | ouvre le dialogue natif **côté Python**, renvoie un chemin |
| `GET /envelope` | l'enveloppe complète, en Float32 binaire |
| `GET /peaks?from&to&width` | les pics de la fenêtre visible |
| `POST /analyze` | lance l'analyse, renvoie un identifiant de travail |
| `POST /edit` · `POST /undo` | une opération d'édition, renvoie le nouvel état |
| `POST /render` | lance l'export |
| `GET /progress` | l'avancement des travaux en cours |
| `GET /audio` | le WAV source, avec `Range` |

Points de vigilance :

- **Le navigateur ne donne pas de chemin de fichier.** Un `<input type=file>`
  fournit un contenu, jamais un `Path` — or tout le cœur prend des `Path`.
  D'où `POST /open` : c'est Python qui ouvre le dialogue.
- **Un serveur local qui ouvre un chemin arbitraire est une primitive de
  lecture de fichiers** pour n'importe quelle page ouverte dans le même
  navigateur. Écoute sur `127.0.0.1`, jeton aléatoire par lancement, vérifié
  sur chaque requête. À faire tout de suite, pas après.
- **Les travaux longs deviennent des jobs**, interrogés toutes les 500 ms.
  Pas de SSE ni de WebSocket : [`render.py`](../concertcutter/render.py) expose
  déjà le `Callable` de progression qu'il faut, il suffit de le déverser dans
  un dictionnaire.

### Lot 3 — la coquille

pywebview sur WebView2, présent d'office sur Windows 10 et 11. Adaptation de
[`ConcertCutter.spec`](../ConcertCutter.spec) pour embarquer le front compilé
et les deux polices. Gérer le port déjà pris et la fermeture propre.

### Lot 4 — l'écran principal

Svelte + TypeScript + Vite. La forme d'onde reste du canvas impératif quoi
qu'il arrive ; le reste est de l'état de formulaire, ce que Svelte fait sans
cérémonie.

Trois canvas : le ruban, les vignettes, le tracé zoomable. Plus le transport,
l'édition du titre en ligne, les steppers, les poignées de l'évolution A.

L'annulation vit **côté serveur** : elle porte sur la liste de segments.

Les raccourcis actuels sont conservés à l'identique, garde-fou compris — ils
sont neutralisés pendant une saisie, faute de quoi taper « c » dans un titre
coupe le morceau :

| Touche | Action |
|---|---|
| `espace` | lecture / pause |
| `c` · `Maj+C` | séparer ici · séparer le morceau |
| `b` | boucler |
| `Suppr` | supprimer la frontière |
| `←` `→` | frontière précédente / suivante |
| `Origine` | début de la section |
| `Échap` | arrêter la lecture |
| `Ctrl+Z` · `Ctrl+Y` · `Ctrl+Maj+Z` | annuler · refaire |

### Lot 5 — les écrans manquants

2a ne couvre que l'écran principal. À **dessiner d'abord** dans la même langue
visuelle, puis à coder :

- l'écran vide, avant import ;
- l'analyse en cours ;
- **l'export** — le plus gros morceau. La fenêtre actuelle fait 942 lignes et
  porte des décisions réfléchies à ne pas perdre en route : trois questions
  numérotées (quels morceaux, sous quelle forme, où), des libellés qui disent
  ce qu'on obtient plutôt que comment ça s'appelle, les fonds vidéo en liste
  plutôt qu'en champ, chaque réglage sous ce qu'il modifie. Lire l'en-tête de
  [`ui/export_dialog.py`](../concertcutter/ui/export_dialog.py) avant de
  redessiner, et `RenderParams` dans `render.py` pour le champ exact des
  options ;
- **Options** — les réglages de détection, sortis de l'écran principal ;
- la reprise de travail (`project.py`, 20 points de reprise) ;
- l'installation de ffmpeg (`ffmpeg_install.py`) ;
- les erreurs.

### Lot 6 — parité, puis nettoyage

Suppression de `concertcutter/ui/` et des PNG. En dernier — non pour garder
l'appli vivante, mais parce que jusqu'au lot 5 elle sert de source à ce qu'on
en extrait. Puis README et captures.

---

## 5 bis. Où en est le chantier

Les lots 1 à 5 sont faits, sur la branche `portage-web`. Ce qui a été appris en
chemin, et qui ne figurait pas au plan :

- **`history.py` a dû quitter `ui/`.** Les deux interfaces s'en servent, et l'y
  laisser obligeait le serveur web à importer Tkinter — donc à l'embarquer dans
  l'exécutable — pour soixante lignes de listes d'instantanés. Les icônes ont
  suivi le même chemin, de `ui/assets/` vers `assets/`.
- **Le port déjà pris était pire que prévu.** Sous Windows, `SO_REUSEADDR` —
  que `HTTPServer` pose par défaut — laisse deux sockets se lier au même port.
  Deux ConcertCutter lancés coup sur coup écoutaient tous les deux, chacun avec
  son jeton, et une requête sur deux tombait chez le mauvais.
- **Les noms de fichiers compilés portent une empreinte.** Sans elle, une
  version suivante sert `app.js` à un navigateur qui garde l'ancien en cache et
  ne le redemande pas : la fenêtre affiche l'interface d'avant, sans rien dire.
- **`detect_hmm.refine_boundary`** ouvre au geste manuel le recalage que le
  détecteur faisait déjà sur chacune de ses frontières. C'est ce qui fait
  fonctionner « Caler sur l'attaque » sans calcul nouveau, comme prévu.

Reste le **lot 6** : la parité se juge à l'usage, sur un vrai concert. Tant
qu'elle n'est pas constatée, `concertcutter/ui/` reste en place — les deux
interfaces partagent le cœur et les fichiers de reprise, donc rien n'oblige à
choisir tout de suite. Après quoi : suppression de `ui/` et de ses PNG,
nouvelles captures, README.

## 6. La règle qui ne bouge pas

**Les résultats de détection ne changent pas d'un octet.** La référence est
déjà versionnée : [`test/antidote_v1.segments.json`](../test/antidote_v1.segments.json)
porte les 50 segments — 25 morceaux, 24 blancs — du concert de 2 h 05. Toute
étape doit pouvoir se conclure en comparant la sortie à ce fichier.

C'est aussi ce qui rend le lot 6 possible : vérifier la détection ne demande
pas de relancer Tkinter.
