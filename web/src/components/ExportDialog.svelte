<script lang="ts">
  /* Ce qu'on écrit, et où.

     La fenêtre Tkinter faisait 942 lignes et portait des décisions qu'il ne
     fallait pas perdre au portage. Elles sont toutes reprises ici :

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
  import { api, follow, type ExportChoice, type Job } from '../lib/api'
  import { session, message } from '../lib/session.svelte'
  import { duration as spell, trackLabel } from '../lib/format'
  import Hint from './Hint.svelte'

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
    onePerTrack:
      'Le morceau 1 reçoit la première image, le 2 la deuxième, et ainsi de ' +
      "suite ; le cycle recommence s'il y a moins d'images que de morceaux. " +
      'Sans cette case, les images défilent toutes sous chaque morceau — la ' +
      'douzième photo passe alors sous la vidéo du premier. Sans effet sur le ' +
      "concert en un seul fichier, où le fond n'a pas de morceau à suivre.",
    slideshow:
      "Les images se relaient dans l'ordre ci-dessus, une toutes les huit " +
      'secondes, et le cycle recommence aussi longtemps que dure le son. ' +
      'Chacune garde ses proportions et se centre sur du noir.',
    stills:
      'Photos du concert, pochette, affiche. Le titre du morceau est incrusté ' +
      'par-dessus.',
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

  async function addImages(): Promise<void> {
    const found = await api.pick('images')
    // Le bouton ajoute sans effacer : on revient presque toujours au sélecteur
    // pour ajouter une image, pas pour remplacer les douze déjà choisies.
    if (found.paths?.length) choice.images = [...choice.images, ...found.paths]
  }

  function moveImage(index: number, by: number): void {
    const next = [...choice.images]
    const target = index + by
    if (target < 0 || target >= next.length) return
    ;[next[index], next[target]] = [next[target], next[index]]
    choice.images = next
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
      selection: picked.size === tracks.length ? null : [...picked].sort((a, b) => a - b),
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

<div class="veil" role="presentation" onclick={(event) => event.target === event.currentTarget && onClose()}>
  <div class="panel" role="dialog" aria-label="Exporter">
    <header>
      <h1>Exporter</h1>
      <button class="btn quiet" onclick={onClose}>Fermer</button>
    </header>

    <div class="body">
      <section>
        <h2>
          <span class="step">1</span> Quels morceaux ?
          <Hint text={WHY.pieces} side="right" />
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
        <button
          class="btn quiet all"
          onclick={() =>
            (picked =
              picked.size === tracks.length
                ? new Set()
                : new Set(tracks.map((track) => track.number)))}
        >
          {picked.size === tracks.length ? 'Tout décocher' : 'Tout cocher'}
        </button>
      </section>

      <div class="right">
      <section class="scrolls">
        <h2><span class="step">2</span> Sous quelle forme ?</h2>

        <span class="label">Audio</span>
        <label class="line">
          <input type="checkbox" bind:checked={choice.full} />
          <b>Le concert en un seul fichier</b>
          <Hint text={WHY.full} />
        </label>
        <label class="line">
          <input type="checkbox" bind:checked={choice.tracks} />
          <b>Un fichier par morceau</b>
          <Hint text={WHY.tracks} />
        </label>

        <div class="knob" class:off={!choice.full}>
          <label for="crossfade">Fondu enchaîné<Hint text={WHY.crossfade} /></label>
          <input
            id="crossfade"
            class="mono"
            type="number"
            min="0"
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
          <label class="line">
            <input type="checkbox" bind:checked={choice.video_full} />
            <b>Un MP4 du concert entier</b>
            <Hint text={WHY.videoFull} />
          </label>
          <label class="line">
            <input type="checkbox" bind:checked={choice.video_tracks} />
            <b>Un MP4 par morceau</b>
            <Hint text={WHY.videoTracks} />
          </label>

          <div class="images" class:off={!choice.video_full && !choice.video_tracks}>
            <div class="images-head">
              <span class="label">Fonds</span>
              <button class="btn quiet" onclick={addImages}>Ajouter des images…</button>
            </div>
            {#if choice.images.length}
              <!-- Des vignettes, et non des noms de fichiers. « DSC_0421.jpg »
                   ne dit pas quelle photo c'est : on choisissait le fond de ses
                   vidéos à l'aveugle, et l'ordre du diaporama encore plus. -->
              <ul>
                {#each choice.images as image, index (image + index)}
                  <li>
                    <img src={api.imageUrl(image)} alt={image.split(/[\\/]/).pop()} />
                    <span class="mono rank">{index + 1}</span>
                    <div class="handles">
                      <button onclick={() => moveImage(index, -1)} aria-label="Avancer dans l'ordre" title="Avancer">
                        ‹
                      </button>
                      <button onclick={() => moveImage(index, 1)} aria-label="Reculer dans l'ordre" title="Reculer">
                        ›
                      </button>
                      <button
                        class="drop"
                        onclick={() =>
                          (choice.images = choice.images.filter((_, rank) => rank !== index))}
                        aria-label="Retirer cette image"
                        title="Retirer"
                      >
                        ×
                      </button>
                    </div>
                    <span class="caption" title={image}>{image.split(/[\\/]/).pop()}</span>
                  </li>
                {/each}
              </ul>

              <label class="line tight">
                <input type="checkbox" bind:checked={choice.one_per_track} />
                <b>Une seule image par morceau</b>
                <Hint text={WHY.onePerTrack} />
              </label>

              {#if !choice.one_per_track}
                <div class="knob">
                  <label for="slide">
                    Fondu entre images<Hint text={WHY.slideshow} />
                  </label>
                  <input
                    id="slide"
                    class="mono"
                    type="number"
                    min="0"
                    step="0.5"
                    bind:value={choice.slide_fade}
                  />
                  <span class="unit">s</span>
                </div>
              {/if}
            {:else}
              <em class="note">
                Photos du concert, pochette, affiche.<Hint text={WHY.stills} />
              </em>
            {/if}
          </div>
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
            <button class="btn" onclick={chooseDir}>Parcourir…</button>
          {/if}
        </div>
      </section>
      </div>
    </div>

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
      <button class="btn strong" disabled={Boolean(missing)} onclick={() => start()}>
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
    margin-top: 8px;
    height: 26px;
    font-size: 11.5px;
  }

  .label.vid {
    display: block;
    margin-top: 20px;
  }

  .line {
    display: flex;
    gap: 10px;
    padding: 7px 0;
    align-items: center;
  }

  .line b {
    font: 500 13px var(--sans);
  }

  em {
    display: block;
    margin-top: 3px;
    font-style: normal;
    font-size: 12px;
    line-height: 1.5;
    color: var(--ink-3);
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

  .images {
    margin: 10px 0 0 26px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .images-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }

  .images-head .btn {
    margin-left: auto;
    height: 26px;
    font-size: 11.5px;
  }

  .images ul {
    list-style: none;
    margin: 0 0 10px;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(86px, 1fr));
    gap: 8px;
  }

  .images li {
    position: relative;
    border-radius: 7px;
    overflow: hidden;
    background: var(--rule);
    border: 1px solid var(--border);
  }

  .images img {
    display: block;
    width: 100%;
    aspect-ratio: 16 / 9;
    object-fit: cover;
  }

  .rank {
    position: absolute;
    top: 4px;
    left: 4px;
    padding: 1px 5px;
    border-radius: 4px;
    background: var(--ink);
    color: var(--on-ink);
    font-size: 10px;
    font-weight: 500;
  }

  /* Les commandes n'apparaissent qu'au survol : douze vignettes couvertes de
     six boutons chacune ne montreraient plus les photos. */
  .handles {
    position: absolute;
    inset: 0 0 auto auto;
    display: flex;
    gap: 2px;
    padding: 3px;
    opacity: 0;
    transition: opacity 0.12s;
  }

  .images li:hover .handles,
  .images li:focus-within .handles {
    opacity: 1;
  }

  .handles button {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    background: var(--surface);
    color: var(--ink-2);
    font-size: 12px;
    line-height: 1;
  }

  .handles button:hover {
    background: var(--ink);
    color: var(--on-ink);
  }

  .handles .drop:hover {
    background: var(--gap);
    color: var(--on-ink);
  }

  .caption {
    display: block;
    padding: 4px 6px;
    font-size: 10.5px;
    color: var(--ink-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .line.tight {
    padding: 12px 0 2px;
  }

  .note {
    margin-top: 2px;
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

  .conflict {
    border-top: 1px solid var(--border);
    background: var(--gap-row);
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
