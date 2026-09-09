<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  /* Le segment sous la loupe, et ses deux coupes.

     C'est l'évolution A du canevas : la vue déborde de quinze secondes sur les
     zones à retirer voisines. Dans 2a, la carte s'appelait « le morceau
     entier » et ses deux limites tombaient exactement sur les bords du tracé —
     impossible de les saisir, et on ne voyait jamais ce qu'il y a de l'autre
     côté de la coupe, c'est-à-dire les applaudissements, la seule chose qui
     permette de juger si elle tombe au bon endroit.

     Trois façons de corriger, par précision croissante : les poignées à la
     souris, la molette pour zoomer, les steppers d'une demi-seconde — et la
     frappe au clavier dans le champ, pour qui veut le dixième. */
  import { session } from '../lib/session.svelte'
  import { api } from '../lib/api'
  import { hms, parseTime, tenths, trackLabel } from '../lib/format'
  import {
    drawCursor, drawHandle, paint, palette, slice, surface, type Palette,
  } from '../lib/wave'

  // Une demi-seconde par appui. Le dixième était plus fin que le geste : caler
  // une coupe à l'oreille demande de bouger d'une demi-seconde, et il en
  // fallait cinq clics. La frappe au clavier reste au dixième, pour qui veut
  // la précision.
  const STEP_S = 0.5

  let canvas = $state<HTMLCanvasElement>(null!)
  let colours: Palette = palette()
  let heights = $state<Float32Array>(new Float32Array(0))
  let width = $state(736)
  let dragging = $state<'start' | 'end' | 'playhead' | null>(null)
  let pointer = $state<{ x: number; y: number } | null>(null)
  let gesture: {
    pointerId: number; clientX: number; moment: number;
    index: number; selected: number; segments: typeof session.segments;
  } | null = null
  let preview = $state<{ edge: 'start' | 'end'; at: number } | null>(null)
  let renaming = $state(false)
  let draft = $state('')
  let pending = 0
  let peaksController: AbortController | null = null

  const segment = $derived(session.segment)
  /** Rang des deux frontières du segment regardé. −1 : le bord du concert. */
  const edges = $derived({
    start: (segment?.index ?? 0) - 1,
    end: segment ? segment.index : -1,
  })
  const lastEdge = $derived(session.segments.length - 2)
  const cursor = $derived.by(() => {
    if (dragging) return dragging === 'playhead' ? 'grabbing' : 'ew-resize'
    const target = pointer ? targetAt(pointer.x, pointer.y) : null
    return target === 'playhead' ? 'grab' : target ? 'ew-resize' : 'crosshair'
  })

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
  async function fetchPeaks(signal: AbortSignal): Promise<void> {
    if (!session.open || !canvas) return
    const columns = Math.max(1, Math.round(canvas.clientWidth))
    const mine = ++pending
    const start = session.viewStart
    const span = session.viewSpan
    try {
      const { data } = await api.peaks(start, span, columns, signal)
      // Deux fenêtres demandées coup sur coup pendant un zoom : seule la
      // dernière compte, sinon le tracé revient en arrière au gré du réseau.
      if (mine === pending) heights = data
    } catch (failure) {
      if (failure instanceof DOMException && failure.name === 'AbortError') return
      session.note(t('ui.the_detailed_waveform_could_not_be_loaded'))
    }
  }

  function draw(): void {
    if (!canvas || !segment) return
    const context = surface(canvas)
    if (!context) return
    colours = palette()
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
      drawCursor(context, x(session.playhead), height, colours)
    }
    if (edges.start >= 0) {
      drawHandle(context, x(shown('start')), height, colours, dragging === 'start')
    }
    if (edges.end >= 0 && edges.end <= lastEdge) {
      drawHandle(context, x(shown('end')), height, colours, dragging === 'end')
    }
  }

  function targetAt(clientX: number, clientY: number): 'start' | 'end' | 'playhead' | null {
    if (!segment || !canvas) return null
    const box = canvas.getBoundingClientRect()
    const y = clientY - box.top
    const px = clientX - box.left
    if (px < 0 || px > box.width || y < 0 || y > box.height) return null
    const distance = (moment: number) => Math.abs(x(moment) - px)
    let edge: 'start' | 'end' | null = null
    let nearest = 9
    for (const candidate of ['start', 'end'] as const) {
      const index = edges[candidate]
      if (index < 0 || index > lastEdge) continue
      const gap = distance(shown(candidate))
      if (gap < nearest) {
        edge = candidate
        nearest = gap
      }
    }
    // Les frontières se saisissent sur toute leur hauteur. En cas de
    // superposition, les poignées restent réservées à la coupe ; au milieu,
    // le trait le plus proche gagne, avec priorité à la lecture à égalité.
    if (edge && (y <= 28 || y >= canvas.clientHeight - 28)) return edge
    if (session.playhead >= session.viewStart &&
        session.playhead <= session.viewStart + session.viewSpan &&
        distance(session.playhead) < 9 && distance(session.playhead) <= nearest) {
      return 'playhead'
    }
    return edge
  }

  function onPointerDown(event: PointerEvent): void {
    if (event.button !== 0 || gesture || !segment) return
    event.preventDefault()
    pointer = { x: event.clientX, y: event.clientY }
    const target = targetAt(event.clientX, event.clientY)
    const grip = target === 'playhead' ? null : target
    dragging = grip ?? 'playhead'
    gesture = {
      pointerId: event.pointerId, clientX: event.clientX,
      moment: grip ? segment[grip] : at(event.clientX),
      index: grip ? edges[grip] : -1,
      selected: session.selected, segments: session.segments,
    }
    session.pinned = true
    if (!grip) {
      // `scrub` et non `seek` : écouter la zone à retirer voisine, montrée
      // exprès aux deux bouts de la carte, ne doit pas recadrer la vue
      // dessus. Voir la note de `Session.scrub`.
      session.scrub(at(event.clientX))
    }
    grab(event.pointerId, true)
  }

  /** Prend ou rend le pointeur, sans faire échouer le glissé si ça rate.

      La capture n'est qu'un confort : elle permet de sortir du canevas en
      tirant. Quand elle échoue — un pointeur déjà relâché, un événement qui ne
      vient pas d'une vraie souris — une exception non rattrapée interrompait
      `onPointerUp` avant l'enregistrement, et la coupe revenait à sa place
      sans un mot. Le geste doit aboutir même sans capture. */
  function grab(pointerId: number, take: boolean): void {
    try {
      if (take) canvas.setPointerCapture(pointerId)
      else canvas.releasePointerCapture(pointerId)
    } catch {
      /* sans capture, le glissé marche encore tant qu'on reste sur le tracé */
    }
  }

  function onPointerMove(event: PointerEvent): void {
    pointer = { x: event.clientX, y: event.clientY }
    if (!dragging || !gesture) {
      return
    }
    if (event.pointerId !== gesture.pointerId) return
    if (dragging === 'playhead') session.scrub(at(event.clientX))
    else if (Math.abs(event.clientX - gesture.clientX) >= 3) {
      preview = { edge: dragging, at: boundaryAt(event.clientX) }
    }
  }

  function boundaryAt(clientX: number): number {
    return gesture!.moment + at(clientX) - at(gesture!.clientX)
  }

  function onPointerCancel(event: PointerEvent): void {
    if (event.pointerId !== gesture?.pointerId) return
    dragging = null
    gesture = null
    preview = null
    grab(event.pointerId, false)
  }

  async function onPointerUp(event: PointerEvent): Promise<void> {
    if (!dragging || !gesture || event.pointerId !== gesture.pointerId) return
    pointer = { x: event.clientX, y: event.clientY }
    const edge = dragging
    const origin = gesture
    const moment = edge === 'playhead' ? at(event.clientX) : boundaryAt(event.clientX)
    dragging = null
    gesture = null
    grab(event.pointerId, false)
    if (edge === 'playhead') {
      session.scrub(moment)
      return
    }
    // Un clic sans glissé ne modifie rien. Si le segment a changé pendant le
    // geste, aucune coupe du nouveau segment ne doit recevoir ce déplacement.
    if (Math.abs(event.clientX - origin.clientX) < 3 ||
        session.selected !== origin.selected || session.segments !== origin.segments) {
      preview = null
      return
    }
    // Le tracé provisoire ne s'efface qu'une fois la réponse arrivée, qu'elle
    // accepte ou qu'elle refuse : l'effacer avant ferait sauter la frontière à
    // son ancienne place le temps d'un aller-retour.
    await session.edit({ op: 'move_boundary', index: origin.index, moment })
    preview = null
  }

  function onWheel(event: WheelEvent): void {
    event.preventDefault()
    if (dragging) return
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
      session.note(t('ui.invalid_time_use_12_34_1_02_14'))
      field.value = tenths(edge === 'start' ? (segment?.start ?? 0) : (segment?.end ?? 0))
      return
    }
    if (index < 0) return
    await session.edit({ op: 'move_boundary', index, moment })
  }

  /* Nommer depuis la carte, et non plus seulement depuis la liste. Le titre
     est ce qu'on décide en écoutant le morceau, c'est-à-dire ici — aller le
     chercher dans la colonne de gauche demandait de quitter des yeux ce qu'on
     était en train de juger. Le serveur écrit en tête de la suite, si bien
     qu'on peut nommer depuis n'importe quel segment du morceau. */
  function startRename(): void {
    if (!segment || segment.kind !== 'music') return
    draft = segment.trackTitle
    renaming = true
  }

  async function rename(): Promise<void> {
    if (!renaming || !segment) return
    renaming = false
    if (draft.trim() === segment.trackTitle) return
    await session.edit({ op: 'set_title', index: segment.index, title: draft })
  }

  function onTitleKey(event: KeyboardEvent): void {
    if (event.key === 'Enter') (event.target as HTMLInputElement).blur()
    if (event.key === 'Escape') {
      renaming = false
      ;(event.target as HTMLInputElement).blur()
    }
  }

  async function setKind(kind: 'music' | 'gap'): Promise<void> {
    if (!segment || segment.kind === kind) return
    await session.edit({ op: 'set_kind', index: segment.index, kind })
  }

  async function merge(): Promise<void> {
    if (edges.end < 0 || edges.end > lastEdge) {
      session.note(t('ui.the_end_of_the_concert_cannot_be_merged'))
      return
    }
    await session.edit({ op: 'delete_boundary', index: edges.end })
  }

  async function split(): Promise<void> {
    await session.edit({ op: 'split_here', moment: session.playhead })
  }

  $effect(() => {
    void session.state?.source
    void session.viewStart
    void session.viewSpan
    void width
    const columns = Math.max(1, Math.round(canvas?.clientWidth ?? width))
    // Le tracé grossier d'abord, pris dans l'enveloppe déjà en mémoire ; les
    // vrais pics ensuite, quand le serveur les rend. Sans ce relais, changer
    // de morceau laissait pendant un aller-retour les pics de la fenêtre
    // précédente étirés sur la nouvelle — un tracé faux, brièvement, et
    // d'autant plus visible que les deux morceaux étaient de durées
    // différentes.
    if (session.envelope.length) {
      heights = slice(
        session.envelope, session.envelopeFps,
        session.viewStart, session.viewSpan, columns,
      )
    }
    peaksController?.abort()
    const controller = new AbortController()
    peaksController = controller
    const timer = window.setTimeout(() => void fetchPeaks(controller.signal), 90)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  })

  $effect(() => {
    // Le thème repeint : les couleurs du tracé sont lues au moment de
    // peindre, mais rien ne redemandait de peindre. Basculer en clair
    // laissait le lit des ondes en sombre jusqu'au geste suivant.
    void session.theme
    void heights
    void session.segments
    void session.playhead
    void session.selected
    void preview
    void dragging
    void width
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
    <div class="title-block">
      <div class="meta-row">
        <span class="badge {segment.kind === 'music' ? 'accent' : 'gap'}">
          {segment.kind === 'music'
            ? t('ui.track_value', { p0: trackLabel(segment.number) })
            : t('ui.section_to_remove_automatic_detection')}
        </span>
        {#if segment.confidence}
          <span class="badge">{t('ui.confidence')} {Math.round(segment.confidence * 100)} %
          </span>
        {/if}
      </div>

      {#if renaming}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="name typing"
          bind:value={draft}
          onblur={rename}
          onkeydown={onTitleKey}
          autofocus
          placeholder={t('ui.untitled')}
          aria-label={t('ui.track_title')}
        />
      {:else}
        <button
          class="name"
          class:empty={!segment.trackTitle}
          onclick={startRename}
          disabled={segment.kind !== 'music'}
          title={segment.kind === 'music'
            ? t('ui.click_to_name_this_track')
            : t('ui.sections_to_remove_cannot_be_named')}
        >
          <span>{segment.trackTitle || t('ui.untitled')}</span>
          {#if segment.kind === 'music'}
            <span class="edit-icon" aria-hidden="true">✎</span>
          {/if}
        </button>
      {/if}
    </div>

    <div class="fate-wrapper">
      <div class="fate" role="group" aria-label={t('ui.segment_action')}>
        <button class:on={segment.kind === 'music'} onclick={() => setKind('music')}>{t('ui.keep')}</button>
        <button class:on={segment.kind === 'gap'} onclick={() => setKind('gap')}>{t('ui.remove')}</button>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-head">
      <div class="card-title">
        <span class="label">
          {segment.kind === 'music' ? t('ui.track_boundaries') : t('ui.section_to_remove_boundaries')}
        </span>
        <span class="badge accent mono">{hms(segment.end - segment.start)}</span>
      </div>

      <div class="card-hints">
        <span class="hint">{t('ui.drag_playback_boundaries_trimming')}</span>
        <span class="hint"><span class="kbd">{t('ui.mouse_wheel')}</span>{t('ui.zoom')}</span>
        <!-- « c » en minuscule, parce que la majuscule désigne autre chose :
             `Maj+C` sépare le morceau en deux pistes là où `c` pose une simple
             coupe. Les afficher toutes deux en capitale renvoyait au mauvais
             geste. -->
        <span class="hint"><span class="kbd">c</span>{t('ui.split')}</span>
        <span class="hint"><span class="kbd">b</span>{t('ui.loop')}</span>
      </div>
    </div>

    <canvas
      bind:this={canvas}
      style:cursor
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerleave={() => (pointer = null)}
      onpointerup={onPointerUp}
      onpointercancel={onPointerCancel}
      onlostpointercapture={onPointerCancel}
      onwheel={onWheel}
      aria-label={t('ui.detailed_segment_waveform')}
    ></canvas>

    <div class="tools">
      {#each [['start', t('ui.section_start')], ['end', t('ui.section_end')]] as [edge, label] (edge)}
        {@const index = edge === 'start' ? edges.start : edges.end}
        {@const fixed = index < 0 || index > lastEdge}
        <div class="edge" class:off={fixed}>
          <span class="label">{label}</span>
          <div class="row">
            <div class="stepper">
              <button
                onclick={() => nudge(edge as 'start' | 'end', -1)}
                title={t('ui.move_back_half_a_second_0_5s')}
                aria-label={t('boundary.backward', { label })}
              >
                −
              </button>
              <input
                class="mono"
                value={tenths(edge === 'start' ? segment.start : segment.end)}
                onchange={(event) => typed(edge as 'start' | 'end', event)}
                aria-label={t('boundary.segment', { label })}
              />
              <button
                onclick={() => nudge(edge as 'start' | 'end', 1)}
                title={t('ui.move_forward_half_a_second_0_5s')}
                aria-label={t('boundary.forward', { label })}
              >
                +
              </button>
            </div>
          </div>
        </div>
      {/each}

      <div class="spacer"></div>
      <button class="btn" onclick={merge} title={t('ui.remove_the_end_boundary_and_merge')}>
        <span>{t('ui.merge')}</span>
      </button>
      <button class="btn accent" onclick={split} title={t('ui.add_a_boundary_at_the_playhead_c')}>
        <span>{t('ui.split_here')}</span>
      </button>
    </div>
  </div>
{/if}

<style>
  .head {
    padding: 24px 28px 0;
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
    flex: none;
  }

  .title-block {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }

  .meta-row {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .name {
    font: 700 24px/1.2 var(--sans);
    letter-spacing: -0.015em;
    color: var(--ink);
    border: 0;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 2px 0;
    max-width: 520px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: left;
    background: none;
    cursor: pointer;
  }

  .edit-icon {
    font-size: 14px;
    color: var(--ink-3);
    opacity: 0;
    transition: opacity 0.12s ease;
  }

  button.name:hover .edit-icon {
    opacity: 1;
    color: var(--accent);
  }

  .name.empty {
    color: var(--hint);
    font-weight: 500;
    font-style: italic;
  }

  button.name:disabled {
    cursor: default;
  }

  input.name.typing {
    outline: none;
    min-width: 340px;
    font: 700 24px/1.2 var(--sans);
    letter-spacing: -0.015em;
    color: var(--ink);
    background: var(--surface);
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    padding: 2px 8px;
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  .fate-wrapper {
    margin-bottom: 4px;
    flex: none;
  }

  .fate {
    display: flex;
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 3px;
    gap: 2px;
  }

  .fate button {
    height: 28px;
    padding: 0 14px;
    border-radius: 6px;
    font: 600 12.5px var(--sans);
    color: var(--ink-2);
    transition: all 0.12s ease;
  }

  .fate button:hover:not(.on) {
    color: var(--ink);
    background: var(--hover);
  }

  .fate button.on {
    background: var(--accent);
    color: var(--on-accent);
  }

  .card {
    margin: 16px 26px 20px;
    flex: 1;
    min-height: 0;
    max-height: 720px;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    padding: 16px;
    box-shadow: var(--shadow);
  }

  .card-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
    flex: none;
  }

  .card-title {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .card-hints {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  canvas {
    display: block;
    width: 100%;
    flex: 1;
    min-height: 180px;
    border-radius: 8px;
    cursor: crosshair;
    touch-action: none;
    border: 1px solid var(--border-subtle);
  }

  .tools {
    display: flex;
    align-items: flex-end;
    gap: 18px;
    margin-top: 16px;
    flex: none;
    flex-wrap: wrap;
  }

  .edge {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .edge.off {
    opacity: 0.35;
    pointer-events: none;
  }

  .edge .row {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .stepper {
    display: flex;
    align-items: center;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface-raised);
    overflow: hidden;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
  }

  .stepper button {
    width: 32px;
    height: 32px;
    color: var(--ink-2);
    font-size: 16px;
    font-weight: 600;
    line-height: 1;
    display: grid;
    place-items: center;
    transition: background 0.1s ease, color 0.1s ease;
  }

  .stepper button:hover {
    background: var(--hover);
    color: var(--ink);
  }

  .stepper input {
    width: 118px;
    height: 32px;
    padding: 0 6px;
    border: 0;
    border-left: 1px solid var(--border);
    border-right: 1px solid var(--border);
    font: 600 13px var(--mono);
    color: var(--ink);
    text-align: center;
    outline: none;
    background: var(--surface);
  }

  .stepper input:focus {
    box-shadow: inset 0 0 0 1px var(--accent);
  }

  .spacer {
    margin-left: auto;
  }
</style>
