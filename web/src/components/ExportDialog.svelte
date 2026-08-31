<script lang="ts">
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
     - **chaque réglage est sous ce qu'il modifie** : le fondu enchaîné sous
       les cases audio, le fondu entre images sous les images ;
     - **la section vidéo répare elle-même ce qui lui manque** : un bouton, à
       la place d'une phrase qui suppose de savoir ce qu'est ffmpeg. */
  import { onMount, tick } from 'svelte'
  import { api, follow, type ExportChoice, type Job } from '../lib/api'
  import { session, message } from '../lib/session.svelte'
  import { duration as spell, trackLabel } from '../lib/format'
  import Hint from './Hint.svelte'
  import ExportImages from './ExportImages.svelte'

  /* Les explications, à part du balisage : elles restent aussi longues et
     aussi précises qu'avant, mais se lisent à la demande. Les rassembler ici
     les rend aussi relisibles d'un coup d'œil, ce qu'elles n'étaient plus une
     fois dispersées entre les cases. */
  const WHY = {
    pieces:
      "Décocher un morceau ne change ni le découpage ni la numérotation : la " +
      "piste 7 s'appellera « 07 » même si elle part seule. Pour retirer un " +
      "passage du concert lui-même, c'est la carte d'édition.",
    full:
      "Un seul WAV : les morceaux bout à bout, blancs retirés. Une cue sheet " +
      "l'accompagne dans « infos », pour retrouver les morceaux à la lecture " +
      'ou à la gravure.',
    tracks:
      "Numéroté et nommé d'après le titre saisi. C'est ce qu'attend un lecteur " +
      'ou une clé USB.',
    crossfade:
      "N'agit que sur le concert en un seul fichier : la fin d'un morceau se " +
      'fond dans le début du suivant. À zéro, ils se suivent bout à bout, ' +
      'comme sur un disque.',
    videoFull:
      "Sur l'image de fond. Le titre affiché suit le morceau en cours plutôt " +
      'que de rester figé deux heures.',
    videoTracks:
      "Son titre incrusté. C'est la forme qu'attendent les plateformes qui " +
      "n'acceptent que de la vidéo.",
    dir:
      "Le concert reçoit son propre dossier ici, nommé d'après " +
      "l'enregistrement. Un export déjà présent n'est jamais écrasé sans qu'on " +
      'le demande.',
  }

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
      ? 'Cocher au moins un morceau à exporter.'
      : !(choice.full || choice.tracks || choice.video_full || choice.video_tracks)
        ? 'Cocher au moins un fichier à écrire.'
        : (choice.video_full || choice.video_tracks) && !choice.images.length
          ? 'Choisir au moins une image de fond des vidéos.'
          : !choice.dir
            ? 'Choisir la destination.'
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
      const written = (done.result as { dir?: string })?.dir ?? target
      session.note(`Export terminé — ${written}`)
      await session.refresh()
    } catch (failure) {
      onBusy(null)
      refused = message(failure)
      session.note(message(failure))
    }
  }
</script>

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
      <h1 id="export-title">Exporter</h1>
      <button class="btn quiet" onclick={onClose}>Fermer</button>
    </header>

    <div class="body">
      <section>
        <h2>
          <span class="step">1</span> Quels morceaux ?
          <Hint text={WHY.pieces} side="right" />
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
            {allPicked ? 'Tout décocher' : 'Tout cocher'}
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
              <span class="who">{track.title || `Piste ${trackLabel(track.number)}`}</span>
              <span class="mono len">{spell(track.end - track.start)}</span>
            </label>
          {/each}
        </div>
      </section>

      <div class="right">
      <section class="scrolls">
        <h2><span class="step">2</span> Sous quelle forme ?</h2>

        <span class="label">Audio</span>
        <div class="line">
          <label>
            <input type="checkbox" bind:checked={choice.full} />
            <b>Le concert en un seul fichier</b>
          </label>
          <Hint text={WHY.full} />
        </div>
        <div class="line">
          <label>
            <input type="checkbox" bind:checked={choice.tracks} />
            <b>Un fichier par morceau</b>
          </label>
          <Hint text={WHY.tracks} />
        </div>

        <div class="knob" class:off={!choice.full}>
          <label for="crossfade">Fondu enchaîné<Hint text={WHY.crossfade} /></label>
          <input
            id="crossfade"
            class="mono"
            type="number"
            min="0"
            max="60"
            step="0.5"
            bind:value={choice.crossfade}
          />
          <span class="unit">s</span>
        </div>

        <span class="label vid">Vidéo</span>
        {#if blocked}
          <p class="why">
            La vidéo demande ffmpeg, un outil qui ne fait pas partie de
            ConcertCutter — une centaine de mégaoctets, contre 27 pour
            l'application entière, pour une sortie dont on se passe souvent. Le
            bouton s'en charge, une fois pour toutes.
          </p>
          {#if installing}
            <p class="mono progress">
              {installing.phase}
              {#if installing.total}
                — {Math.round((installing.done / installing.total) * 100)} %
              {/if}
            </p>
          {:else}
            <button class="btn" onclick={installFfmpeg}>Installer ffmpeg (110 Mo)</button>
          {/if}
        {:else}
          <div class="line">
            <label>
              <input type="checkbox" bind:checked={choice.video_full} />
              <b>Un MP4 du concert entier</b>
            </label>
            <Hint text={WHY.videoFull} />
          </div>
          <div class="line">
            <label>
              <input type="checkbox" bind:checked={choice.video_tracks} />
              <b>Un MP4 par morceau</b>
            </label>
            <Hint text={WHY.videoTracks} />
          </div>

          <ExportImages
            {choice}
            enabled={choice.video_full || choice.video_tracks}
          />
        {/if}
      </section>

      <section class="anchored">
        <h2>
          <span class="step">3</span> Où ?
          <Hint text={WHY.dir} />
        </h2>
        <div class="dir">
          <input class="mono" bind:value={choice.dir} placeholder="Aucun dossier choisi" />
          {#if session.dialogs}
            <!-- Tonal comme « Ajouter des images… » : un bouton de contour
                 posé contre un champ de saisie a le même dessin que lui, et
                 se lit comme une deuxième case plutôt que comme l'action qui
                 remplit la première. -->
            <button class="btn tonal" onclick={chooseDir}>Parcourir…</button>
          {/if}
        </div>
      </section>
      </div>
    </div>

    {#if asking && mismatch}
      <div class="conflict">
        <b>
          {mismatch.images} image{mismatch.images > 1 ? 's' : ''} pour
          {mismatch.wanted} morceau{mismatch.wanted > 1 ? 'x' : ''} à exporter.
        </b>
        <ul>
          {#if mismatch.short}
            <li>
              « Une seule image par morceau » est cochée, et il en manque : une
              fois la dernière atteinte, l'export repart de la première. Les
              images se répètent donc jusqu'au bout du concert.
            </li>
          {:else}
            <li>
              « Une seule image par morceau » est cochée, et il y en a plus que
              de morceaux : {mismatch.images - mismatch.wanted} ne
              {mismatch.images - mismatch.wanted > 1 ? 'seront' : 'sera'} pas
              utilisée{mismatch.images - mismatch.wanted > 1 ? 's' : ''}.
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
          >
            Exporter quand même
          </button>
          <button class="btn quiet" onclick={() => (asking = false)}>
            Revenir aux images
          </button>
        </div>
      </div>
    {/if}

    {#if conflict}
      <div class="conflict">
        <b>Ce dossier contient déjà un export.</b>
        <ul>
          {#if conflict.overwritten}
            <li>{conflict.overwritten} fichier(s) seraient écrasés</li>
          {/if}
          {#if conflict.leftovers}
            <li>
              {conflict.leftovers} fichier(s) d'un export précédent resteraient
              mélangés aux nouveaux
            </li>
          {/if}
        </ul>
        <div class="issues">
          <button class="btn accent" onclick={() => start(conflict!.proposed, false)}>
            Écrire à côté, dans « {conflict.proposed.split(/[\\/]/).pop()} »
          </button>
          <button class="btn" onclick={() => start(conflict!.target, true)}>
            Remplacer l'export précédent
          </button>
          <button class="btn quiet" onclick={() => (conflict = null)}>Ne rien faire</button>
        </div>
      </div>
    {/if}

    <footer>
      <span class="refuse">{refused || missing}</span>
      <button class="btn quiet" onclick={onClose}>Annuler</button>
      <button class="btn strong" disabled={Boolean(missing)} onclick={attempt}>
        Exporter
      </button>
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
    padding: 20px 0 4px;
  }

  /* La première question occupe sa colonne entière : vingt-cinq morceaux ne
     tiennent pas sous un titre. */
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
  }

  .step {
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    border-radius: 10px;
    background: var(--ink);
    color: var(--on-ink);
    font: 600 11px var(--mono);
  }

  .why {
    margin: 0 0 14px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--ink-3);
  }

  .picks {
    flex: 1;
    min-height: 120px;
    overflow-y: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .pick {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 7px 10px;
    border-bottom: 1px solid var(--rule);
    font-size: 12.5px;
  }

  .pick:last-child {
    border-bottom: 0;
  }

  .num {
    color: var(--ink-3);
    font-size: 11.5px;
  }

  .who {
    flex: 1;
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

  /* La case et son libellé forment le seul point de clic. L'étiquette portait
     toute la ligne, large de sa colonne : un clic dans le vide à droite du
     texte cochait la case sans qu'on l'ait voulu. */
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
    font: 500 13px var(--sans);
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
  }

  .knob input,
  .dir input {
    height: 30px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    outline: none;
  }

  .knob input {
    text-align: right;
  }

  .knob input:focus,
  .dir input:focus {
    border-color: var(--accent);
  }

  .unit {
    font-size: 12px;
    color: var(--ink-3);
  }

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
  }

  /* Une bande neutre, et non `--gap-row`.

     Cette teinte-là appartient aux blancs du concert — les applaudissements,
     la seule couleur chaude de la palette, posée pour qu'on repère une coupe
     dans le tracé. Sous une question posée avant d'exporter, elle ne dit rien
     et se voit trop : un brun qui n'est ni celui du thème sombre ni celui du
     clair. `--rule` est le fond en creux de l'application, celui des vignettes
     — la bande se détache du panneau sans changer de famille. */
  .conflict {
    border-top: 1px solid var(--border);
    background: var(--rule);
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
    gap: 10px;
    padding: 14px 24px;
    border-top: 1px solid var(--border);
    flex: none;
  }

  .refuse {
    flex: 1;
    font-size: 12.5px;
    color: var(--gap);
  }
</style>
