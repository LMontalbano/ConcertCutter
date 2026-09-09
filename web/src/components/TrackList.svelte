<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  /* La colonne de gauche : les morceaux, et les zones à retirer entre eux.

     « Blanc » est le mot du métier, et il ne disait rien à qui ouvre le
     logiciel : ni que la zone a été trouvée toute seule, ni surtout qu'elle
     part à l'export. Les lignes annoncent donc leur sort — « À retirer » —, et
     le bouton d'à côté dit comment le refuser. */
  import { session } from '../lib/session.svelte'
  import { hms, duration as spell, trackLabel } from '../lib/format'
  import { paint, palette, silhouette, surface, type Palette } from '../lib/wave'
  import type { Segment } from '../lib/api'

  const THUMB = { width: 88, height: 26 }

  let colours: Palette = palette()
  let editing = $state(-1)
  let draft = $state('')

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
        showCenterLine: false,
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
    await session.edit({ op: 'set_title', index, title: draft })
  }

  function onKey(event: KeyboardEvent): void {
    if (event.key === 'Enter') (event.target as HTMLInputElement).blur()
    if (event.key === 'Escape') {
      editing = -1
      ;(event.target as HTMLInputElement).blur()
    }
  }

  let rows: HTMLDivElement

  $effect(() => {
    const index = session.selected
    const row = rows?.querySelector<HTMLElement>(`[data-rank="${index}"]`)
    if (!row || !rows) return
    const line = row.getBoundingClientRect()
    const frame = rows.getBoundingClientRect()
    if (line.top >= frame.top && line.bottom <= frame.bottom) return
    row.scrollIntoView({ block: 'center' })
  })

  async function keep(segment: Segment): Promise<void> {
    // La ligne change de couleur et de camp sous le curseur : rien à ajouter.
    await session.edit({ op: 'toggle_kind', index: segment.index })
  }
</script>

<aside>
  <header>
    <div class="header-left">
      <span class="label">{t('ui.tracks_segments')}</span>
    </div>
    <div class="header-right">
      <span class="badge accent" title={t('ui.tracks_kept_in_the_export')}
        >{t('count.tracks', { count: session.counts.tracks })}</span
      >
      <!-- Deux compteurs, et rien derrière : le titre dit ce qu'ils comptent,
           et `cursor: default` évite de laisser croire à une action. -->
      <span
        class="badge gap"
        title={t('ui.automatically_detected_sections_removed_from_the_export')}
        >{session.counts.gaps} {t('ui.to_remove')}</span
      >
    </div>
  </header>

  <div class="rows" bind:this={rows}>
    {#each session.segments as segment (segment.index)}
      {#if segment.kind === 'music'}
        <!-- La ligne entière est cliquable par commodité, mais elle n'est pas
             un bouton : elle en contient trois. Lui donner `role="button"` et
             un `tabindex` — ce qu'elle avait — plaçait des contrôles
             interactifs à l'intérieur d'un contrôle interactif, ce qu'aucun
             lecteur d'écran ne sait annoncer, et posait un arrêt de tabulation
             par morceau sur lequel aucune touche ne faisait rien. Le clavier
             passe par les boutons de la ligne, qui sélectionnent déjà. -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div
          class="track"
          data-rank={segment.index}
          class:current={session.selected === segment.index}
          onclick={() => session.select(segment.index)}
        >
          <button
            class="listen"
            class:sounding={session.playing_at(segment.index)}
            onclick={(event) => (event.stopPropagation(), session.play(segment.index))}
            aria-label={t(session.playing_at(segment.index) ? 'track.stop' : 'track.listen', { number: trackLabel(segment.number) })}
            title={session.playing_at(segment.index) ? t('ui.stop') : t('ui.listen_to_this_track')}
          >
            <span class="play-icon">{session.playing_at(segment.index) ? '❚❚' : '▶'}</span>
          </button>
          
          <div class="num-pill">{trackLabel(segment.number)}</div>

          <div class="body">
            {#if editing === segment.index}
              <!-- svelte-ignore a11y_autofocus -->
              <input
                class="title"
                bind:value={draft}
                onblur={commit}
                onkeydown={onKey}
                autofocus
                placeholder={t('ui.untitled')}
              />
            {:else}
              <div class="title-row">
                <button
                  class="title"
                  class:empty={!segment.trackTitle}
                  ondblclick={(event) => (event.stopPropagation(), startEdit(segment))}
                  onclick={(event) => (event.stopPropagation(), session.select(segment.index))}
                  title={t('ui.double_click_to_rename')}
                >
                  {segment.trackTitle || t('ui.untitled')}
                </button>
              </div>
            {/if}
            <div class="mono times">
              <span>{hms(segment.start)} → {hms(segment.end)}</span>
              <span class="times-sep">·</span>
              <span class="dur-badge">{spell(segment.end - segment.start)}</span>
            </div>
          </div>
          <canvas
            use:thumb={{ segment, theme: session.theme, envelope: session.envelope }}
            style="width:{THUMB.width}px;height:{THUMB.height}px"
          ></canvas>
        </div>
      {:else}
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <div
          class="cut"
          data-rank={segment.index}
          class:current={session.selected === segment.index}
          onclick={() => session.select(segment.index)}
        >
          <button
            class="listen thin"
            class:sounding={session.playing_at(segment.index)}
            onclick={(event) => (event.stopPropagation(), session.play(segment.index))}
            aria-label={t('ui.listen_to_this_passage')}
            title={t('ui.listen_to_this_passage')}
          >
            <span class="play-icon">{session.playing_at(segment.index) ? '❚❚' : '▶'}</span>
          </button>

          <span class="gap-icon" aria-hidden="true">✂</span>

          <!-- Un bouton, et non un simple texte : c'est la seule prise du
               clavier sur une zone à retirer. Devenu `<span>`, il ne laissait
               plus que la souris pour en sélectionner une. -->
          <button
            class="mono gap-name"
            onclick={(event) => (event.stopPropagation(), session.select(segment.index))}
            title={t('ui.automatically_detected_gap_or_applause_this_passage_will')}
            aria-label={t('track.select_gap', { duration: spell(segment.end - segment.start) })}
          >{t('ui.to_remove_249')} {spell(segment.end - segment.start)}</button>

          <button
            class="keep-btn"
            onclick={(event) => (event.stopPropagation(), keep(segment))}
            title={t('ui.keep_this_passage_in_the_export_instead_of')}
          >{t('ui.keep_251')}</button>
        </div>
      {/if}
    {/each}
  </div>
</aside>

<style>
  aside {
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
    justify-content: space-between;
    height: 48px;
    padding: 0 18px;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    flex: none;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .rows {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
  }

  .listen {
    flex: none;
    width: 26px;
    height: 26px;
    border-radius: 13px;
    display: grid;
    place-items: center;
    font-size: 9px;
    color: var(--ink-2);
    border: 1px solid var(--border);
    background: var(--surface);
    transition: all 0.12s ease;
  }

  .listen:hover {
    color: var(--on-accent);
    background: var(--accent);
    border-color: var(--accent);
    transform: scale(1.05);
  }

  .listen.sounding {
    color: var(--on-accent);
    background: var(--accent);
    border-color: var(--accent);
  }

  .listen.thin {
    font-size: 8px;
    color: var(--gap);
    border-color: var(--gap-rule);
    background: var(--surface);
  }

  .listen.thin:hover {
    color: var(--on-ink);
    background: var(--gap);
    border-color: var(--gap);
    transform: scale(1.05);
  }

  .listen.thin.sounding {
    color: var(--on-ink);
    background: var(--gap);
    border-color: var(--gap);
  }

  .play-icon {
    line-height: 1;
    margin-left: 1px;
  }

  .listen.sounding .play-icon,
  .listen.thin.sounding .play-icon {
    margin-left: 0;
  }

  .track {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--rule);
    border-left: 3px solid transparent;
    cursor: pointer;
    transition: background 0.12s ease;
  }

  .track:hover {
    background: var(--hover);
  }

  .track.current {
    background: var(--accent-soft);
    border-left-color: var(--accent);
  }

  .num-pill {
    flex: none;
    font: 600 12px/1 var(--mono);
    color: var(--ink-3);
    padding: 4px 6px;
    border-radius: 4px;
    background: var(--surface-raised);
    border: 1px solid var(--border-subtle);
  }

  .track.current .num-pill {
    color: var(--accent);
    background: var(--surface);
    border-color: var(--accent);
  }

  .body {
    flex: 1;
    min-width: 0;
  }

  .title-row {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .title {
    display: block;
    width: 100%;
    text-align: left;
    padding: 0;
    font: 600 13.5px var(--sans);
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .title.empty {
    color: var(--hint);
    font-weight: 400;
    font-style: italic;
  }

  input.title {
    border: 1px solid var(--accent);
    border-radius: var(--radius-sm);
    padding: 2px 6px;
    margin: -3px -7px;
    background: var(--surface);
    outline: none;
    color: var(--ink);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  .times {
    display: flex;
    align-items: center;
    gap: 5px;
    margin-top: 3px;
    font-size: 11.5px;
    color: var(--ink-3);
    white-space: nowrap;
  }

  .times-sep {
    opacity: 0.5;
  }

  .dur-badge {
    color: var(--ink-2);
  }

  canvas {
    flex: none;
    border-radius: 4px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  }

  /* `cut` et non `gap` : la pastille du compteur porte « badge gap », et la
     règle de la ligne l'attrapait au passage — curseur de main et fond qui
     change au survol sur un simple compte, qui ne répond à rien. Deux rôles
     différents, deux noms différents. */
  .cut {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--rule);
    border-left: 3px solid transparent;
    background: var(--gap-row);
    font-size: 11.5px;
    color: var(--gap);
    cursor: pointer;
    transition: background 0.12s ease;
  }

  /* Assombri dans sa propre teinte, et non repeint en gris : `--hover` est
     le survol des lignes de morceau, et l'emprunter faisait perdre à la zone à
     retirer la seule couleur qui la distingue au premier coup d'œil. */
  .cut:hover {
    background: var(--gap-soft);
  }

  .cut.current {
    border-left-color: var(--gap);
  }

  .gap-icon {
    font-size: 12px;
    color: var(--gap);
    opacity: 0.8;
  }

  .gap-name {
    flex: 1;
    text-align: left;
    color: var(--gap);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .keep-btn {
    margin-left: auto;
    font: 600 11px var(--sans);
    color: var(--gap);
    background: var(--gap-soft);
    border: 1px solid transparent;
    padding: 3px 8px;
    border-radius: var(--radius-sm);
    transition: all 0.12s ease;
  }

  .keep-btn:hover {
    background: var(--gap);
    color: var(--on-ink);
  }
</style>

