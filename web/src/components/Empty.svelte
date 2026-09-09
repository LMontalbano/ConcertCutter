<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  /* L'écran d'accueil : ouvrir un enregistrement ou reprendre un travail. */
  import { api, type RecentProject } from '../lib/api'
  import { session } from '../lib/session.svelte'
  import { savedAgo } from '../lib/format'
  import logoUrl from '../assets/logo_128.png'

  let recent = $state<RecentProject[]>([])
  let typed = $state('')

  $effect(() => {
    void api
      .recent()
      .then((found) => {
        recent = found.projects
        session.dialogs = found.dialogs
      })
      .catch(() => {})
  })

  /* Pas de dépôt de fichier ici, et c'est une contrainte, pas un oubli.

     Il y en avait un. Il lisait `file.path` — une extension d'Electron, que
     WebView2 n'a pas, et qu'Electron lui-même a retirée. La propriété valait
     donc toujours `undefined`, le repli prenait `file.name`, et ConcertCutter
     recevait « concert.wav » sans dossier : un chemin relatif que le serveur
     résolvait depuis son dossier de travail. Au mieux « fichier introuvable »,
     au pire l'ouverture d'un homonyme sans rapport. La bannière promettait
     pourtant, en gras, de glisser son enregistrement ici.

     Le navigateur ne donne jamais de chemin — c'est délibéré de sa part, et
     tout `read_span` de ce programme prend un `Path`. Remonter deux
     gigaoctets par le tuyau HTTP pour les redescendre serait absurde là où le
     fichier est déjà sur le disque du serveur. Le sélecteur natif reste donc
     la seule porte, et on ne dessine plus l'autre. */
</script>

<main>
  <div class="sheet">
    <div class="header-badge">
      <img class="hero-logo" src={logoUrl} alt={t('ui.concertcutter_logo')} width="40" height="40" />
      <div class="hero-title-group">
        <h1>ConcertCutter</h1>
        <span class="hero-tagline">{t('ui.audio_splitting_editing')}</span>
      </div>
    </div>

    <p class="lead">{t('ui.automatically_split_a_recorded_concert_into_tracks_removing')}</p>

    {#if session.dialogs}
      <div class="acts">
        <button class="btn strong open-btn" onclick={() => session.openFile('wav')}>
          <span>{t('ui.open_a_wav_recording')}</span>
        </button>
        <button class="btn resume-btn" onclick={() => session.openFile('project')}>
          <span>{t('ui.resume_a_project')}</span>
        </button>
      </div>
    {:else}
      <form class="typed" onsubmit={(event) => (event.preventDefault(), session.openFile('wav', typed))}>
        <input
          bind:value={typed}
          placeholder={t('ui.c_path_to_concert_wav')}
          spellcheck="false"
        />
        <button class="btn strong" type="submit">{t('ui.open')}</button>
      </form>
    {/if}

    {#if recent.length}
      <div class="recent">
        <div class="recent-header">
          <span class="label">{t('ui.recent_projects')}</span>
          <span class="hint">{t('ui.resume_instantly')}</span>
        </div>
        <div class="recent-list">
          {#each recent as work (work.path)}
            <button class="work" onclick={() => session.openFile('project', work.path)}>
              <div class="work-icon">💿</div>
              <div class="work-info">
                <span class="who">{work.name}</span>
                <span class="mono when">
                  {savedAgo(work.saved) || t('ui.saved')}
                </span>
              </div>
              <span class="badge accent">{t('count.tracks', { count: work.tracks })}</span>
            </button>
          {/each}
        </div>
      </div>
    {/if}
    <div class="preferences-link">
      <button class="btn quiet" onclick={() => (session.screen = 'options')}>{t('ui.options')}</button>
    </div>
  </div>
</main>

<style>
  .preferences-link { margin-top: 18px; display: flex; justify-content: flex-end; }
  main {
    flex: 1;
    display: grid;
    place-items: center;
    padding: 40px;
    min-height: 0;
    overflow-y: auto;
  }

  .sheet {
    width: min(600px, 100%);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-float);
    padding: 38px 36px 32px;
  }

  .header-badge {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  .hero-logo {
    width: 44px;
    height: 44px;
    border-radius: 10px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
    flex: none;
  }

  .hero-title-group {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  h1 {
    margin: 0;
    font: 700 16px/1 var(--sans);
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--ink);
  }

  .hero-tagline {
    font: 500 12px var(--sans);
    color: var(--ink-3);
  }

  .lead {
    margin: 14px 0 24px;
    font-size: 14.5px;
    line-height: 1.5;
    color: var(--ink-2);
  }

  .acts {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }

  .open-btn {
    height: 36px;
    padding: 0 18px;
  }

  .resume-btn {
    height: 36px;
    background: var(--surface);
  }

  .typed {
    display: flex;
    gap: 10px;
  }

  .typed input {
    flex: 1;
    height: 36px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface-raised);
    color: var(--ink);
    outline: none;
  }

  .typed input:focus {
    border-color: var(--accent);
  }

  .recent {
    margin-top: 28px;
    padding-top: 22px;
    border-top: 1px solid var(--rule);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .recent-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .recent-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .work {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    border-radius: var(--radius);
    background: var(--surface-raised);
    border: 1px solid var(--border-subtle);
    text-align: left;
    transition: all 0.12s ease;
  }

  .work:hover {
    background: var(--hover);
    border-color: var(--border);
    transform: translateX(2px);
  }

  .work-icon {
    font-size: 18px;
    flex: none;
    opacity: 0.8;
  }

  .work-info {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .who {
    font-weight: 600;
    font-size: 13.5px;
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .when {
    font-size: 11.5px;
    color: var(--ink-3);
    white-space: nowrap;
  }
</style>

