# Guide utilisateur

[English](user-guide.en.md) · Français

Ce guide décrit l'interface graphique actuelle de ConcertCutter. Pour réaliser
un premier export sans parcourir toutes les options, suivez la prise en main du
[README](../README.fr.md#premier-export).

## Choisir la langue

Ouvrez **Options** depuis l’accueil ou la barre du concert. Dans **Langue**,
choisissez **Automatique (Windows)**, **Français** ou **English**, puis
**Enregistrer les options**. La traduction s’applique immédiatement, sans
redémarrage ni perte du travail ouvert. **Annuler** conserve le choix précédent.

Le mode automatique, activé par défaut, suit la langue d’affichage de Windows :
français pour une langue française, anglais dans les autres cas et si la
détection échoue. Windows est interrogé à chaque lancement. Un choix manuel
prend la priorité et reste conservé pour tous les projets dans
`%LOCALAPPDATA%\ConcertCutter\preferences.json`.

Les titres saisis et les noms des fichiers exportés restent inchangés. Les
boutons des dialogues natifs suivent Windows. Les détails techniques des outils
externes peuvent rester dans leur langue d’origine sous un message traduit.

## Ouvrir ou reprendre un concert

L'écran d'accueil propose trois chemins :

- **Ouvrir un enregistrement WAV** lance le sélecteur de fichiers natif ;
- **Reprendre un travail…** ouvre un projet ConcertCutter ou un
  `segments.json` déjà exporté ;
- **Travaux récents** rouvre directement une analyse sauvegardée.

L'enregistrement n'est pas envoyé sur Internet. Une fois ouvert, sa forme
d'onde globale apparaît et il peut être écouté avant l'analyse.

Cliquez sur **Analyser** pour détecter les morceaux et les zones à retirer. Les
options de détection se règlent depuis **Options & Réglages** :

| Réglage | Valeur initiale | Effet |
|---|---:|---|
| Silence minimum | 6 s | Une zone plus courte reste dans le morceau |
| Morceau minimum | 75 s | Un passage plus court n'est pas considéré comme un morceau |
| Morceaux attendus | 0 | À zéro, la détection choisit librement le nombre de morceaux |
| Amorce avant | 0,5 s | Son conservé avant chaque morceau lors de l'export |
| Queue après | 0,6 s | Son conservé après chaque morceau lors de l'export |
| Fondus anti-clic | 40 ms | Fondus très courts aux extrémités des pistes |

Les trois premiers réglages demandent de relancer l'analyse. Les réglages de
montage s'appliquent au prochain export.

## Comprendre l'écran de travail

La **vue globale** représente tout le concert. Un clic y place la tête de
lecture et déplace la fenêtre détaillée autour de cet instant.

La liste **Pistes & Segments** contient :

- les morceaux conservés, numérotés et éventuellement titrés ;
- les zones détectées comme blancs ou applaudissements, marquées **À retirer**.

Un clic sur une ligne la sélectionne. La carte de droite affiche alors le
segment, ses deux frontières, sa durée, sa confiance et son sort actuel.

Les segments voisins de même type restent distincts dans l'éditeur, mais les
segments conservés contigus sont réunis en une seule piste à l'export. Le
numéro d'origine d'un morceau reste stable lorsque d'autres morceaux sont
retirés ou exclus d'un export partiel.

## Écouter et se déplacer

| Geste | Résultat |
|---|---|
| Bouton de lecture ou `Espace` | Lire ou mettre en pause depuis la tête de lecture |
| Clic ou glissement dans le corps de la forme d'onde détaillée | Déplacer la tête de lecture sans démarrer le son |
| Bouton `▶` d'une ligne | Sélectionner et lire ce segment depuis son début |
| Clic dans la vue globale | Placer la tête et recentrer la vue détaillée |
| Molette sur la forme d'onde | Zoomer autour du pointeur |
| `←` ou `→` | Aller à la frontière précédente ou suivante |
| `Origine` | Aller au début de la section ; répéter pour revenir à la précédente |
| `B` | Lire en boucle le segment sous la tête de lecture |
| `Échap` | Arrêter la lecture |

La vue détaillée suit la lecture tant qu'elle n'a pas été positionnée
manuellement. Après un clic dans cette vue, elle reste fixe pour permettre de
régler une coupe sans perdre le passage affiché.

Écouter les marges orange conserve le segment sélectionné et ses deux bornes.
Pour éditer une zone voisine, sélectionnez-la dans la liste ou la vue globale.

## Corriger les segments

### Déplacer une frontière

Une frontière est commune aux deux segments qu'elle sépare : déplacer la fin
du premier déplace également le début du second.

Trois méthodes sont disponibles dans la carte d'édition :

- saisir la frontière sur toute sa hauteur, ou l'une de ses poignées, et la faire glisser ;
- saisir un horaire dans **Début de section** ou **Fin de section** ;
- utiliser `−` et `+` pour déplacer la frontière de 0,5 seconde.

Les horaires `12:34`, `1:02:14` et `754` sont acceptés. Une valeur invalide est
refusée et l'ancienne frontière est conservée.

Le pointeur devient une main au survol de la tête de lecture et une double
flèche horizontale au survol d'une frontière. Lorsque les deux traits se
superposent, saisissez le milieu pour déplacer la lecture, ou une poignée en
haut ou en bas pour déplacer la frontière.

### Garder ou supprimer

Les boutons **Garder** et **Supprimer** changent le sort du segment sélectionné.
Dans la liste, le bouton **Conserver** permet de réintégrer directement une zone
à retirer.

Cette opération ne supprime pas de son immédiatement : elle change la
segmentation utilisée au prochain export et reste annulable.

### Couper ou fusionner

- **Couper ici** ou `C` pose une frontière à la tête de lecture. Les deux
  moitiés conservent le type du segment d'origine.
- `Maj+C` sépare un morceau en deux pistes en insérant la zone nécessaire entre
  elles.
- **Fusionner** ou `Suppr` retire la frontière de fin du segment sélectionné.

### Nommer les morceaux

Cliquez sur le titre dans la carte d'édition, ou double-cliquez le titre dans
la liste. `Entrée` valide la saisie et `Échap` l'annule.

Un morceau sans titre est exporté sous la forme `Piste 01`, `Piste 02`, etc. Une
zone à retirer ne peut pas être nommée. Le titre reste attaché au morceau lors
des corrections de frontières.

### Annuler

Les boutons de l'en-tête, `Ctrl+Z` et `Ctrl+Y` permettent d'annuler et de
rétablir les cinquante derniers états d'édition. Une nouvelle analyse remet
l'historique à zéro.

## Sauvegarde et reprise

Le projet est sauvegardé automatiquement environ deux secondes après une
modification et à la fermeture. Il conserve :

- la segmentation et les titres ;
- les réglages d'analyse et de montage ;
- la sélection de morceaux, la destination et les images du dernier export.

Les quatre cases de sortie ne sont volontairement pas mémorisées : elles sont
à choisir à chaque export.

Les projets récents sont conservés dans les données utilisateur de
ConcertCutter. Si l'enregistrement WAV a été déplacé, l'application demande de
le localiser à nouveau au lieu de relancer l'analyse.

## Exporter

La fenêtre d'export suit trois étapes.

### 1. Choisir les morceaux

Au premier export, tous les morceaux sont sélectionnés. Les fois suivantes,
l'application retrouve la dernière sélection enregistrée. Vous pouvez la
modifier ou utiliser **Tout cocher** et **Tout décocher**.

Cette sélection ne modifie pas le concert ni ses numéros. Si seule la piste 7
est exportée, son fichier commence toujours par `07`.

### 2. Choisir les fichiers

Aucune des quatre sorties n'est cochée automatiquement :

- **Le concert en un seul fichier** produit `audio/concert_clean.wav` et sa cue
  sheet ;
- **Un fichier par morceau** produit un WAV numéroté par piste ;
- **Un MP4 du concert entier** produit une vidéo dont le titre suit le morceau
  en cours ;
- **Un MP4 par morceau** produit une vidéo titrée pour chaque piste.

Le **fondu enchaîné** de l'album WAV et celui de la vidéo complète sont deux
réglages distincts. Ils n'affectent pas les fichiers individuels. À zéro, les
morceaux sont placés bout à bout.

#### Images des vidéos

Au moins une image est nécessaire pour produire un MP4. Les formats proposés
par le sélecteur sont JPEG, PNG, BMP et WebP. Les images peuvent être
réordonnées par glisser-déposer ou avec les flèches gauche et droite lorsqu'une
vignette a le focus.

Deux comportements sont possibles :

- par défaut, les images défilent dans l'ordre, une toutes les huit secondes,
  puis le cycle recommence ;
- avec **Une seule image par morceau**, la première image est associée au
  premier morceau sélectionné, la deuxième au suivant, etc. S'il manque des
  images, le cycle recommence ; s'il y en a trop, les dernières sont ignorées.

Le **fondu entre images** règle la transition du diaporama. En mode une image
par morceau, il agit aux frontières de la vidéo complète ; une vidéo de piste
individuelle garde une image fixe.

Avec une image par morceau, le fondu d'image commence avec le morceau entrant.
Si le fondu enchaîné de la vidéo et celui des images valent tous deux 2 secondes,
leurs transitions commencent et finissent ensemble, sous réserve que les
morceaux soient assez longs pour appliquer cette durée. Un chapitre trop court
limite uniquement la transition qui le concerne.

Le titre du morceau est incrusté sur chaque vidéo. Les proportions de l'image
sont conservées et l'espace restant est rempli en noir.

#### ffmpeg

L'export vidéo demande ffmpeg. S'il manque, la fenêtre propose **Installer
ffmpeg** et affiche la progression. Le téléchargement n'a lieu qu'après ce
clic.

L'application reconnaît également un `ffmpeg.exe` indiqué par la variable
`CONCERTCUTTER_FFMPEG`, placé à côté de `ConcertCutter.exe`, installé dans les
données utilisateur ou disponible dans le `PATH`.

### 3. Choisir la destination

Choisissez un emplacement existant. ConcertCutter y crée un sous-dossier portant
le nom du WAV source :

```text
<destination>/
└── Nom du concert/
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

Les dossiers et fichiers absents de votre sélection ne sont pas créés. La cue
sheet vise `../audio/concert_clean.wav`. `reperes.txt` contient des marqueurs
Audacity et `segments.json` permet de rouvrir ou d'inspecter le découpage.

### Réexporter ou interrompre

Si la destination contient déjà un export, trois choix sont proposés :

- écrire à côté dans un dossier suffixé ;
- remplacer l'export précédent ;
- ne rien faire.

Le manifeste caché dans `infos/` permet de remplacer uniquement les fichiers
produits par ConcertCutter. Un fichier ajouté manuellement est conservé.

L'export peut être interrompu depuis son écran de progression.
Un export interrompu laisse l'export précédent en place et nettoie ses fichiers
temporaires.

## Dépannage et limites

- **SmartScreen bloque l'exécutable** : vérifiez qu'il vient de la release
  GitHub officielle, puis choisissez **Informations complémentaires** et
  **Exécuter quand même**.
- **La fenêtre native ne s'ouvre pas** : l'application peut se replier sur le
  navigateur par défaut ; les fonctions restent les mêmes, mais les chemins se
  saisissent manuellement si les boîtes de dialogue ne sont pas disponibles.
- **La vidéo est indisponible** : installez ffmpeg depuis l'export ou fournissez
  un exécutable doté du filtre `drawtext` et d'un encodeur MP4.
- **Trop de corrections sont nécessaires** : les captations d'ambiance, les
  téléphones et les morceaux enchaînés sans baisse de niveau sont les cas les
  plus difficiles. Utilisez **Morceaux attendus** si le compte est connu, puis
  contrôlez chaque frontière à l'oreille.
- **Un enchaînement reste invisible** : la commande avancée `segues` peut
  produire une liste d'instants à écouter, sans modifier le projet par défaut.

Pour cette dernière fonction et les traitements par lot, consultez la
[référence en ligne de commande](ligne-de-commande.md).
