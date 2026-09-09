<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  /* Ce qu'on écrit, et où. Les décisions d'interface sont explicites ici :

     - **trois questions numérotées, dans l'ordre où on se les pose** : quels
       morceaux, sous quelle forme, où. Les numéros ne décorent pas — ils
       donnent un sens de lecture qu'on peut interrompre et reprendre ;
     - **les morceaux d'abord**, parce que c'est la seule décision qui porte
       sur le concert ; les deux autres portent sur des fichiers ;
     - **les libellés disent ce qu'on obtient**, pas comment ça s'appelle :
       « Le concert en un seul fichier », pas « Album continu » ;
     - **les fonds vidéo se tiennent en liste**, pas en champ : un champ ne
       laissait ni voir la douzième image, ni en retirer une, ni savoir
       laquelle passerait en premier ;
     - **chaque réglage est sous ce qu'il modifie** : le fondu entre images
       sous les images, un fondu enchaîné sous chaque sortie d'un seul tenant —
       celui du WAV sous les cases audio, celui du MP4 du concert entier sous
       les cases vidéo. Ils restent en place quand leur case ne l'est pas,
       éteints : rien n'apparaît ni ne disparaît sous le curseur ;
     - **la section vidéo répare elle-même ce qui lui manque** : un bouton, à
       la place d'une phrase qui suppose de savoir ce qu'est ffmpeg. */
  import { onMount, tick } from 'svelte'
  import { api, follow, type ExportChoice, type Job } from '../lib/api'
  import { session, message } from '../lib/session.svelte'
  import { duration as spell, trackLabel } from '../lib/format'
  import Hint from './Hint.svelte'
  import ExportImages from './ExportImages.svelte'
  import NumberInput from './NumberInput.svelte'

  /* Les explications, à part du balisage : elles restent aussi longues et
     aussi précises qu'avant, mais se lisent à la demande. Les rassembler ici
     les rend aussi relisibles d'un coup d'œil, ce qu'elles n'étaient plus une
     fois dispersées entre les cases. */
  const WHY = $derived({
    pieces:
      t('ui.deselecting_a_track_changes_neither_the_edits_nor'),
    full:
      t('ui.a_single_wav_containing_the_tracks_back_to'),
    tracks:
      t('ui.numbered_and_named_using_the_title_you_entered'),
    crossfade:
      t('ui.the_end_of_each_track_fades_into_the'),
    videoFull:
      t('ui.uses_the_background_image_the_displayed_title_follows'),
    videoTracks:
      t('ui.includes_the_track_title_overlaid_on_the_image'),
    dir:
      t('ui.the_concert_gets_its_own_folder_here_named'),
  })

  let { onClose, onBusy }: { onClose: () => void; onBusy: (job: Job | null) => void } =
    $props()

  const tracks = $derived(session.state?.tracks ?? [])
  let choice = $state<ExportChoice>({ ...(session.state?.export as ExportChoice) })
  let picked = $state<Set<number>>(
    new Set(session.state?.export.selection ?? (session.state?.tracks ?? []).map((t) => t.number)),
  )
  let blocked = $state(session.state?.video ?? null)
  let installing = $state<Job | null>(null)
  let conflict = $state<{
    target: string
    proposed: string
    overwritten: number
    leftovers: number
  } | null>(null)
  let refused = $state('')
  const allPicked = $derived(
    picked.size === tracks.length && tracks.every((track) => picked.has(track.number)),
  )
  let panel: HTMLElement

  function dialogKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault()
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab') return
    const focusable = [...panel.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )].filter((item) => item.offsetParent !== null)
    if (!focusable.length) {
      event.preventDefault()
      panel.focus()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  onMount(() => {
    const previous = document.activeElement as HTMLElement | null
    void tick().then(() => panel.querySelector<HTMLElement>('button, input')?.focus())
    return () => previous?.focus()
  })

  const missing = $derived(
    !picked.size
      ? t('ui.select_at_least_one_track_to_export')
      : !(choice.full || choice.tracks || choice.video_full || choice.video_tracks)
        ? t('ui.select_at_least_one_output_file')
        : (choice.video_full || choice.video_tracks) && !choice.images.length
          ? t('ui.choose_at_least_one_video_background_image')
          : !choice.dir
            ? t('ui.choose_a_destination')
            : '',
  )

  /* Une image par morceau, mais pas le compte : on prévient avant d'écrire.

     La règle promet une image à chacun ; le rendu, lui, ne s'arrête pas pour
     si peu — il reprend la première quand il arrive au bout, ou laisse de côté
     celles qui dépassent. C'est un choix raisonnable, mais silencieux : on
     découvrait à la lecture que trois photos avaient tourné sur douze
     morceaux, après une demi-heure d'encodage.

     Rien à dire hors de cette règle : dans le diaporama à l'horloge, le nombre
     d'images n'a aucun rapport avec le nombre de morceaux. */
  const mismatch = $derived.by(() => {
    if (!(choice.video_full || choice.video_tracks)) return null
    if (!choice.one_per_track) return null
    const images = choice.images.length
    const wanted = picked.size
    if (!images || images === wanted) return null
    return { images, wanted, short: images < wanted }
  })

  // L'alerte n'est posée qu'au moment d'exporter : la signaler en continu la
  // ferait clignoter pendant qu'on coche ses morceaux, quand le compte est
  // forcément faux.
  let asking = $state(false)

  function attempt(): void {
    if (![...panel.querySelectorAll('input')].every(input => input.reportValidity())) return
    if (mismatch) {
      asking = true
      return
    }
    start()
  }

  function toggle(number: number): void {
    const next = new Set(picked)
    if (next.has(number)) next.delete(number)
    else next.add(number)
    picked = next
  }

  async function chooseDir(): Promise<void> {
    const found = await api.pick('dir', { start: choice.dir })
    if (found.path) choice.dir = found.path
  }

  async function installFfmpeg(): Promise<void> {
    try {
      const done = await follow(await api.installFfmpeg(), (tick) => (installing = tick))
      blocked = (done.result as { blocked: string | null })?.blocked ?? null
    } catch (failure) {
      // L'échec laisse le bouton cliquable : une coupure de réseau se rattrape
      // en réessayant, et la seconde source n'a peut-être été injoignable
      // qu'un instant.
      refused = message(failure)
    } finally {
      installing = null
    }
  }

  function payload(): ExportChoice {
    return {
      ...choice,
      images: choice.images,
      image: choice.images[0] ?? '',
      selection: allPicked ? null : [...picked].sort((a, b) => a - b),
    }
  }

  async function start(target?: string, replace = false): Promise<void> {
    refused = ''
    const body = payload()
    try {
      if (!target) {
        const plan = await api.planExport(body)
        if (plan.conflict) {
          conflict = {
            target: plan.target,
            proposed: plan.proposed ?? plan.target,
            overwritten: plan.overwritten ?? 0,
            leftovers: plan.leftovers ?? 0,
          }
          return
        }
        target = plan.target
      }
      conflict = null
      onClose()
      const job = await api.render({ ...body, target, replace })
      const done = await follow(job, (tick) => onBusy(tick))
      onBusy(null)
      if (done.state === 'cancelled') {
        session.note(t('ui.export_stopped_the_previous_export_was_preserved'))
        return
      }
      const written = (done.result as { dir?: string })?.dir ?? target
      session.note(t('ui.export_complete_value', { p0: written }))
      await session.refresh()
    } catch (failure) {
      onBusy(null)
      refused = message(failure)
      session.note(message(failure))
    }
  }
</script>

<!-- Le fondu enchaîné n'existe que quand il sert, et là où il sert.

     Le WAV et le MP4 du concert entier ont **chacun le sien** : ce sont deux
     documents, et on grave volontiers un disque bout à bout tout en mettant en
     ligne une vidéo sans couture. Chaque section porte donc son champ, sous la
     case qui l'active.

     Il reste en place quand sa sortie n'est pas cochée, éteint. Le faire
     apparaître et disparaître au fil des cases était pire que le vide qu'il
     laisse : la colonne se réorganisait sous le curseur à chaque clic, et les
     cases vidéo sautaient de quarante pixels au moment même où l'on visait la
     suivante. -->
{#snippet crossfadeKnob(field: 'crossfade' | 'video_crossfade', on: boolean)}
  <div class="knob" class:off={!on}>
    <label for={field}>{t('ui.crossfade')}<Hint text={WHY.crossfade} /></label>
    <NumberInput
      id={field}
      min={0}
      max={60}
      step={0.5}
      disabled={!on}
      bind:value={choice[field]}
    />
    <span class="unit">s</span>
  </div>
{/snippet}

<div
  class="veil"
  role="presentation"
  onclick={(event) => event.target === event.currentTarget && onClose()}
  onkeydown={dialogKey}
>
  <div
    class="panel"
    bind:this={panel}
    role="dialog"
    aria-modal="true"
    aria-labelledby="export-title"
    tabindex="-1"
  >
    <header>
      <h1 id="export-title">{t('ui.export')}</h1>
      <button class="btn quiet" onclick={onClose}>{t('ui.close')}</button>
    </header>

    <div class="body">
      <section>
        <h2>
          <span class="step">1</span>{t('ui.which_tracks')}<Hint text={WHY.pieces} side="right" />
          <!-- Le bouton est passé du bas de la liste à la ligne du titre :
               sous vingt-cinq morceaux qui défilent, il attendait qu'on
               descende pour se montrer, alors qu'on s'en sert avant de
               choisir. Il retrouve le motif de « Fonds / Ajouter des
               images… » plus bas — l'action de la zone, au bout de son
               en-tête. -->
          <button
            class="btn tonal all"
            onclick={() =>
              (picked =
                allPicked
                  ? new Set()
                  : new Set(tracks.map((track) => track.number)))}
          >
            {allPicked ? t('ui.deselect_all') : t('ui.select_all')}
          </button>
        </h2>
        <div class="picks">
          {#each tracks as track (track.number)}
            <label class="pick">
              <input
                type="checkbox"
                checked={picked.has(track.number)}
                onchange={() => toggle(track.number)}
              />
              <span class="mono num">{trackLabel(track.number)}</span>
              <span class="who">{track.title || t('ui.track_value_116', { p0: trackLabel(track.number) })}</span>
              <span class="mono len">{spell(track.end - track.start)}</span>
            </label>
          {/each}
        </div>
      </section>

      <div class="right">
      <section class="scrolls">
        <h2><span class="step">2</span>{t('ui.which_formats')}</h2>

        <span class="label">{t('ui.audio')}</span>
        <div class="line">
          <label>
            <input type="checkbox" bind:checked={choice.full} />
            <b>{t('ui.the_concert_in_one_file')}</b>
          </label>
          <Hint text={WHY.full} />
        </div>
        <div class="line">
          <label>
            <input type="checkbox" bind:checked={choice.tracks} />
            <b>{t('ui.one_file_per_track')}</b>
          </label>
          <Hint text={WHY.tracks} />
        </div>

        {@render crossfadeKnob('crossfade', choice.full)}

        <span class="label vid">{t('ui.video')}</span>
        {#if blocked}
          <p class="why">{t('ui.video_requires_ffmpeg_a_tool_supplied_separately_from')}</p>
          {#if installing}
            <p class="mono progress">
              {installing.phase}
              {#if installing.total}
                — {Math.round((installing.done / installing.total) * 100)} %
              {/if}
            </p>
          {:else}
            <button class="btn" onclick={installFfmpeg}>{t('ui.install_ffmpeg_110_mb')}</button>
          {/if}
        {:else}
          <div class="line">
            <label>
              <input type="checkbox" bind:checked={choice.video_full} />
              <b>{t('ui.one_mp4_of_the_entire_concert')}</b>
            </label>
            <Hint text={WHY.videoFull} />
          </div>
          <div class="line">
            <label>
              <input type="checkbox" bind:checked={choice.video_tracks} />
              <b>{t('ui.one_mp4_per_track')}</b>
            </label>
            <Hint text={WHY.videoTracks} />
          </div>

          {@render crossfadeKnob('video_crossfade', choice.video_full)}

          <ExportImages
            {choice}
            enabled={choice.video_full || choice.video_tracks}
          />
        {/if}
      </section>

      <section class="anchored">
        <h2>
          <span class="step">3</span>{t('ui.where')}<Hint text={WHY.dir} />
        </h2>
        <div class="dir">
          <input class="mono" bind:value={choice.dir} placeholder={t('ui.no_folder_selected')} />
          {#if session.dialogs}
            <!-- Tonal comme « Ajouter des images… » : un bouton de contour
                 posé contre un champ de saisie a le même dessin que lui, et
                 se lit comme une deuxième case plutôt que comme l'action qui
                 remplit la première. -->
            <button class="btn tonal" onclick={chooseDir}>{t('ui.browse')}</button>
          {/if}
        </div>
      </section>
      </div>
    </div>

    {#if asking && mismatch}
      <div class="conflict">
        <b>
          {t('export.mismatch', { images: t('count.images', { count: mismatch.images }), tracks: t('count.tracks', { count: mismatch.wanted }) })}
        </b>
        <ul>
          {#if mismatch.short}
            <li>{t('ui.one_image_per_track_is_selected_but_there')}</li>
          {:else}
            <li>
              {t('export.unused_images', { count: mismatch.images - mismatch.wanted })}
            </li>
          {/if}
        </ul>
        <div class="issues">
          <button
            class="btn accent"
            onclick={() => {
              asking = false
              start()
            }}
          >{t('ui.export_anyway')}</button>
          <button class="btn quiet" onclick={() => (asking = false)}>{t('ui.back_to_images')}</button>
        </div>
      </div>
    {/if}

    {#if conflict}
      <div class="conflict">
        <b>{t('ui.this_folder_already_contains_an_export')}</b>
        <ul>
          {#if conflict.overwritten}
            <li>{t('export.overwritten', { count: conflict.overwritten })}</li>
          {/if}
          {#if conflict.leftovers}
            <li>
              {t('export.leftovers', { count: conflict.leftovers })}
            </li>
          {/if}
        </ul>
        <div class="issues">
          <button class="btn accent" onclick={() => start(conflict!.proposed, false)}>
            {t('export.beside', { name: conflict.proposed.split(/[\\/]/).pop() })}
          </button>
          <button class="btn" onclick={() => start(conflict!.target, true)}>{t('ui.replace_the_previous_export')}</button>
          <button class="btn quiet" onclick={() => (conflict = null)}>{t('ui.do_nothing')}</button>
        </div>
      </div>
    {/if}

    <footer>
      <span class="refuse">{refused || missing}</span>
      <button class="btn quiet" onclick={onClose}>{t('ui.cancel')}</button>
      <button class="btn strong" disabled={Boolean(missing)} onclick={attempt}>{t('ui.export')}</button>
    </footer>
  </div>
</div>

<style>
  .veil {
    position: fixed;
    inset: 0;
    background: var(--veil);
    display: grid;
    place-items: center;
    padding: 28px;
    z-index: 30;
  }

  .panel {
    width: min(880px, 100%);
    max-height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--surface);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-float);
    overflow: hidden;
  }

  header {
    display: flex;
    align-items: center;
    padding: 18px 24px;
    border-bottom: 1px solid var(--border);
    flex: none;
  }

  h1 {
    margin: 0;
    font: 600 18px var(--sans);
  }

  header .btn {
    margin-left: auto;
  }

  /* Deux colonnes, et **c'est la colonne de droite qui défile**, pas la
     fenêtre. Tout défilait, et choisir six fonds vidéo poussait « Où ? » hors
     de l'écran : la troisième question disparaissait au moment précis où l'on
     venait de répondre à la deuxième. Elle est maintenant ancrée en bas de sa
     colonne, toujours visible, quoi qu'on empile au-dessus. */
  .body {
    flex: 1;
    min-height: 0;
    padding: 4px 24px 0;
    display: grid;
    grid-template-columns: minmax(280px, 1fr) minmax(320px, 1fr);
    gap: 0 28px;
    align-items: stretch;
  }

  .right {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  section {
    padding: 18px 0 4px;
  }

  .body > section:first-child {
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .scrolls {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding-right: 6px;
  }

  .anchored {
    flex: none;
    border-top: 1px solid var(--rule);
    padding-bottom: 18px;
  }

  h2 {
    display: flex;
    align-items: center;
    gap: 9px;
    margin: 0 0 12px;
    font: 600 14px var(--sans);
    color: var(--ink);
  }

  .step {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border-radius: 11px;
    background: var(--accent);
    color: var(--on-accent);
    font: 700 11px var(--mono);
    box-shadow: 0 1px 3px var(--accent-soft);
  }

  .why {
    margin: 0 0 14px;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--ink-2);
  }

  .picks {
    flex: 1;
    min-height: 140px;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface-raised);
  }

  .pick {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-subtle);
    font-size: 12.5px;
    cursor: pointer;
    transition: background 0.1s ease;
  }

  .pick:hover {
    background: var(--hover);
  }

  .pick:last-child {
    border-bottom: 0;
  }

  .num {
    color: var(--ink-3);
    font-size: 11.5px;
    font-weight: 600;
  }

  .who {
    flex: 1;
    font-weight: 500;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .len {
    font-size: 11.5px;
    color: var(--ink-3);
  }

  .all {
    margin-left: auto;
    height: 26px;
    font-size: 11.5px;
  }

  .label.vid {
    display: block;
    margin-top: 20px;
  }

  .line {
    display: flex;
    align-items: center;
    padding: 7px 0;
  }

  .line label {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }

  .line b {
    font: 600 13px var(--sans);
    color: var(--ink);
  }

  .knob {
    display: grid;
    grid-template-columns: auto 78px auto;
    align-items: center;
    gap: 8px;
    padding: 10px 0 6px 26px;
  }

  .knob label {
    font-size: 12.5px;
    font-weight: 500;
    white-space: nowrap;
    color: var(--ink-2);
  }

  .knob :global(input),
  .dir input {
    height: 32px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-raised);
    color: var(--ink);
    outline: none;
  }

  .knob :global(input) {
    text-align: right;
    font: 600 13px var(--mono);
  }

  .knob :global(input:focus),
  .dir input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  .unit {
    font-size: 12px;
    color: var(--ink-3);
  }

  /* Éteint, pas retiré : un réglage qui disparaît fait sauter la colonne
     entière sous le curseur. Le champ garde sa place et sa valeur. */
  .off {
    opacity: 0.45;
    pointer-events: none;
  }

  .dir {
    display: flex;
    gap: 8px;
  }

  .dir input {
    flex: 1;
    font-size: 12px;
  }

  .progress {
    font-size: 12px;
    color: var(--accent);
    font-weight: 600;
  }

  .conflict {
    border-top: 1px solid var(--border);
    background: var(--surface-raised);
    padding: 16px 24px;
    font-size: 12.5px;
  }

  .conflict ul {
    margin: 8px 0 12px;
    padding-left: 18px;
    color: var(--ink-2);
  }

  .issues {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }

  footer {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 24px;
    border-top: 1px solid var(--border);
    flex: none;
    background: var(--surface);
  }

  .refuse {
    flex: 1;
    font-size: 12.5px;
    color: var(--gap);
    font-weight: 500;
  }
</style>
