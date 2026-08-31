/* Le tracé, en canvas impératif.

   Trois vues, une seule fonction de peinture : le ruban du concert entier, les
   vignettes de la liste, et la fenêtre zoomable de la carte d'édition.
*/

import type { Segment } from './api'

export interface Palette {
  wave: string
  bed: string
  gapWave: string
  gapBed: string
  handle: string
  handleActive: string
  cursor: string
  onHandle: string
  halo: string
  veil: string
}

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
    handleActive: read('--handle-active') || read('--accent'),
    cursor: read('--cursor') || (theme === 'dark' ? '#ffffff' : '#0f172a'),
    onHandle: read('--on-ink'),
    halo: read('--cursor-halo') || read('--surface'),
    veil: read('--ribbon-veil'),
  }
  known = { theme, palette: found }
  return found
}

/** Cale le canvas sur la densité de l'écran, et rend son contexte. */
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
  start: number
  span: number
  segments: Segment[]
  palette: Palette
  fill?: number
  radius?: number
  showCenterLine?: boolean
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

  // Le lit d'abord, par plages de même type
  let from = 0
  let kind = kindAt(segments, start)
  for (let column = 1; column <= columns; column += 1) {
    const here =
      column < columns ? kindAt(segments, start + ((column + 0.5) / columns) * span) : kind
    if (column < columns && here === kind) continue
    const x0 = (from / columns) * width
    const x1 = (column / columns) * width
    
    // Fond de zone
    context.fillStyle = kind === 'music' ? colours.bed : colours.gapBed
    context.fillRect(x0, 0, x1 - x0, height)
    
    // Onde
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

  // Ligne de centre en filigrane pour les cartes d'édition
  if (options.showCenterLine !== false && height > 60) {
    context.strokeStyle = colours.halo
    context.globalAlpha = 0.35
    context.lineWidth = 1
    context.beginPath()
    context.moveTo(0, Math.round(middle) + 0.5)
    context.lineTo(width, Math.round(middle) + 0.5)
    context.stroke()
    context.globalAlpha = 1
  }

  context.restore()
}

/** Découpe l'enveloppe entière sur une fenêtre. */
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

/** Silhouette d'un segment, pour une vignette. */
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

  const flat = peak - floor < peak * 0.1
  const BODY = 0.18
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
  // Liseré halo sous le trait pour détacher la tête de lecture
  context.fillStyle = colours.halo
  context.fillRect(x - 2, 0, 4, height)

  // Marqueur triangulaire en tête avec halo
  context.beginPath()
  context.moveTo(x - 5, 0)
  context.lineTo(x + 5, 0)
  context.lineTo(x, 7)
  context.closePath()
  context.fillStyle = colours.halo
  context.fill()

  // Trait blanc principal
  context.fillStyle = colours.cursor
  context.fillRect(x - 1, 0, 2, height)

  context.beginPath()
  context.moveTo(x - 3.5, 0)
  context.lineTo(x + 3.5, 0)
  context.lineTo(x, 5.5)
  context.closePath()
  context.fillStyle = colours.cursor
  context.fill()
}

/** Poignées de découpe interactives */
export function drawHandle(
  context: CanvasRenderingContext2D,
  x: number,
  height: number,
  colours: Palette,
  active: boolean,
): void {
  const grip = { w: 12, h: 28 }
  const handleColor = active ? colours.handleActive : colours.handle

  // Ligne verticale sur toute la hauteur
  context.fillStyle = active ? colours.handleActive : colours.handle
  context.fillRect(x - 1, 0, 2, height)

  // Poignées haute et basse arrondies
  context.fillStyle = handleColor
  roundRect(context, x - grip.w / 2, 0, grip.w, grip.h, 4)
  roundRect(context, x - grip.w / 2, height - grip.h, grip.w, grip.h, 4)

  // Stries de préhension
  context.fillStyle = colours.onHandle
  context.globalAlpha = active ? 0.95 : 0.75
  for (const offset of [-2.5, 1.5]) {
    context.fillRect(x + offset, 8, 1.2, 12)
    context.fillRect(x + offset, height - 20, 1.2, 12)
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

