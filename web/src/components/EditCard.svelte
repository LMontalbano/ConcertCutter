<script lang="ts">
  /* Le segment sous la loupe, et ses deux coupes.

     C'est l'évolution A du canevas : la vue déborde de quinze secondes sur les
     blancs voisins. Dans 2a, la carte s'appelait « le morceau entier » et ses
     deux limites tombaient exactement sur les bords du tracé — impossible de
     les saisir, et on ne voyait jamais ce qu'il y a de l'autre côté de la
     coupe, c'est-à-dire les applaudissements, la seule chose qui permette de
     juger si elle tombe au bon endroit.

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
  let dragging = $state<'start' | 'end' | null>(null)
  let preview = $state<{ edge: 'start' | 'end'; at: number } | null>(null)
  let renaming = $state(false)
  let draft = $state('')
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
    grab(event.pointerId, false)
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
    await session.edit(
      { op: 'set_title', index: segment.index, title: draft },
      'Titre enregistré.',
    )
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
    void session.state?.source
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
    void fetchPeaks()
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
      {#if renaming}
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="name typing"
          bind:value={draft}
          onblur={rename}
          onkeydown={onTitleKey}
          autofocus
          placeholder="Sans titre"
          aria-label="Titre du morceau"
        />
      {:else}
        <button
          class="name"
          class:empty={!segment.trackTitle}
          onclick={startRename}
          disabled={segment.kind !== 'music'}
          title={segment.kind === 'music' ? 'Cliquer pour nommer' : "Un blanc ne se nomme pas"}
        >
          {segment.trackTitle || 'Sans titre'}
        </button>
      {/if}
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
      <!-- Chaque borne forme un groupe nommé, son libellé au-dessus de son
           champ. Les libellés suivaient leur champ et précédaient le bouton
           suivant, si bien qu'on lisait « début » comme l'étiquette de ce qui
           venait après. -->
      {#each [['start', 'Début'], ['end', 'Fin']] as [edge, label] (edge)}
        {@const index = edge === 'start' ? edges.start : edges.end}
        {@const fixed = index < 0 || index > lastEdge}
        <div class="edge" class:off={fixed}>
          <span class="label">{label}</span>
          <div class="row">
            <div class="stepper">
              <button
                onclick={() => nudge(edge as 'start' | 'end', -1)}
                title="Reculer d'une demi-seconde"
                aria-label="{label} : reculer d'une demi-seconde"
              >
                −
              </button>
              <input
                class="mono"
                value={tenths(edge === 'start' ? segment.start : segment.end)}
                onchange={(event) => typed(edge as 'start' | 'end', event)}
                aria-label="{label} du segment"
              />
              <button
                onclick={() => nudge(edge as 'start' | 'end', 1)}
                title="Avancer d'une demi-seconde"
                aria-label="{label} : avancer d'une demi-seconde"
              >
                +
              </button>
            </div>
          </div>
        </div>
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
    flex: none;
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
    border: 0;
    border-bottom: 2px solid var(--accent);
    display: inline-block;
    padding: 0 0 2px;
    max-width: 460px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: left;
    background: none;
  }

  .name.empty {
    color: var(--hint);
    font-weight: 500;
  }

  button.name:hover:not(:disabled) {
    border-bottom-color: var(--ink);
  }

  button.name:disabled {
    opacity: 1;
    border-bottom-color: var(--gap-rule);
  }

  input.name.typing {
    outline: none;
    min-width: 320px;
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
    color: var(--on-accent);
  }

  /* La carte prend la hauteur qui reste, et le tracé la remplit : elle était
     haute de son contenu — cent cinquante pixels de tracé — et laissait sous
     elle un vide qui grandissait avec la fenêtre.

     Plafonnée tout de même. Au-delà d'environ sept cents pixels la hauteur
     n'apprend plus rien sur une attaque, et le morceau devient un mur de
     couleur. Ce qui reste au-delà se pose sous la carte, en marge, plutôt
     qu'entre le tracé et ses commandes. */
  .card {
    margin: 18px 26px 22px;
    flex: 1;
    min-height: 0;
    max-height: 700px;
    display: flex;
    flex-direction: column;
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
    flex: none;
  }

  .card-head .hint {
    margin-left: auto;
  }

  canvas {
    display: block;
    width: 100%;
    flex: 1;
    min-height: 170px;
    border-radius: 8px;
    cursor: crosshair;
    touch-action: none;
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
    gap: 5px;
  }

  .edge.off {
    opacity: 0.4;
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
    overflow: hidden;
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
    /* Assez large pour « 1:14:00,0 ». À soixante-dix-huit pixels, le dixième
       d'un concert de plus d'une heure passait sous le bord droit. */
    width: 118px;
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

  .spacer {
    margin-left: auto;
  }
</style>
