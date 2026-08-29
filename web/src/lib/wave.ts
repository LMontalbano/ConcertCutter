/* Le tracé, en canvas impératif.

   C'est la seule partie de l'interface qui ne soit pas de l'état de
   formulaire : trente mille points à redessiner à chaque image de glissé, ce
   qu'aucun arbre de composants ne rend correctement. Le reste de l'écran est
   déclaratif ; ici, on peint.

   Trois vues, une seule fonction de peinture : le ruban du concert entier, les
   vignettes de la liste, et la fenêtre zoomable de la carte d'édition. Elles
   diffèrent par la taille et par ce qu'on superpose, pas par la façon de
   dessiner une forme d'onde. */

import type { Segment } from './api'

export interface Palette {
  wave: string
  bed: string
  gapWave: string
  gapBed: string
  handle: string
  cursor: string
  /** Ce qui se lit *sur* la poignée : elle est sombre en clair, claire en
      sombre, et les stries gravées dessus doivent suivre. */
  onHandle: string
  halo: string
  /** Voile posé sur ce que la loupe ne regarde pas, dans le ruban. */
  veil: string
}

// Relue une fois par thème. Un `getComputedStyle` par image de glissé se
// paierait en résolutions de style à quarante images par seconde, pour un
// résultat qui ne change qu'au clic sur la bascule.
let known: { theme: string; palette: Palette } | null = null

export function palette(): Palette {
  const theme = document.documentElement.dataset.theme ?? 'dark'
  if (known?.theme === theme) return known.palette
  const style = getComputedStyle(document.documentElement)
  const read = (name: string) => style.getPropertyValue(name).trim()
  const found: Palette = {
    wave: read('--wave'),
    bed: read('--wave-bed'),
    gapWave: read('--wave-gap'),
    gapBed: read('--wave-gap-bed'),
    handle: read('--handle'),
    cursor: read('--ink'),
    onHandle: read('--on-ink'),
    halo: read('--surface'),
    veil: read('--ribbon-veil'),
  }
  known = { theme, palette: found }
  return found
}

/** Cale le canvas sur la densité de l'écran, et rend son contexte.

    Sans ça, le tracé est flou sur tout écran à plus de 100 % — c'est-à-dire
    sur la plupart des portables, où l'on travaille. */
export function surface(canvas: HTMLCanvasElement): CanvasRenderingContext2D | null {
  const ratio = window.devicePixelRatio || 1
  const width = Math.max(1, Math.round(canvas.clientWidth * ratio))
  const height = Math.max(1, Math.round(canvas.clientHeight * ratio))
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width
    canvas.height = height
  }
  const context = canvas.getContext('2d')
  if (!context) return null
  context.setTransform(ratio, 0, 0, ratio, 0, 0)
  context.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight)
  return context
}

/** Le type du segment sous cet instant, pour colorer la colonne. */
function kindAt(segments: Segment[], moment: number): 'music' | 'gap' {
  // Recherche dichotomique : la liste est triée et le tracé pose la question
  // une fois par colonne, soit douze cents fois par image.
  let low = 0
  let high = segments.length - 1
  while (low <= high) {
    const middle = (low + high) >> 1
    const segment = segments[middle]
    if (moment < segment.start) high = middle - 1
    else if (moment >= segment.end) low = middle + 1
    else return segment.kind
  }
  return 'music'
}

export interface WaveOptions {
  heights: Float32Array
  /** Instant du premier point de `heights`, et pas du concert. */
  start: number
  /** Durée couverte par l'ensemble des points. */
  span: number
  segments: Segment[]
  palette: Palette
  /** Part de la demi-hauteur qu'occupe la crête la plus forte. */
  fill?: number
  radius?: number
}

export function paint(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  options: WaveOptions,
): void {
  const { heights, start, span, segments, palette: colours } = options
  const middle = height / 2
  const reach = middle * (options.fill ?? 0.92)
  const columns = heights.length
  if (!columns || span <= 0) return

  context.save()
  if (options.radius) {
    context.beginPath()
    context.roundRect(0, 0, width, height, options.radius)
    context.clip()
  }

  // Le lit d'abord, par plages de même type : c'est lui qui montre où sont les
  // applaudissements, y compris là où la crête est plate.
  let from = 0
  let kind = kindAt(segments, start)
  for (let column = 1; column <= columns; column += 1) {
    const here =
      column < columns ? kindAt(segments, start + ((column + 0.5) / columns) * span) : kind
    if (column < columns && here === kind) continue
    const x0 = (from / columns) * width
    const x1 = (column / columns) * width
    context.fillStyle = kind === 'music' ? colours.bed : colours.gapBed
    context.fillRect(x0, 0, x1 - x0, height)
    context.fillStyle = kind === 'music' ? colours.wave : colours.gapWave
    context.beginPath()
    context.moveTo(x0, middle)
    for (let index = from; index < column; index += 1) {
      const x = (index / columns) * width
      context.lineTo(x, middle - heights[index] * reach)
    }
    for (let index = column - 1; index >= from; index -= 1) {
      const x = (index / columns) * width
      context.lineTo(x, middle + heights[index] * reach)
    }
    context.closePath()
    context.fill()
    from = column
    kind = here
  }
  context.restore()
}

/** Découpe l'enveloppe entière sur une fenêtre, sans repasser par le serveur.

    C'est ce qui rend les vingt-cinq vignettes gratuites : elles sortent de
    l'enveloppe déjà reçue pour le ruban, et aucune n'ajoute d'entrée-sortie. */
export function slice(
  envelope: Float32Array,
  fps: number,
  start: number,
  span: number,
  columns: number,
): Float32Array {
  const out = new Float32Array(columns)
  if (!envelope.length || span <= 0) return out
  for (let column = 0; column < columns; column += 1) {
    const first = Math.floor((start + (column / columns) * span) * fps)
    const last = Math.max(first + 1, Math.floor((start + ((column + 1) / columns) * span) * fps))
    let peak = 0
    for (let index = Math.max(0, first); index < Math.min(last, envelope.length); index += 1) {
      if (envelope[index] > peak) peak = envelope[index]
    }
    out[column] = peak
  }
  return out
}

/** Silhouette d'un segment, pour une vignette de quatre-vingt-huit pixels.

    Trois choses la séparent du tracé principal, et chacune a sa raison.

    **La moyenne, et non la crête.** Une vignette de 88 colonnes sur un morceau
    de trois minutes couvre deux secondes et demie par colonne ; en musique, la
    crête de deux secondes et demie ne bouge pratiquement pas, et toutes les
    colonnes sortent à la même hauteur. C'est ce qui donnait un rectangle. La
    moyenne, elle, suit ce qu'on entend : un couplet est plus bas qu'un refrain.

    **L'amplitude, et non les décibels.** L'échelle en décibels range un morceau
    de concert entre −20 et −6 dB, soit entre 0,66 et 0,90 de la hauteur. Sur
    vingt-six pixels, six centièmes d'écart ne se voient pas.

    **Étirée sur la dynamique du morceau**, du plus bas au plus haut de ses
    propres colonnes. C'est là qu'on triche, et c'est assumé : la vignette ne
    dit rien de juste sur les niveaux absolus, et n'a pas à le faire. Elle sert
    à distinguer un morceau d'un autre du coin de l'œil, ce qu'un rectangle ne
    faisait pas. Le tracé de la carte d'édition, lui, reste en décibels — ce
    qu'on y voit est exactement ce sur quoi le détecteur a décidé.

    Un morceau dont le niveau ne bouge pas — un bourdon, une nappe — n'est pas
    étiré : sans ce garde-fou, on amplifierait son bruit de fond en zigzag et
    la vignette montrerait une agitation qui n'existe pas. Il retombe alors sur
    une simple mise à l'échelle, et reste franchement plat, ce qu'il est.

    Le plancher garde un corps visible là où le son se tait, plutôt qu'un
    trait interrompu. */
export function silhouette(
  envelope: Float32Array,
  fps: number,
  start: number,
  span: number,
  columns: number,
): Float32Array {
  const out = new Float32Array(columns)
  if (!envelope.length || span <= 0) return out

  let peak = 0
  for (let column = 0; column < columns; column += 1) {
    const from = Math.max(0, Math.floor((start + (column / columns) * span) * fps))
    const to = Math.min(
      envelope.length,
      Math.max(from + 1, Math.floor((start + ((column + 1) / columns) * span) * fps)),
    )
    let total = 0
    let count = 0
    for (let index = from; index < to; index += 1) {
      // `to_height` a posé −60 dBFS à 0 et 0 dBFS à 1 : on refait le chemin
      // inverse pour retrouver une amplitude, seule grandeur qui se moyenne.
      total += 10 ** ((envelope[index] * 60 - 60) / 20)
      count += 1
    }
    const mean = count ? total / count : 0
    out[column] = mean
    if (mean > peak) peak = mean
  }

  if (peak <= 0) return out

  let floor = Infinity
  for (let column = 0; column < columns; column += 1) {
    if (out[column] < floor) floor = out[column]
  }

  // Moins d'un dixième d'écart entre le plus fort et le plus faible : il n'y a
  // pas de relief à montrer, et l'étirement ne montrerait que du bruit.
  const flat = peak - floor < peak * 0.1
  const BODY = 0.16
  for (let column = 0; column < columns; column += 1) {
    const share = flat
      ? out[column] / peak
      : (out[column] - floor) / (peak - floor)
    out[column] = BODY + (1 - BODY) * Math.sqrt(Math.max(0, share))
  }
  return out
}

export function drawCursor(
  context: CanvasRenderingContext2D,
  x: number,
  height: number,
  colours: Palette,
): void {
  // Un liseré de la couleur de la surface sous le trait : sans lui, la tête
  // de lecture se perd dans le tracé quand elle tombe sur une crête.
  context.fillStyle = colours.halo
  context.fillRect(x - 1.5, 0, 3, height)
  context.fillStyle = colours.cursor
  context.fillRect(x - 0.5, 0, 1, height)
}

/** Les poignées de l'évolution A : deux prises franches, en haut et en bas.

    Le défaut de 2a était que les deux limites du morceau tombaient exactement
    sur les bords du tracé — impossible de les saisir, et on ne voyait jamais
    ce qu'il y avait de l'autre côté de la coupe. La vue s'élargit donc sur les
    blancs voisins, et les poignées tombent à l'intérieur. */
export function drawHandle(
  context: CanvasRenderingContext2D,
  x: number,
  height: number,
  colours: Palette,
  active: boolean,
): void {
  const grip = { w: 11, h: 26 }
  context.fillStyle = colours.handle
  context.fillRect(x - 1, 0, 2, height)
  context.globalAlpha = active ? 1 : 0.92
  roundRect(context, x - grip.w / 2, 0, grip.w, grip.h, 3)
  roundRect(context, x - grip.w / 2, height - grip.h, grip.w, grip.h, 3)
  context.globalAlpha = 1
  // Deux traits sur la prise : sans eux, le rectangle ne dit pas qu'il se
  // saisit — c'est la même convention que la poignée d'une fenêtre.
  context.fillStyle = colours.onHandle
  context.globalAlpha = 0.75
  for (const offset of [-2, 1]) {
    context.fillRect(x + offset, 8, 1, 10)
    context.fillRect(x + offset, height - 18, 1, 10)
  }
  context.globalAlpha = 1
}

function roundRect(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): void {
  context.beginPath()
  context.roundRect(x, y, width, height, radius)
  context.fill()
}
