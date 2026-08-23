<script lang="ts">
  /* La colonne de gauche : les morceaux, et les blancs entre eux.

     Chaque ligne porte son numéro, son titre, ses bornes et une vignette de
     forme d'onde — découpée dans l'enveloppe déjà reçue pour le ruban, donc
     gratuite en entrées-sorties.

     Les blancs sont des lignes à part entière, plus basses et d'une autre
     teinte. Ce ne sont pas des séparateurs décoratifs : ce sont les
     applaudissements, et « garder » les recolle au morceau voisin. */
  import { session } from '../lib/session.svelte'
  import { hms, duration as spell, trackLabel } from '../lib/format'
  import { paint, palette, silhouette, surface, type Palette } from '../lib/wave'
  import type { Segment } from '../lib/api'

  const THUMB = { width: 88, height: 26 }

  let colours: Palette = palette()
  let editing = $state(-1)
  let draft = $state('')

  /* Le paramètre de l'action porte tout ce dont la vignette dépend, parce que
     c'est lui qui décide des repeintes.

     L'enveloppe surtout : elle arrive quelques secondes après la liste, et
     sans elle dans le paramètre, les vignettes restaient telles qu'elles
     avaient été peintes avant son arrivée — c'est-à-dire plates. C'était là
     l'origine des « rectangles ».

     Et le thème, sans quoi vingt-cinq vignettes garderaient leur lit sombre
     sur fond clair. */
  function thumb(
    canvas: HTMLCanvasElement,
    at: { segment: Segment; theme: string; envelope: Float32Array },
  ) {
    let segment = at.segment
    const render = () => {
      const context = surface(canvas)
      if (!context) return
      colours = palette()
      const span = Math.max(0.1, segment.end - segment.start)
      paint(context, canvas.clientWidth, canvas.clientHeight, {
        // `silhouette` et non `slice` : la crête d'une colonne de deux
        // secondes ne bouge pas en musique, et les vignettes sortaient toutes
        // en rectangle plein.
        heights: silhouette(
          session.envelope,
          session.envelopeFps,
          segment.start,
          span,
          THUMB.width,
        ),
        start: segment.start,
        span,
        segments: [segment],
        palette: colours,
        fill: 0.92,
        radius: 3,
      })
    }
    render()
    return {
      update(next: { segment: Segment; theme: string; envelope: Float32Array }) {
        segment = next.segment
        render()
      },
    }
  }

  function startEdit(segment: Segment): void {
    // Le simple clic lance le morceau ; le double clic vient le nommer, et
    // taper un titre par-dessus le son qu'on vient de déclencher serait
    // pénible.
    session.stop()
    editing = segment.index
    draft = segment.trackTitle
  }

  async function commit(): Promise<void> {
    const index = editing
    editing = -1
    if (index < 0) return
    const segment = session.segments[index]
    if (!segment || draft.trim() === segment.trackTitle) return
    await session.edit({ op: 'set_title', index, title: draft }, 'Titre enregistré.')
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === 'Enter') (event.target as HTMLInputElement).blur()
    if (event.key === 'Escape') {
      editing = -1
      ;(event.target as HTMLInputElement).blur()
    }
  }

  let rows: HTMLDivElement

  /* La liste suit la sélection. Cliquer dans le ruban ou déplacer la tête de
     lecture change le morceau regardé ; la ligne correspondante restait hors
     de vue, et il fallait la chercher à la molette pour retrouver où l'on en
     était. `nearest` ne fait rien quand elle est déjà visible : la liste ne
     saute pas sous les doigts de qui la parcourt. */
  $effect(() => {
    const index = session.selected
    const row = rows?.querySelector<HTMLElement>(`[data-rank="${index}"]`)
    if (!row || !rows) return
    const line = row.getBoundingClientRect()
    const frame = rows.getBoundingClientRect()
    // Rien tant qu'elle est déjà sous les yeux : la liste ne saute pas sous
    // les doigts de qui la parcourt. Sinon on la ramène au milieu, et non au
    // plus court — `nearest` la collait au bord bas, d'où l'on ne voit pas ce
    // qui suit.
    if (line.top >= frame.top && line.bottom <= frame.bottom) return
    row.scrollIntoView({ block: 'center' })
  })

  async function keep(segment: Segment): Promise<void> {
    await session.edit(
      { op: 'toggle_kind', index: segment.index },
      segment.kind === 'gap' ? 'Blanc conservé.' : 'Segment écarté.',
    )
  }
</script>

<aside>
  <header>
    <span class="label">
      {session.counts.tracks} morceaux · {session.counts.gaps} blancs
    </span>
  </header>

  <div class="rows" bind:this={rows}>
    {#each session.segments as segment (segment.index)}
      {#if segment.kind === 'music'}
        <div
          class="track"
          data-rank={segment.index}
          class:current={session.selected === segment.index}
          role="button"
          tabindex="0"
          aria-label="Morceau {trackLabel(segment.number)}{segment.trackTitle
            ? `, ${segment.trackTitle}`
            : ''}"
          onclick={() => session.select(segment.index)}
          onkeydown={(event) => event.key === 'Enter' && session.select(segment.index)}
        >
          <button
            class="listen"
            class:sounding={session.playing_at(segment.index)}
            onclick={(event) => (event.stopPropagation(), session.play(segment.index))}
            aria-label="{session.playing_at(segment.index)
              ? 'Arrêter'
              : 'Écouter'} le morceau {trackLabel(segment.number)}"
            title={session.playing_at(segment.index) ? 'Arrêter' : 'Écouter ce morceau'}
          >
            {session.playing_at(segment.index) ? '❚❚' : '▶'}
          </button>
          <span class="mono number">{trackLabel(segment.number)}</span>
          <div class="body">
            {#if editing === segment.index}
              <!-- svelte-ignore a11y_autofocus -->
              <input
                class="title"
                bind:value={draft}
                onblur={commit}
                onkeydown={onKey}
                autofocus
                placeholder="Sans titre"
              />
            {:else}
              <button
                class="title"
                class:empty={!segment.trackTitle}
                ondblclick={() => startEdit(segment)}
                onclick={() => session.select(segment.index)}
                title="Double-cliquer pour nommer"
              >
                {segment.trackTitle || 'Sans titre'}
              </button>
            {/if}
            <div class="mono times">
              {hms(segment.start)} → {hms(segment.end)} · {spell(segment.end - segment.start)}
            </div>
          </div>
          <canvas
            use:thumb={{ segment, theme: session.theme, envelope: session.envelope }}
            style="width:{THUMB.width}px;height:{THUMB.height}px"
          ></canvas>
        </div>
      {:else}
        <div
          class="gap"
          data-rank={segment.index}
          class:current={session.selected === segment.index}
          role="button"
          tabindex="0"
          aria-label="Blanc de {spell(segment.end - segment.start)}"
          onclick={() => session.select(segment.index)}
          onkeydown={(event) => event.key === 'Enter' && session.select(segment.index)}
        >
          <button
            class="listen thin"
            class:sounding={session.playing_at(segment.index)}
            onclick={(event) => (event.stopPropagation(), session.play(segment.index))}
            aria-label="Écouter ce blanc"
            title="Écouter ce blanc"
          >
            {session.playing_at(segment.index) ? '❚❚' : '▶'}
          </button>
          <span class="mono">blanc {spell(segment.end - segment.start)}</span>
          <button class="keep" onclick={(event) => (event.stopPropagation(), keep(segment))}>
            garder
          </button>
        </div>
      {/if}
    {/each}
  </div>
</aside>

<style>
  aside {
    /* Quatre cents pixels sur un écran de portable, un peu plus sur un grand :
       la colonne porte des titres, et un titre coupé au milieu ne se lit pas
       mieux parce que l'écran est large. */
    width: clamp(400px, 24%, 560px);
    flex: none;
    border-right: 1px solid var(--border);
    background: var(--surface);
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  header {
    display: flex;
    align-items: center;
    height: 42px;
    padding: 0 18px;
    border-bottom: 1px solid var(--border);
    flex: none;
  }

  .rows {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
  }

  /* Un rond de lecture par ligne. Sélectionner et écouter n'en faisaient
     qu'un : parcourir la liste pour regarder les découpes déclenchait le son
     vingt-cinq fois de suite. Ce sont deux intentions différentes, et elles
     ont maintenant deux cibles différentes. */
  /* Même diamètre pour un morceau et pour un blanc : les deux ronds ne
     faisaient pas la même taille, si bien que leurs centres — et donc la
     colonne qu'ils dessinent le long de la liste — se décalaient de trois
     pixels d'une ligne à l'autre. */
  .listen {
    flex: none;
    width: 24px;
    height: 24px;
    border-radius: 12px;
    display: grid;
    place-items: center;
    font-size: 8px;
    color: var(--ink-2);
    border: 1px solid var(--border);
    background: var(--surface);
  }

  /* Le survol annonce ce que le clic va donner : la même teinte que le rond
     en train de jouer. Il empruntait l'encre, c'est-à-dire presque blanc en
     thème sombre — un aplat qui n'avait rapport ni avec la lecture ni avec le
     reste de la ligne. */
  .listen:hover {
    color: var(--on-accent);
    background: var(--accent);
    border-color: var(--accent);
  }

  .listen.sounding {
    color: var(--on-accent);
    background: var(--accent);
    border-color: var(--accent);
  }

  /* Le rond d'un blanc emprunte la teinte des blancs. Il était en encre
     sourdine sur un fond déjà brun : la pause s'y devinait plus qu'elle ne s'y
     lisait, et c'est justement sur les segments qu'on écarte qu'on réécoute le
     plus. Fond plein plutôt que transparent, pour la même raison. */
  .listen.thin {
    font-size: 7px;
    color: var(--gap);
    border-color: var(--gap-rule);
    background: var(--surface);
  }

  .listen.thin:hover {
    color: var(--on-ink);
    background: var(--gap);
    border-color: var(--gap);
  }


  .listen.thin.sounding {
    color: var(--on-ink);
    background: var(--gap);
    border-color: var(--gap);
  }

  .track {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 13px 16px;
    border-bottom: 1px solid var(--rule);
    border-left: 3px solid transparent;
    cursor: default;
  }

  .track:hover {
    background: var(--hover);
  }

  .track.current {
    background: var(--accent-soft);
    border-left-color: var(--accent);
  }

  .number {
    width: 22px;
    font-weight: 500;
    font-size: 13px;
    color: var(--ink-3);
  }

  .track.current .number {
    color: var(--accent);
  }

  .body {
    flex: 1;
    min-width: 0;
  }

  .title {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0;
    font: 500 13.5px var(--sans);
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .track.current .title {
    font-weight: 600;
  }

  .title.empty {
    color: var(--hint);
    font-weight: 400;
  }

  input.title {
    border: 1px solid var(--accent);
    border-radius: 5px;
    padding: 1px 5px;
    margin: -2px -6px;
    background: var(--surface);
    outline: none;
  }

  .times {
    margin-top: 4px;
    font-size: 11.5px;
    color: var(--ink-3);
    white-space: nowrap;
  }

  canvas {
    flex: none;
    border-radius: 3px;
  }

  .gap {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--rule);
    border-left: 3px solid transparent;
    background: var(--gap-row);
    font-size: 11.5px;
    color: var(--gap);
    cursor: default;
  }

  .gap.current {
    border-left-color: var(--gap);
  }

  .keep {
    margin-left: auto;
    font: 500 11.5px var(--sans);
    color: var(--ink-2);
    padding: 2px 6px;
    border-radius: 5px;
  }

  .keep:hover {
    background: var(--surface);
    color: var(--ink);
  }
</style>
