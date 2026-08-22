# ConcertCutter

Découpe un concert enregistré en morceaux, en retirant les blancs — discussions
avec le public, applaudissements, accordage.

![L'interface, un concert de 2 h 05 analysé](docs/interface.png)

**État : V3.** Détection par mélange gaussien + Viterbi, aucun seuil réglé à la
main, plus une interface graphique pour corriger les frontières à la souris.
Validé sur un concert réel de 2 h 05 : 25 morceaux sur 25.

### → **[Télécharger ConcertCutter.exe](https://github.com/LMontalbano/ConcertCutter/releases/latest/download/ConcertCutter.exe)** (Windows, environ 25 Mo)

---

**[Prise en main](#prise-en-main)** · **[En ligne de commande](#en-ligne-de-commande)**
· **[Sous le capot](#sous-le-capot)** · **[Développement](#développement)**
· **[Licence](#licence)**

---

# Prise en main

## Installer, c'est-à-dire ne rien installer

Un seul fichier : on le télécharge, on le pose où l'on veut — le bureau fait
très bien l'affaire — et on double-clique. Python, numpy et le reste sont
dedans. Rien n'est inscrit dans Windows, rien n'ajouté au menu Démarrer ; pour
désinstaller, on met le fichier à la corbeille. La seule exception est ffmpeg,
si l'on demande l'export vidéo : il est alors posé à côté de l'exécutable, ou
dans `%LOCALAPPDATA%\ConcertCutter`.

**Windows va afficher un avertissement au premier lancement.** « Windows a
protégé votre ordinateur », avec un seul bouton visible. Ce n'est pas un
antivirus qui aurait trouvé quelque chose : SmartScreen ne connaît simplement
pas encore ce fichier. Pour passer outre : cliquer **Informations
complémentaires**, puis **Exécuter quand même**.

C'est à refaire à chaque nouvelle version — la réputation d'un fichier non
signé se compte par fichier, et repart de zéro à chaque publication. Signer n'y
changerait pas grand-chose : depuis 2024, même un certificat EV, à quelques
centaines d'euros par an, doit construire sa réputation comme les autres. Le
seul chemin qui supprime vraiment l'avertissement est le Microsoft Store, qui
signe lui-même ce qu'il distribue — l'inscription y est gratuite depuis 2025 —
au prix d'un empaquetage MSIX et d'un passage en revue.

## Les trois gestes

**Importer** un enregistrement WAV : la forme d'onde s'affiche immédiatement et le
fichier est écoutable, **avant même d'analyser**. Le tracé d'un concert de 2 h
apparaît en 5 s.

**Analyser** : morceaux conservés en vert, passages supprimés en rose, une barre
par frontière, et une vue d'ensemble sous le tracé.

**Exporter** : choisir où poser le dossier du concert. C'est tout — la suite de
cette section ne sert qu'à corriger ce que la détection aurait manqué.

Les actions qui portent sur le fichier entier — Importer, Analyser, Exporter —
sont groupées en haut. Les commandes d'édition sont contre la forme d'onde sur
laquelle elles agissent, et la poignée entre le tracé et le tableau laisse
donner à chacun la place que ce concert-là réclame.

**Rien à enregistrer.** Le travail en cours s'écrit tout seul, deux secondes
après le dernier geste et à la fermeture. À la séance suivante, « Reprendre »
rouvre le découpage, les titres, les réglages et la destination du dernier
export — sans réanalyser. Découper un concert de deux heures ne se fait pas
d'une traite.

## Corriger à la souris

| Action | Comment |
|---|---|
| Lire / mettre en pause | Bouton du transport, ou Espace |
| Placer la tête de lecture | Clic dans le tracé — le son ne démarre pas pour autant |
| Placer *et* écouter | Double clic dans le tracé |
| Promener la tête de lecture | La saisir et la glisser |
| Revenir au début d'une section | Origine (Début) — deux fois de suite, la section précédente |
| Aller de frontière en frontière | Flèches ← et → |
| Répéter un passage | B, pour caler une coupe en le réécoutant |
| Écouter à partir d'un segment | Colonne ▶ de sa ligne — la lecture continue au-delà ; un second clic met en pause |
| Se déplacer dans le concert | Clic n'importe où sur la barre de progression |
| Zoomer | Molette sur la forme d'onde |
| Naviguer | Maj+glisser, ou cliquer dans la vue d'ensemble |
| Écouter une coupe | Cliquer la frontière sans la bouger — lecture 5 s avant |
| Déplacer une frontière | La saisir et la glisser (n'enclenche pas la lecture) |
| Saisir un horaire | Cliquer la colonne Début ou Fin et taper `12:34` |
| Fusionner deux segments | Sélectionner leur frontière, puis Suppr |
| Poser une frontière | Cliquer dans le tracé, puis « Couper » (C) — vert ou rouge |
| Séparer un morceau en deux pistes | « Séparer » (Maj+C), qui insère le blanc nécessaire |
| Garder / Supprimer un passage | Cliquer la colonne Action de la ligne |
| Avancer dans un morceau | Cliquer dans sa silhouette, colonne Piste |
| Nommer un morceau | Cliquer son nom dans la colonne Morceau et saisir |
| Choisir les morceaux à exporter | La liste « Morceaux » de la fenêtre d'export |
| Exporter en vidéo | Cocher une case sous « Vidéo » dans la fenêtre d'export |
| Annuler / Rétablir | Ctrl+Z / Ctrl+Y, ou les boutons Annuler / Rétablir |

**Couper marche partout.** « Couper » pose une frontière au curseur, dans un
morceau comme dans un blanc, sans rien retirer du son : les deux moitiés gardent
leur couleur, et la case décide ensuite du sort de chacune. C'est ce qu'il faut
pour marquer, dans un long passage rouge, l'entrée que la détection a manquée.
« Séparer » est l'autre geste : deux segments verts voisins forment *un* seul
morceau au rendu, donc obtenir deux pistes distinctes d'une même improvisation
demande un blanc entre elles — deux secondes, d'où deux commandes plutôt qu'une
qui trancherait à notre place.

**La fin d'un segment est le début du suivant.** Saisir un horaire dans la
colonne Début ou Fin déplace donc cette frontière-là, à la seconde près — ce que
six secondes par pixel interdisent à la souris. `12:34`, `1:02:14` et `754` se
lisent tous. Un horaire hors des bornes laisse la saisie ouverte plutôt que de
la perdre.

Toutes les éditions sont annulables : bascule, déplacement de frontière,
suppression, découpe. L'historique retient les cinquante derniers états et
repart à zéro à chaque nouvelle analyse.

Le tableau liste *tous* les segments, pas seulement les morceaux. Changer le
sort d'une ligne entre « Garder » et « Supprimer » est le geste le plus direct
pour corriger une erreur de catégorie — sans avoir à viser une frontière au
pixel.

Cette bascule ne détruit rien. Les segments restent des entités distinctes même
quand plusieurs se suivent en « Garder » ; le regroupement en morceaux est
*calculé* au moment du rendu. Marquer un blanc comme conservé réunit donc bien
ses deux voisins en une seule piste, mais un second clic défait l'opération. Les
segments ainsi rattachés portent le nom du morceau suivi de `(suite)`.

**Le numéro d'un morceau est posé à l'analyse et ne bouge plus.** Il bougeait :
décocher le morceau 4 faisait remonter tous les suivants d'un cran, si bien
qu'on ne pouvait plus désigner un morceau par son numéro d'un bout à l'autre
d'une séance, ni retrouver dans un dossier d'export le « 12 » qu'on avait sous
les yeux en travaillant. Un morceau écarté laisse maintenant un trou dans la
suite — 01, 02, 04, 05 —, ce qui est exactement l'information utile : il manque
quelque chose, et on sait quoi. Il garde son numéro et son nom dans le tableau,
suivis de la mention « retiré », et les retrouve si on le recoche.

Le numéro affiché est celui du **morceau**, pas du segment. Cocher le blanc
entre les morceaux 1 et 2 les réunit : la suite entière s'annonce alors « 1 »,
puisque c'est là qu'elle commence. Le 2 n'est pas perdu pour autant — il dort
sur son segment et réapparaît au décochage. Il était auparavant réécrit sur
place : le second morceau restait « 1 » une fois séparé, deux morceaux
distincts finissaient par porter le même numéro, l'export leur donnait le même
nom de fichier, et la fenêtre d'export refusait de s'ouvrir sur cette liste.

**Si tu connais le nombre de morceaux, donne-le** dans le champ « Morceaux
attendus ». C'est la seule information qui vienne de l'extérieur du signal, donc
la plus fiable du problème : l'outil fusionne alors les blancs les moins
convaincants — les moins profonds et les plus courts — jusqu'à retomber sur le
compte, et dit lesquels.

## Nommer les morceaux

Cliquer sur le nom d'un morceau dans la colonne Morceau ouvre un champ, Entrée
valide, Échap annule. Sans titre, les fichiers sortent en `Piste 01`,
`Piste 02`…

Un segment décoché se nomme aussi, et garde son nom : on reconnaît un morceau à
l'oreille avant de décider s'il ira dans l'export.

Le titre est attaché au segment qui ouvre le morceau, pas à un numéro de piste :
une numérotation se décale dès qu'on ajoute ou retire une frontière, et les
titres suivraient le mauvais morceau. Le renommage est annulable comme les
autres éditions.

## Exporter

<img src="docs/export.png" alt="La fenêtre d'export" width="420">

La fenêtre pose **trois questions numérotées**, dans l'ordre où on se les pose :
quels morceaux, sous quelle forme, où. Les morceaux passent en premier — c'est
la seule décision qui porte sur le concert, les deux autres portent sur des
fichiers. Chaque réglage est rangé sous ce qu'il modifie : le fondu enchaîné
sous les deux cases audio, puisqu'il n'agit que sur le fichier d'un seul tenant,
et le fondu entre images sous les images.

On choisit un **emplacement**, pas un dossier vierge : le concert y reçoit son
propre dossier, nommé d'après le fichier source. À la racine de ce dossier, il
n'y a que de l'audio ; tout le reste va dans `infos/`.

**Un concert n'a pas toujours à sortir en entier** — trois titres pour une
maquette, le rappel seul pour l'envoyer à quelqu'un. La première question de la
fenêtre permet de n'en cocher qu'une partie. Décocher là ne touche ni au
découpage ni à la numérotation : la piste 7 s'appelle `07` même si elle part
seule, sans quoi le dossier ne correspondrait plus ni au concert ni à un export
complet du même enregistrement. Pour retirer un passage du concert lui-même,
c'est la case du tableau.

```
<emplacement choisi>/
└── Concert Antidote 14.07.2026/
    ├── concert_clean.wav
    ├── 01 - Ouverture.wav
    ├── 02 - Le Long Chemin.wav
    └── infos/
        ├── concert_clean.cue
        ├── reperes.txt
        └── segments.json
```

La cue sheet est rangée avec les fichiers techniques mais désigne son audio par
`../concert_clean.wav` : les lecteurs résolvent ce chemin depuis l'emplacement
de la cue, donc elle reste fonctionnelle.

**Réexporter dans un dossier déjà utilisé ne détruit rien en silence.** Le
problème était double : les fichiers de même nom étaient écrasés sans un mot,
et — plus insidieux — ceux dont le nom ne coïncidait pas restaient en place. Un
second export de 5 morceaux dans un dossier qui en contenait 6 laissait
**11 fichiers**, un mélange de deux versions qui paraissait complet.

L'export refuse donc d'écrire par-dessus un export existant, et propose trois
issues : écrire dans un dossier libre (`Concert Antidote 14.07.2026 (2)`),
remplacer l'export précédent, ou annuler. Le remplacement s'appuie sur un
manifeste `infos/.concertcutter-export.json` écrit à chaque export : seuls les
fichiers qu'il liste sont effacés. Un fichier que l'utilisateur aurait déposé
dans le dossier n'est jamais touché.

## Export vidéo

Pour déposer un concert sur une plateforme qui n'accepte que de la vidéo :
**une image fournie par toi, et le titre du morceau écrit dessus**. Plusieurs
images défilent en diaporama, avec un fondu de l'une à l'autre — une seule photo
tenue deux heures finit par peser.

**Rien à régler en secondes.** Une image toutes les huit secondes, puis le cycle
recommence, aussi longtemps que dure le son : trois photos suffisent donc à
animer un concert de deux heures. Les images ont un temps été étalées sur la
durée à couvrir, une par morceau — et c'était le contraire d'un diaporama :
l'image changeait toutes les trois minutes et rien ne bougeait entre-temps. Un
cycle qui tourne, quitte à repasser plusieurs fois dans un même morceau, est ce
qui fait qu'il se passe quelque chose à l'écran.

**Les images se tiennent en liste, pas en champ.** Le bouton *Ajouter* ajoute à
la suite sans effacer ce qui est déjà choisi — on revient presque toujours pour
ajouter, rarement pour tout remplacer —, *Retirer* enlève la ligne choisie, et
les flèches ↑ ↓ décident de l'ordre du défilement.

La fenêtre d'export tient en **quatre cases, une par fichier possible** : album
continu et pistes séparées, en audio et en vidéo. Des cases plutôt que des
boutons radio — « l'un, l'autre, ou les deux » est en réalité deux questions
oui/non — et aucune question préalable « audio ou vidéo ? » : cocher « Album
continu » sous Vidéo dit déjà ce qu'on veut.

Cocher une case sous Vidéo et choisir l'image. Les MP4 (H.264 + AAC,
1920×1080) sont rangés dans `video/` :

```
└── Concert Antidote 14.07.2026/
    ├── 01 - Ouverture.wav
    └── video/
        ├── concert_clean.mp4        (l'album continu)
        ├── 01 - Ouverture.mp4
        └── 02 - Le Long Chemin.mp4
```

Le titre incrusté est celui saisi dans la colonne Morceau — le même que celui
qui nomme les fichiers. Un morceau resté sans titre affiche `Piste 03` plutôt
que rien. Le corps du texte s'ajuste à la longueur du titre pour qu'il tienne
dans la largeur, sur un bandeau sombre qui le garde lisible quelle que soit
l'image dessous. L'image garde ses proportions et se centre : elle n'est jamais
déformée pour remplir le cadre.

Les images d'un diaporama peuvent avoir des tailles différentes : chacune est
mise au cadre avant d'être enchaînée, ce qui évite à ffmpeg de buter sur un
changement de format en cours de flux.

**Sur la vidéo de l'album continu, le titre suit le morceau en cours** : il
change à chaque frontière, comme des chapitres. Une seule mention figée pendant
deux heures n'aurait rien dit de ce qu'on écoute. Les instants d'apparition sont
ceux de la vidéo produite, pas ceux du concert d'origine — les blancs retirés
ont décalé tout ce qui suit.

Si seule la vidéo t'intéresse, décocher les deux cases sous Audio : le son n'est
alors écrit qu'une fois, dans les MP4.

L'image ne bouge jamais : le coût réel de l'encodage est celui de l'audio.
Compter environ une minute de calcul pour trente minutes de concert.

### ffmpeg s'installe d'un bouton

<img src="docs/export-ffmpeg.png" alt="La fenêtre d'export sans ffmpeg" width="420">

**La vidéo demande ffmpeg**, la seule dépendance externe du projet — 100 Mo,
contre 25 pour ConcertCutter tout entier, donc il n'est pas embarqué.

Un bouton, une barre de progression, et c'est fait — une seule fois, pour toutes
les fois suivantes. Ce qui remplaçait cela était une phrase, « ffmpeg est
introuvable, installez-le », qui suppose de savoir ce qu'est ffmpeg, quel site
fait autorité, laquelle des six archives proposées prendre, et où poser le
fichier qu'elle contient : quatre obstacles, dont aucun ne concerne le découpage
d'un concert. C'est le seul endroit de l'application qui aille sur le réseau, et
seulement au clic.

L'archive vient de gyan.dev — les constructions que ffmpeg.org désigne pour
Windows — avec les constructions BtbN sur GitHub en second recours si le premier
site ne répond pas. Seul `bin/ffmpeg.exe` est extrait : le reste de l'archive
pèse trois cents mégaoctets dont rien ne sert ici. Le binaire obtenu est
**exécuté avant d'être déclaré installé** — une archive tronquée par une coupure
de réseau donne un fichier de taille plausible, qui n'échouerait qu'à l'export,
une heure plus tard.

Il est ensuite cherché dans `CONCERTCUTTER_FFMPEG`, à côté de
`ConcertCutter.exe`, dans le dossier d'installation
(`%LOCALAPPDATA%\ConcertCutter`), puis dans le `PATH`. Y déposer `ffmpeg.exe` à
la main reste donc possible, et un ffmpeg déjà présent sur la machine est
reconnu sans rien télécharger.

Sans lui, l'option est grisée et la fenêtre dit pourquoi, plutôt que de lancer
un export qui échouerait à la première piste.

---

# En ligne de commande

Tout ce qui précède se fait à la souris. Cette partie sert au traitement par
lot, et à la mise au point.

## Installation

```bash
pip install -r requirements.txt
python gui.py [concert.wav]
```

Aucune dépendance système : `numpy` et `soundfile` suffisent. Entrée et sortie
en WAV — sauf l'export vidéo, qui produit du MP4 et demande ffmpeg à part.

## En une passe

```bash
python -m concertcutter run concert.wav -d sortie --expected-tracks 24
```

Produit dans `sortie/` :

- `concert_clean.wav` — le concert entier, blancs retirés
- `concert_clean.cue` — marqueurs de piste pour ce fichier
- `01 - Piste 01.wav`, `02 - Piste 02.wav`, … — un fichier par morceau

Et à côté du fichier source :

- `concert.segments.json` — les segments détectés
- `concert.labels.txt` — repères Audacity

## Revue manuelle

L'analyse et le rendu sont deux commandes séparées, avec un JSON entre les
deux. C'est le point important : on peut corriger une frontière à la main sans
refaire l'analyse.

```bash
python -m concertcutter analyze concert.wav
```

Ouvrir `concert.wav` dans Audacity, puis *Fichier > Importer > Étiquettes* avec
`concert.labels.txt` : les frontières apparaissent sur la forme d'onde. Le
résumé console signale par `<- à vérifier` les segments où la détection hésite.
Corriger les temps dans `concert.segments.json`, puis :

```bash
python -m concertcutter render concert.segments.json -d sortie
```

## Tracklist

Un fichier texte, un titre par ligne (les lignes vides et les `#` sont ignorés) :

```bash
python -m concertcutter run concert.wav -d sortie --tracklist titres.txt
```

Les fichiers sortent nommés. Surtout, si le nombre de titres ne correspond pas
au nombre de morceaux détectés, l'outil le signale — c'est le meilleur
garde-fou disponible pour un coût nul.

## Vérifier à l'oreille

Juger un détecteur sur sa propre segmentation est circulaire. La seule
vérification honnête est l'écoute :

```bash
python -m concertcutter verify concert.segments.json -d verification --max-confidence 0.97
```

Un WAV de douze secondes par frontière douteuse, avec un bip à l'instant exact
de la coupe : on entend la fin du blanc puis le début du morceau, donc on juge
si la coupe tombe au bon endroit et pas seulement si elle existe.

Pour contrôler une décision de fusion — une frontière écartée n'apparaît plus
dans les segments, donc `--max-confidence` ne peut pas la produire :

```bash
python -m concertcutter verify concert.segments.json -d verification --at 27:14,36:10
```

## Morceaux enchaînés sans blanc

Contrôle **additionnel, en ligne de commande seulement**. Le bouton a été retiré
de l'interface : sur du matériel réel il ne produisait que des faux positifs,
pour un cas de figure rare. La fonction reste utile quand le compte de morceaux
est inférieur à celui attendu.

La détection par niveau reste le moteur ; celle-ci cherche seulement les
endroits où la musique change franchement sans que le volume ne bouge — le seul
cas que le niveau ne peut structurellement pas voir.

```bash
python -m concertcutter segues concert.segments.json --cache feats.npz
```

Méthode : chroma sur douze classes de hauteur, matrice d'auto-similarité
réduite à une bande autour de la diagonale, noyau en damier de Foote. Pur
numpy, aucun modèle. La matrice complète d'un concert de deux heures ferait
7 Go ; la bande en fait quelques mégaoctets.

**Ce que ça vaut, mesuré.** Sur un enchaînement réel confirmé à l'oreille
(36:15 du concert de test), la courbe monte à 0,570, contre une médiane de
0,195 à l'intérieur des morceaux — mais son 99e centile est à 0,575. Test de
rappel : en masquant volontairement cette frontière, l'outil la retrouve à
**1,8 seconde près**, classée 6e sur 12 candidats.

Donc : très bonne localisation, classement médiocre. C'est une **liste d'écoute
classée, pas un détecteur**. Elle sert surtout quand le nombre de morceaux
trouvés est inférieur à celui attendu.

## Toutes les options

| Option | Défaut | Effet |
|---|---|---|
| `--expected-tracks` | — | Nombre de morceaux connu (recommandé) |
| `--min-gap` | 6 s | Un blanc plus court est absorbé dans le morceau |
| `--min-song` | 45 s | Un morceau plus court est absorbé dans le blanc |
| `--stay-prob` | 0.999 | Persistance des états dans le HMM |
| `--refine-window` | 2.5 s | Fenêtre de recalage des frontières |
| `--smooth` | 0.75 s | Lissage du niveau avant décision |
| `--pad-start` | 0.5 s | Amorce conservée avant chaque morceau |
| `--pad-end` | 0.6 s | Queue d'applaudissements conservée après |
| `--fade-ms` | 40 | Fondus d'entrée et de sortie |
| `--crossfade` | 0 s | Fondu enchaîné entre morceaux, dans l'album continu |
| `--only N,N` | — | N'écrire que ces morceaux (`1,4,7` ou `3-9`), numéros conservés |
| `--video-image F` | — | Écrit aussi des MP4, sur cette image de fond |
| `--video` | `pistes` | Quelles vidéos : `pistes`, `album`, ou `les-deux` |
| `--no-wav` | — | Avec `--video-image` : les vidéos seules, sans les WAV |
| `--overwrite` | — | Autorise l'écriture par-dessus un export existant |
| `--method energy` | — | Repasse au détecteur V0, pour comparaison |
| `--cache F.npz` | — | Relit les descripteurs (instantané) au lieu de les recalculer (9 s sur 2 h 05) |

Le coût des erreurs est asymétrique : garder dix secondes d'applaudissements
passe inaperçu, rogner les deux premières mesures d'un morceau ruine la piste.
Tous les défauts penchent du côté conservateur.

---

# Sous le capot

## Comment marche la détection

1. **Descripteurs** (`spectral.py`) — niveau, ratio de grave, présence, platitude
   spectrale, corrélation L/R, toutes les 0,25 s.
2. **Deux modes** (`gmm.py`) — un mélange gaussien à deux composantes trouve
   dans le signal lui-même le niveau des blancs et celui de la musique. Plus de
   seuil magique, et l'écart entre les modes dit si l'enregistrement est facile.
3. **Viterbi** (`hmm.py`) — la séquence d'états globalement la plus vraisemblable,
   au lieu d'un seuillage trame par trame. Le forward-backward fournit en prime
   une vraie confiance, qui sert à trier les frontières à réécouter.
4. **Règles de durée** puis **recalage des frontières** sur la transition de
   niveau la plus franche, dans une fenêtre de 2,5 s.

Sur le concert de test, les deux modes tombent à **-43,2 dB** et **-24,7 dB**,
soit 18,5 dB d'écart, sans aucun réglage.

## Pourquoi l'interface est faite ainsi

**Le zoom n'est pas un confort.** Deux heures étalées sur la largeur d'un écran
font plus de six secondes par pixel : placer une frontière au bon endroit y est
impossible. Sous une minute et demie de fenêtre visible, le tracé bascule
automatiquement sur les échantillons réels, relus à la volée sur la seule
portion affichée.

**La colonne Action ouvre un menu** montrant les deux choix, l'actuel coché :
une bascule au clic ne disait ni qu'elle était cliquable, ni ce qu'elle allait
produire.

**La tête de lecture apparaît sur les deux tracés** — le zoom et la vue
d'ensemble — parce que la seconde est la seule à montrer le concert entier, donc
la seule qui situe l'écoute dans l'ensemble dès qu'on est zoomé.

**La barre de progression est un canevas**, pas un `ttk.Scale` : cette dernière
avance d'un pas fixe quand on clique dans son couloir, ce qui demandait une
dizaine de clics pour atteindre une minute précise sur un concert de deux
heures. Ici, un clic vaut un déplacement direct.

**Le lecteur** passe par l'interface MCI de Windows (`winmm.dll` via `ctypes`),
et non par `winsound` qui ne sait que jouer un fichier entier — sans pause, ni
position, ni intervalle. MCI lit **en flux** : mesuré à 0,06 s pour ouvrir un
WAV de 1,86 Go, sans le charger en mémoire. On obtient donc lecture depuis un
instant, intervalle borné, pause, reprise et position réelle, toujours sans
aucune dépendance.

Tkinter et `ctypes` sont dans la bibliothèque standard : l'interface n'ajoute
rien à installer et reste empaquetable sans effort. La lecture n'existe que
sous Windows ; ailleurs, tout le reste fonctionne.

## Ce que le matériel réel a appris

Deux hypothèses de départ se sont révélées fausses, et il valait mieux le
découvrir par la mesure que par un bug tardif :

- **La corrélation L/R ne sert à rien ici.** L'idée était que les
  applaudissements forment un champ diffus (L et R décorrélés) là où un mix a
  la voix et la basse au centre. Sur le concert de test, la corrélation vaut
  0,995 en médiane et dépasse 0,93 sur 97 % des trames : l'enregistrement est
  quasi mono, probablement une captation console. Le descripteur est calculé et
  archivé, mais il n'entre pas dans la décision.
- **Le ratio de grave ne sépare pas non plus.** L'idée — les applaudissements
  n'ont pas de grave, la musique a une grosse caisse — donne 0,341 côté musique
  contre 0,337 côté blancs. Rigoureusement identique.

Ce qui sépare vraiment, sur ce matériel, c'est le niveau : 18,5 dB d'écart
entre les deux modes. Une captation console est le cas facile, parce que le
public n'y entre que par repisse.

## Limites connues

- Une captation *dans la salle* (micro d'ambiance, téléphone) aura un écart de
  modes bien plus faible. L'outil le signale sous 6 dB, mais ne sait pas encore
  faire mieux dans ce cas.
- Deux morceaux enchaînés sans blanc restent indétectables.
- Un présentateur qui parle par-dessus la musique n'est pas géré.
- **Le niveau ne suffit pas à départager deux blancs courts.** Sur le concert de
  test, une vraie frontière de 9,5 s / 8,9 dB et une fausse de 15,5 s / 8,5 dB
  sont indiscernables par l'énergie seule. `--expected-tracks` choisit alors mal.
  C'est ce que `segues` vient compléter, sans le résoudre entièrement.
- **Le tempogramme ne marche pas** sur ce matériel — voir l'en-tête de
  `segue.py`. Le code reste, sous `--with-rhythm`, mais désactivé.

## Pistes pour la suite

**Whisper, mais ciblé.** Transcrire les deux heures serait lent et peu fiable :
Whisper est entraîné sur de la parole et hallucine abondamment sur de la
musique et des applaudissements. En revanche, le lancer *uniquement sur les
blancs candidats* — quelques minutes d'audio au lieu de deux heures — pour
répondre à « y a-t-il de la parole articulée ici ? » joue sur son point fort.
Une annonce au micro est un indice bien plus solide qu'une chute de niveau.

**Base de données de paroles : déconseillé.** Identifier un morceau ne dit pas
où il commence, et c'est la frontière qu'on cherche, pas le titre. Le titre,
la tracklist le donne déjà. En échange, il faudrait une API externe, sa
disponibilité, ses conditions d'utilisation, et un appariement flou sur des
transcriptions bruitées — beaucoup de fragilité pour une information dont on
dispose autrement.

**Timbre en complément du chroma.** Un vecteur de bandes log-mel réagirait à un
changement d'instrumentation là où la tonalité ne bouge pas. C'est le
descripteur qui manque le plus pour améliorer le classement de `segues`, et il
se calcule dans la passe spectrale existante.

**Classifieur d'événements audio** (YAMNet, PANNs) branché comme source
d'émissions alternative du HMM : le reste du code ne bougerait pas, tout passe
par `list[Segment]`. Attention au poids pour une application à empaqueter —
TensorFlow dépasse 500 Mo, un export ONNX serait préférable.

---

# Développement

## Construire l'exécutable

Utile seulement pour publier une version, ou après avoir modifié le code :

```bash
build_exe.bat
```

Le script installe PyInstaller au besoin et écrit `dist\ConcertCutter.exe`.
Mesuré : fenêtre affichée en 1,1 s, 51 Mo en mémoire au repos. Un simple `.bat`
qui appellerait `python gui.py` n'aurait pas suffi — il supposerait Python et
les bibliothèques déjà installés sur la machine.

**La publication est automatique.** `dist/` est ignoré par git : un exécutable
construit ici ne va nulle part, et c'était la raison pour laquelle il n'existait
aucun lien de téléchargement. Poser une étiquette de version déclenche
`.github/workflows/release.yml`, qui reconstruit l'exécutable sous Windows et
l'attache à une release GitHub :

```bash
git tag v1.1 && git push origin v1.1
```

Le fichier attaché garde toujours le même nom, ce qui rend le lien
`releases/latest/download/ConcertCutter.exe` valable sans le réécrire. Le
workflow se déclenche aussi à la main depuis l'onglet Actions, et dépose alors
l'exécutable en pièce jointe de l'exécution, sans rien publier.

## Outils

`tools/` fabrique de quoi tester sans dépendre d'un concert réel, et contrôle ce
qui ne se voit pas à la lecture.

```bash
python tools/make_fake_concert.py -n 6 -o test/faux_concert.wav
python -m concertcutter run test/faux_concert.wav -d test/sortie
python tools/compare.py test/faux_concert.truth.json test/faux_concert.segments.json
```

- `make_fake_concert.py` — faux concert + vérité terrain
- `compare.py` — morceaux retrouvés et **secondes de musique rognées**
- `sweep.py` — balaye `drop_db` pour vérifier qu'un réglage tient sur une plage
  large, et pas seulement sur 2 dB
- `check_output.py` — durées, écrêtage, et bords à zéro (un fondu manquant
  s'entend comme un clic)
- `check_ffmpeg_install.py` — le bouton d'installation : emplacement, sources
  joignables, ménage d'un téléchargement abandonné, et la fenêtre qui ne bouge
  pas pendant le travail. Le téléchargement y est simulé, sauf avec
  `--vraiment` qui installe pour de bon puis remet la machine en état
- `check_video_export.py` — de bout en bout : le titre saisi finit-il écrit sur
  l'image du MP4, et change-t-il bien au morceau suivant sur l'album continu ?
  Le contrôle mesure vraiment les pixels du bandeau — une incrustation ratée ne
  fait pas échouer ffmpeg, elle sort une vidéo vierge. Le test s'annonce ignoré
  si ffmpeg manque, il n'échoue pas
- `smoke_gui.py` — l'interface entière parcourue sans souris
- `make_screenshots.py` — refait les captures de ce README. Une capture prise à
  la main vieillit sans prévenir

Ces scripts demandent le paquet sur le `PYTHONPATH` :

```bash
PYTHONPATH=. python tools/sweep.py test/faux_concert.wav test/faux_concert.truth.json
```

---

# Licence

[MIT](LICENSE). ffmpeg, s'il est installé par le bouton de la fenêtre d'export,
reste distribué par ses auteurs sous ses propres conditions — il est téléchargé
sur la machine de l'utilisateur, jamais redistribué ici.
