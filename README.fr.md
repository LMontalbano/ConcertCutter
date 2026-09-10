# ConcertCutter

[English](README.md) · Français

ConcertCutter découpe automatiquement un concert enregistré en morceaux. Il
repère les passages à retirer — applaudissements, discussions, accordage — puis
permet de corriger chaque coupe avant d'exporter le résultat en WAV ou en MP4.

L'analyse et les fichiers restent sur votre ordinateur. L'interface utilise un
serveur local protégé, accessible uniquement depuis la machine.

## Télécharger

**[Télécharger ConcertCutter.exe](https://github.com/LMontalbano/ConcertCutter/releases/latest/download/ConcertCutter.exe)**
pour Windows 10 ou 11.

L'exécutable est autonome : posez-le où vous voulez et double-cliquez dessus.
Il n'installe ni Python ni dépendance système. Pour le supprimer, mettez le
fichier à la corbeille.

Windows SmartScreen peut avertir au premier lancement d'une version non signée.
Choisissez **Informations complémentaires**, puis **Exécuter quand même** si le
fichier vient bien du lien ci-dessus.

## Langue

Depuis l’accueil ou la barre du concert, ouvrez **Options**, choisissez
**Automatique (Windows)**, **Français** ou **English**, puis **Enregistrer les
options**. Le changement s’applique sans redémarrer ni perdre le travail ouvert.
**Annuler** conserve la langue précédente.

Le mode automatique est activé par défaut : une langue d’affichage Windows
française donne une interface française ; les autres langues, ou un échec de
détection, donnent une interface anglaise. Le choix manuel est prioritaire et
conservé entre les lancements, indépendamment des projets.

## Mises à jour

L'exécutable Windows recherche les nouvelles releases stables au lancement,
sans retarder l'ouverture de l'interface. Si une version est disponible, une
bannière permet de la télécharger, d'en vérifier l'empreinte SHA-256 puis de
redémarrer ConcertCutter sur le travail en cours. Ce contrôle peut être
désactivé ou lancé manuellement depuis **Options**.

## Premier export

1. Cliquez sur **Ouvrir un enregistrement WAV** et choisissez le concert.
2. Cliquez sur **Analyser**. Les morceaux apparaissent dans la liste de gauche
   et le segment sélectionné dans la carte d'édition.
3. Écoutez les transitions, déplacez les frontières si nécessaire et donnez un
   titre aux morceaux.
4. Cliquez sur **Exporter**, choisissez les morceaux, les fichiers à produire
   et leur destination.

Aucune sortie n'est cochée à l'avance : choisissez explicitement le concert en
un seul fichier, les pistes séparées, leurs équivalents vidéo, ou plusieurs de
ces sorties.

## Corriger le découpage

- Sélectionnez un morceau ou une zone à retirer dans la liste de gauche.
- Cliquez dans la forme d'onde détaillée pour placer la tête de lecture.
- Faites glisser une poignée de frontière, saisissez un horaire précis ou
  utilisez les boutons `−` et `+` par pas de 0,5 seconde.
- Utilisez **Garder** ou **Supprimer** pour changer le sort du segment.
- Utilisez **Couper ici** pour créer une frontière et **Fusionner** pour retirer
  la frontière de fin du segment sélectionné.
- Cliquez sur le titre dans la carte, ou double-cliquez son titre dans la liste,
  pour le renommer.

Les modifications peuvent être annulées avec `Ctrl+Z` et rétablies avec
`Ctrl+Y`.

| Raccourci | Action |
|---|---|
| `Espace` | Lecture ou pause |
| `←` / `→` | Frontière précédente ou suivante |
| `Origine` | Début de la section courante, puis section précédente |
| `B` | Boucler le segment sous la tête de lecture |
| `C` | Couper à la tête de lecture |
| `Maj+C` | Séparer un morceau en deux pistes |
| `Suppr` | Fusionner à la frontière sélectionnée |
| `Échap` | Arrêter la lecture |

La sauvegarde est automatique après l'analyse et les modifications. L'écran
d'accueil permet de reprendre un travail récent sans relancer l'analyse.

Le [guide utilisateur](docs/guide-utilisateur.md) détaille l'écoute, l'édition,
la reprise et tous les choix d'export.

## Fichiers produits

ConcertCutter crée un dossier portant le nom de l'enregistrement dans la
destination choisie :

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

Seuls les fichiers demandés sont écrits. Les vidéos nécessitent au moins une
image de fond et **ffmpeg**. Si ffmpeg manque, la fenêtre d'export propose de
l'installer. Ces téléchargements, comme celui d'une mise à jour, commencent
uniquement après un clic de l'utilisateur.

Un export existant n'est jamais écrasé silencieusement. L'application propose
d'écrire à côté, de remplacer les fichiers de l'export précédent, ou d'annuler.
Les fichiers ajoutés manuellement au dossier sont conservés.

## Limites connues

- L'interface graphique accepte les enregistrements WAV.
- La détection fonctionne mieux quand la musique est nettement plus forte que
  les échanges avec le public. Une captation de salle ou de téléphone demande
  généralement davantage de corrections.
- Deux morceaux enchaînés sans baisse de niveau ne peuvent pas être séparés
  automatiquement par l'interface.
- Le nombre de morceaux attendus aide à fusionner de fausses coupures, mais ne
  peut pas inventer une frontière absente du signal.
- Une personne qui parle par-dessus la musique peut rester dans le morceau.

## Ligne de commande

Pour le traitement par lot et les contrôles avancés :

```powershell
python -m pip install -r requirements.txt
python -m concertcutter run concert.wav -d sortie --expected-tracks 24
```

Les commandes `analyze`, `render`, `run`, `verify` et `segues`, leurs options et
leurs sorties sont décrites dans la [référence en ligne de
commande](docs/ligne-de-commande.md).

## Développer

Le cœur est en Python. L'interface Svelte est compilée puis servie localement
par l'application Python et affichée dans une fenêtre WebView2, avec repli vers
le navigateur par défaut.

```powershell
python -m pip install -r requirements.txt
python gui.py test/faux_concert.wav
python tools/check_all.py
```

Consultez le [guide de développement](docs/developpement.md) pour l'installation
de Node.js, le mode Vite, les tests, la construction de l'exécutable et la
publication d'une release.

## Documentation

- [Guide utilisateur](docs/guide-utilisateur.md)
- [Référence en ligne de commande](docs/ligne-de-commande.md)
- [Guide de développement](docs/developpement.md)
- [Développement du frontend](web/README.fr.md)

## Licence

[MIT](LICENSE). ffmpeg, lorsqu'il est installé depuis l'application, reste
distribué par ses auteurs sous ses propres conditions.
