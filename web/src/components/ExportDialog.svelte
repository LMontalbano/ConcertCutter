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
        <h2><span class="step">1</span> Quels morceaux ?</h2>
        <p class="why">
          Décocher un morceau ici ne change ni le découpage ni la numérotation :
          la piste 7 s'appellera « 07 » même si elle part seule. Pour retirer un
          passage du concert lui-même, c'est la carte d'édition.
        </p>
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

      <section>
        <h2><span class="step">2</span> Sous quelle forme ?</h2>

        <span class="label">Audio</span>
        <label class="line">
          <input type="checkbox" bind:checked={choice.full} />
          <span>
            <b>Le concert en un seul fichier</b>
            <em>
              Un seul WAV : les morceaux bout à bout, blancs retirés. Une cue
              sheet l'accompagne dans « infos », pour retrouver les morceaux à
              la lecture ou à la gravure.
            </em>
          </span>
        </label>
        <label class="line">
          <input type="checkbox" bind:checked={choice.tracks} />
          <span>
            <b>Un fichier par morceau</b>
            <em>
              Numéroté et nommé d'après le titre saisi. C'est ce qu'attend un
              lecteur ou une clé USB.
            </em>
          </span>
        </label>

        <div class="knob" class:off={!choice.full}>
          <label for="crossfade">Fondu enchaîné</label>
          <input
            id="crossfade"
            class="mono"
            type="number"
            min="0"
            step="0.5"
            bind:value={choice.crossfade}
          />
          <span class="unit">s</span>
          <em>
            N'agit que sur le concert en un seul fichier : la fin d'un morceau
            se fond dans le début du suivant. À zéro, ils se suivent bout à
            bout, comme sur un disque.
          </em>
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
            <span>
              <b>Un MP4 du concert entier</b>
              <em>
                Sur l'image de fond. Le titre affiché suit le morceau en cours
                plutôt que de rester figé deux heures.
              </em>
            </span>
          </label>
          <label class="line">
            <input type="checkbox" bind:checked={choice.video_tracks} />
            <span>
              <b>Un MP4 par morceau</b>
              <em>
                Son titre incrusté. C'est la forme qu'attendent les plateformes
                qui n'acceptent que de la vidéo.
              </em>
            </span>
          </label>

          <div class="images" class:off={!choice.video_full && !choice.video_tracks}>
            <div class="images-head">
              <span class="label">Fonds</span>
              <button class="btn quiet" onclick={addImages}>Ajouter des images…</button>
            </div>
            {#if choice.images.length}
              <ul>
                {#each choice.images as image, index (image + index)}
                  <li>
                    <span class="mono rank">{index + 1}</span>
                    <span class="path" title={image}>{image.split(/[\\/]/).pop()}</span>
                    <button onclick={() => moveImage(index, -1)} aria-label="Monter">↑</button>
                    <button onclick={() => moveImage(index, 1)} aria-label="Descendre">↓</button>
                    <button
                      onclick={() =>
                        (choice.images = choice.images.filter((_, rank) => rank !== index))}
                      aria-label="Retirer"
                    >
                      ×
                    </button>
                  </li>
                {/each}
              </ul>
              <em class="note">
                Les images se relaient dans l'ordre de la liste, une toutes les
                huit secondes, et le cycle recommence aussi longtemps que dure
                le son. Chacune garde ses proportions et se centre sur du noir.
              </em>
              <div class="knob">
                <label for="slide">Fondu entre images</label>
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
            {:else}
              <em class="note">
                Photos du concert, pochette, affiche. Le titre du morceau est
                incrusté par-dessus.
              </em>
            {/if}
          </div>
        {/if}
      </section>

      <section>
        <h2><span class="step">3</span> Où ?</h2>
        <p class="why">
          Le concert reçoit son propre dossier ici, nommé d'après
          l'enregistrement. Un export déjà présent n'est jamais écrasé sans
          qu'on le demande.
        </p>
        <div class="dir">
          <input class="mono" bind:value={choice.dir} placeholder="Aucun dossier choisi" />
          {#if session.dialogs}
            <button class="btn" onclick={chooseDir}>Parcourir…</button>
          {/if}
        </div>
      </section>
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
    background: rgba(27, 32, 41, 0.28);
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

  .body {
    flex: 1;
    overflow-y: auto;
    padding: 4px 24px 20px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0 28px;
    align-items: start;
  }

  section {
    padding: 20px 0 4px;
  }

  /* La première question occupe la colonne de gauche sur toute la hauteur :
     vingt-cinq morceaux ne tiennent pas sous un titre. */
  section:first-child {
    grid-row: span 2;
  }

  h2 {
    display: flex;
    align-items: center;
    gap: 9px;
    margin: 0 0 10px;
    font: 600 14px var(--sans);
  }

  .step {
    display: grid;
    place-items: center;
    width: 20px;
    height: 20px;
    border-radius: 10px;
    background: var(--ink);
    color: #fff;
    font: 600 11px var(--mono);
  }

  .why {
    margin: 0 0 14px;
    font-size: 12px;
    line-height: 1.5;
    color: var(--ink-3);
  }

  .picks {
    max-height: 320px;
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
    padding: 9px 0;
    align-items: flex-start;
  }

  .line input {
    margin-top: 2px;
  }

  .line b {
    display: block;
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

  .knob em {
    grid-column: 1 / -1;
    margin-top: 2px;
  }

  .knob label {
    font-size: 12.5px;
    font-weight: 500;
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
    margin: 0 0 8px;
    padding: 0;
    max-height: 108px;
    overflow-y: auto;
  }

  .images li {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 0;
    font-size: 12px;
  }

  .rank {
    color: var(--ink-3);
    font-size: 11px;
    width: 14px;
  }

  .path {
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .images li button {
    width: 22px;
    height: 22px;
    border-radius: 5px;
    color: var(--ink-3);
  }

  .images li button:hover {
    background: var(--rule);
    color: var(--ink);
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
