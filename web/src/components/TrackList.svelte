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
  import { paint, palette, slice, surface, type Palette } from '../lib/wave'
  import type { Segment } from '../lib/api'

  const THUMB = { width: 88, height: 26 }

  let colours: Palette | null = null
  let editing = $state(-1)
  let draft = $state('')

  function thumb(canvas: HTMLCanvasElement, segment: Segment) {
    const render = () => {
      const context = surface(canvas)
      if (!context) return
      colours ??= palette()
      const span = Math.max(0.1, segment.end - segment.start)
      paint(context, canvas.clientWidth, canvas.clientHeight, {
        heights: slice(
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
        fill: 0.86,
        radius: 3,
      })
    }
    render()
    return {
      update(next: Segment) {
        segment = next
        render()
      },
    }
  }

  function startEdit(segment: Segment): void {
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

  <div class="rows">
    {#each session.segments as segment (segment.index)}
      {#if segment.kind === 'music'}
        <div
          class="track"
          class:current={session.selected === segment.index}
          role="button"
          tabindex="0"
          aria-label="Morceau {trackLabel(segment.number)}{segment.trackTitle
            ? `, ${segment.trackTitle}`
            : ''}"
          onclick={() => session.select(segment.index)}
          onkeydown={(event) => event.key === 'Enter' && session.select(segment.index)}
        >
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
            use:thumb={segment}
            style="width:{THUMB.width}px;height:{THUMB.height}px"
          ></canvas>
        </div>
      {:else}
        <div
          class="gap"
          class:current={session.selected === segment.index}
          role="button"
          tabindex="0"
          aria-label="Blanc de {spell(segment.end - segment.start)}"
          onclick={() => session.select(segment.index)}
          onkeydown={(event) => event.key === 'Enter' && session.select(segment.index)}
        >
          <span class="dash"></span>
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
    width: 400px;
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

  .track {
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 13px 18px;
    border-bottom: 1px solid var(--rule);
    border-left: 3px solid transparent;
    cursor: default;
  }

  .track:hover {
    background: #fbfcfd;
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
    gap: 10px;
    padding: 8px 18px;
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

  .dash {
    width: 22px;
    height: 1px;
    background: var(--gap-rule);
  }

  .keep {
    margin-left: auto;
    font: 500 11.5px var(--sans);
    color: var(--ink-2);
    padding: 2px 6px;
    border-radius: 5px;
  }

  .keep:hover {
    background: #fff;
    color: var(--ink);
  }
</style>
