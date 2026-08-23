<script lang="ts">
  /* Le segment sous la loupe, et ses deux coupes.

     C'est l'évolution A du canevas : la vue déborde de quinze secondes sur les
     blancs voisins. Dans 2a, la carte s'appelait « le morceau entier » et ses
     deux limites tombaient exactement sur les bords du tracé — impossible de
     les saisir, et on ne voyait jamais ce qu'il y a de l'autre côté de la
     coupe, c'est-à-dire les applaudissements, la seule chose qui permette de
     juger si elle tombe au bon endroit.

     Trois façons de corriger, par précision croissante : les poignées à la
     souris, la molette pour zoomer, les steppers au dixième de seconde. Plus
     « Caler sur l'attaque », qui ne devine rien — il rejoue le calcul que le
     détecteur fait déjà sur chacune de ses frontières. */
  import { session } from '../lib/session.svelte'
  import { api } from '../lib/api'
  import { hms, parseTime, tenths, trackLabel } from '../lib/format'
  import { drawCursor, drawHandle, paint, palette, surface, type Palette } from '../lib/wave'

  const STEP_S = 0.1

  let canvas = $state<HTMLCanvasElement>(null!)
  let colours: Palette | null = null
  let heights = $state<Float32Array>(new Float32Array(0))
  let width = $state(736)
  let dragging = $state<'start' | 'end' | null>(null)
  let preview = $state<{ edge: 'start' | 'end'; at: number } | null>(null)
  let pending = 0

  const segment = $derived(session.segment)
  /** Rang des deux frontières du segment regardé. −1 : le bord du concert. */
  const edges = $derived({
    start: (segment?.index ?? 0) - 1,
    end: segment ? segment.index : -1,
  })
  const lastEdge = $derived(session.segments.length - 2)

  function shown(edge: 'start' | 'end'): number {
    if (preview?.edge === edge) return preview.at
    return edge === 'start' ? (segment?.start ?? 0) : (segment?.end ?? 0)
  }

  function x(moment: number): number {
    return ((moment - session.viewStart) / session.viewSpan) * canvas.clientWidth
  }

  function at(clientX: number): number {
    const box = canvas.getBoundingClientRect()
    return session.viewStart + ((clientX - box.left) / box.width) * session.viewSpan
  }

  /** Va chercher les pics de la fenêtre visible.

      Le serveur décide seul de la source — l'enveloppe de l'analyse au-delà de
      quatre-vingt-dix secondes, les échantillons réels en deçà. Le navigateur
      n'a donc pas à savoir à quelle échelle il est. */
  async function fetchPeaks(): Promise<void> {
    if (!session.open || !canvas) return
    const columns = Math.max(1, Math.round(canvas.clientWidth))
    const mine = ++pending
    const { data } = await api.peaks(session.viewStart, session.viewSpan, columns)
    // Deux fenêtres demandées coup sur coup pendant un zoom : seule la
    // dernière compte, sinon le tracé revient en arrière au gré du réseau.
    if (mine === pending) heights = data
  }

  function draw(): void {
    if (!canvas || !segment) return
    const context = surface(canvas)
    if (!context) return
    colours ??= palette()
    const height = canvas.clientHeight
    paint(context, canvas.clientWidth, height, {
      heights,
      start: session.viewStart,
      span: session.viewSpan,
      segments: session.segments,
      palette: colours,
      radius: 8,
    })

    if (session.playhead >= session.viewStart &&
        session.playhead <= session.viewStart + session.viewSpan) {
      drawCursor(context, x(session.playhead), height, colours.cursor)
    }
    if (edges.start >= 0) {
      drawHandle(context, x(shown('start')), height, colours.handle, dragging === 'start')
    }
    if (edges.end >= 0 && edges.end <= lastEdge) {
      drawHandle(context, x(shown('end')), height, colours.handle, dragging === 'end')
    }
  }

  function grabbed(clientX: number): 'start' | 'end' | null {
    if (!segment) return null
    const near = (moment: number) => Math.abs(x(moment) - (clientX - canvas.getBoundingClientRect().left)) < 9
    if (edges.start >= 0 && near(segment.start)) return 'start'
    if (edges.end >= 0 && edges.end <= lastEdge && near(segment.end)) return 'end'
    return null
  }

  function onPointerDown(event: PointerEvent): void {
    const grip = grabbed(event.clientX)
    if (!grip) {
      session.seek(at(event.clientX))
      return
    }
    dragging = grip
    preview = { edge: grip, at: at(event.clientX) }
    canvas.setPointerCapture(event.pointerId)
  }

  function onPointerMove(event: PointerEvent): void {
    if (!dragging) {
      canvas.style.cursor = grabbed(event.clientX) ? 'ew-resize' : 'crosshair'
      return
    }
    preview = { edge: dragging, at: at(event.clientX) }
  }

  async function onPointerUp(event: PointerEvent): Promise<void> {
    if (!dragging) return
    const edge = dragging
    const moment = at(event.clientX)
    dragging = null
    canvas.releasePointerCapture(event.pointerId)
    const index = edge === 'start' ? edges.start : edges.end
    // Le tracé provisoire ne s'efface qu'une fois la réponse arrivée, qu'elle
    // accepte ou qu'elle refuse : l'effacer avant ferait sauter la frontière à
    // son ancienne place le temps d'un aller-retour.
    await session.edit(
      { op: 'move_boundary', index, moment },
      `Coupe déplacée à ${tenths(moment)}.`,
    )
    preview = null
  }

  function onWheel(event: WheelEvent): void {
    event.preventDefault()
    session.zoom(event.deltaY > 0 ? 1.25 : 0.8, at(event.clientX))
  }

  async function nudge(edge: 'start' | 'end', direction: number): Promise<void> {
    if (!segment) return
    const index = edge === 'start' ? edges.start : edges.end
    if (index < 0) return
    // Recalé sur le dixième : sans arrondi, vingt appuis laissent la coupe à
    // 217,299999997 s, et le champ finit par afficher un chiffre qui n'est pas
    // celui qu'on a demandé.
    const from = edge === 'start' ? segment.start : segment.end
    const moment = Math.round((from + direction * STEP_S) * 10) / 10
    await session.edit({ op: 'move_boundary', index, moment })
  }

  async function typed(edge: 'start' | 'end', event: Event): Promise<void> {
    const field = event.target as HTMLInputElement
    const moment = parseTime(field.value)
    const index = edge === 'start' ? edges.start : edges.end
    if (moment === null) {
      session.note('Horaire illisible. Attendu : 12:34, 1:02:14 ou 754.')
      field.value = tenths(edge === 'start' ? (segment?.start ?? 0) : (segment?.end ?? 0))
      return
    }
    if (index < 0) return
    await session.edit({ op: 'move_boundary', index, moment })
  }

  async function snap(edge: 'start' | 'end'): Promise<void> {
    const index = edge === 'start' ? edges.start : edges.end
    if (index < 0) return
    await session.edit({ op: 'refine_boundary', index }, 'Coupe calée sur l\'attaque.')
  }

  async function setKind(kind: 'music' | 'gap'): Promise<void> {
    if (!segment || segment.kind === kind) return
    await session.edit({ op: 'set_kind', index: segment.index, kind })
  }

  async function merge(): Promise<void> {
    if (edges.end < 0 || edges.end > lastEdge) {
      session.note('La fin du concert ne se fusionne pas.')
      return
    }
    await session.edit({ op: 'delete_boundary', index: edges.end }, 'Coupe supprimée.')
  }

  async function split(): Promise<void> {
    await session.edit(
      { op: 'split_here', moment: session.playhead },
      `Frontière posée à ${tenths(session.playhead)}.`,
    )
  }

  $effect(() => {
    void session.viewStart
    void session.viewSpan
    void session.state?.source
    void width
    void fetchPeaks()
  })

  $effect(() => {
    void heights
    void session.segments
    void session.playhead
    void session.selected
    void preview
    void dragging
    draw()
  })

  $effect(() => {
    const observer = new ResizeObserver(() => {
      width = canvas.clientWidth
    })
    observer.observe(canvas)
    return () => observer.disconnect()
  })
</script>

{#if segment}
  <div class="head">
    <div>
      <div class="mono kind">
        {segment.kind === 'music' ? `MORCEAU ${trackLabel(segment.number)}` : 'BLANC'}
      </div>
      <div class="name">{segment.trackTitle || 'Sans titre'}</div>
    </div>
    {#if segment.confidence}
      <span class="pill">confiance {Math.round(segment.confidence * 100)} %</span>
    {/if}
    <div class="fate">
      <button class:on={segment.kind === 'music'} onclick={() => setKind('music')}>
        Garder
      </button>
      <button class:on={segment.kind === 'gap'} onclick={() => setKind('gap')}>
        Supprimer
      </button>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <span class="label">
        {segment.kind === 'music' ? 'Le morceau, et ses deux coupes' : 'Le blanc, et ses deux coupes'}
      </span>
      <span class="hint">
        {hms(segment.end - segment.start)} · molette pour zoomer
      </span>
    </div>

    <canvas
      bind:this={canvas}
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      onwheel={onWheel}
      aria-label="Forme d'onde du segment"
    ></canvas>

    <div class="tools">
      {#each [['start', 'début'], ['end', 'fin']] as [edge, label] (edge)}
        <div class="stepper" class:off={(edge === 'start' ? edges.start : edges.end) < 0}>
          <button onclick={() => nudge(edge as 'start' | 'end', -1)} title="Reculer d'un dixième">
            −
          </button>
          <input
            class="mono"
            value={tenths(edge === 'start' ? segment.start : segment.end)}
            onchange={(event) => typed(edge as 'start' | 'end', event)}
          />
          <button onclick={() => nudge(edge as 'start' | 'end', 1)} title="Avancer d'un dixième">
            +
          </button>
        </div>
        <span class="edge">{label}</span>
        <button
          class="btn quiet snap"
          disabled={!session.state?.hasFeatures ||
            (edge === 'start' ? edges.start : edges.end) < 0}
          onclick={() => snap(edge as 'start' | 'end')}
          title="Rejouer le recalage du détecteur sur cette coupe"
        >
          Caler
        </button>
      {/each}

      <div class="spacer"></div>
      <button class="btn" onclick={merge}>Fusionner</button>
      <button class="btn accent" onclick={split}>Séparer ici</button>
    </div>
  </div>
{/if}

<style>
  .head {
    padding: 22px 26px 0;
    display: flex;
    align-items: flex-end;
    gap: 12px;
  }

  .kind {
    font-weight: 500;
    font-size: 11.5px;
    color: var(--ink-3);
  }

  .name {
    margin-top: 6px;
    font: 600 26px/1.2 var(--sans);
    letter-spacing: -0.015em;
    color: var(--ink);
    border-bottom: 2px solid var(--accent);
    display: inline-block;
    padding-bottom: 2px;
    max-width: 460px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .pill {
    font: 500 11px var(--sans);
    color: var(--accent);
    background: var(--accent-soft);
    border-radius: 20px;
    padding: 3px 10px;
    margin-bottom: 6px;
    white-space: nowrap;
  }

  .fate {
    margin-left: auto;
    display: flex;
    background: var(--rule);
    border-radius: var(--radius);
    padding: 3px;
    margin-bottom: 4px;
  }

  .fate button {
    height: 28px;
    padding: 0 14px;
    border-radius: 6px;
    font: 500 12.5px var(--sans);
    color: var(--ink-2);
  }

  .fate button.on {
    background: var(--accent);
    color: #fff;
  }

  .card {
    margin: 18px 26px 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    padding: 14px;
    box-shadow: var(--shadow);
  }

  .card-head {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }

  .card-head .hint {
    margin-left: auto;
  }

  canvas {
    display: block;
    width: 100%;
    height: 150px;
    border-radius: 8px;
    cursor: crosshair;
    touch-action: none;
  }

  .tools {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 14px;
    flex-wrap: wrap;
  }

  .stepper {
    display: flex;
    align-items: center;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }

  .stepper.off {
    opacity: 0.4;
    pointer-events: none;
  }

  .stepper button {
    width: 32px;
    height: 32px;
    color: var(--ink-2);
    font-size: 15px;
    line-height: 1;
  }

  .stepper button:hover {
    background: var(--rule);
  }

  .stepper input {
    width: 78px;
    height: 32px;
    padding: 0 6px;
    border: 0;
    border-left: 1px solid var(--border);
    border-right: 1px solid var(--border);
    font: 500 13px var(--mono);
    text-align: center;
    outline: none;
    background: none;
  }

  .edge {
    font: 400 12px var(--sans);
    color: var(--ink-3);
  }

  .snap {
    height: 26px;
    padding: 0 9px;
    font-size: 11.5px;
  }

  .spacer {
    margin-left: auto;
  }
</style>
