<script lang="ts">
  /* L'écran d'accueil : ouvrir un enregistrement ou reprendre un travail. */
  import { api, type RecentProject } from '../lib/api'
  import { session } from '../lib/session.svelte'
  import { savedAgo } from '../lib/format'
  import logoUrl from '../assets/logo_128.png'

  let recent = $state<RecentProject[]>([])
  let typed = $state('')
  let isDragging = $state(false)

  $effect(() => {
    void api
      .recent()
      .then((found) => {
        recent = found.projects
        session.dialogs = found.dialogs
      })
      .catch(() => {})
  })

  function onDragOver(event: DragEvent): void {
    event.preventDefault()
    isDragging = true
  }

  function onDragLeave(event: DragEvent): void {
    event.preventDefault()
    isDragging = false
  }

  function onDrop(event: DragEvent): void {
    event.preventDefault()
    isDragging = false
    const files = event.dataTransfer?.files
    if (!files || !files.length) return
    const file = files[0]
    // Sur Electron/WebView2 ou navigateur compatible, file.path existe
    const path = (file as unknown as { path?: string }).path || file.name
    if (path) {
      void session.openFile(path.toLowerCase().endsWith('.json') ? 'project' : 'wav', path)
    }
  }
</script>

<main
  ondragover={onDragOver}
  ondragleave={onDragLeave}
  ondrop={onDrop}
>
  <div class="sheet" class:dragging={isDragging}>
    <div class="header-badge">
      <img class="hero-logo" src={logoUrl} alt="Logo ConcertCutter" width="40" height="40" />
      <div class="hero-title-group">
        <h1>ConcertCutter</h1>
        <span class="hero-tagline">Découpage & Montage Audio</span>
      </div>
    </div>

    <p class="lead">
      Découpez automatiquement un concert enregistré en morceaux, en retirant les blancs et applaudissements.
    </p>

    {#if session.dialogs}
      <div class="dropzone" class:active={isDragging}>
        <div class="drop-content">
          <span class="drop-icon">🎵</span>
          <div class="drop-text">
            <strong>Glissez votre fichier WAV ici</strong>
            <span>ou utilisez les boutons ci-dessous</span>
          </div>
        </div>

        <div class="acts">
          <button class="btn strong open-btn" onclick={() => session.openFile('wav')}>
            <span>Ouvrir un enregistrement WAV</span>
          </button>
          <button class="btn resume-btn" onclick={() => session.openFile('project')}>
            <span>Reprendre un travail…</span>
          </button>
        </div>
      </div>
    {:else}
      <form class="typed" onsubmit={(event) => (event.preventDefault(), session.openFile('wav', typed))}>
        <input
          bind:value={typed}
          placeholder="C:\chemin\vers\le concert.wav"
          spellcheck="false"
        />
        <button class="btn strong" type="submit">Ouvrir</button>
      </form>
    {/if}

    {#if recent.length}
      <div class="recent">
        <div class="recent-header">
          <span class="label">Travaux récents</span>
          <span class="hint">Reprise instantanée</span>
        </div>
        <div class="recent-list">
          {#each recent as work (work.path)}
            <button class="work" onclick={() => session.openFile('project', work.path)}>
              <div class="work-icon">💿</div>
              <div class="work-info">
                <span class="who">{work.name}</span>
                <span class="mono when">
                  {savedAgo(work.saved) || 'enregistré'}
                </span>
              </div>
              <span class="badge accent">{work.tracks} morceaux</span>
            </button>
          {/each}
        </div>
      </div>
    {/if}
  </div>
</main>

<style>
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
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }

  .sheet.dragging {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft), var(--shadow-float);
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

  .dropzone {
    border: 2px dashed var(--border);
    border-radius: var(--radius);
    padding: 24px 20px;
    background: var(--surface-raised);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 18px;
    transition: all 0.15s ease;
  }

  .dropzone.active {
    border-color: var(--accent);
    background: var(--accent-soft);
  }

  .drop-content {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    text-align: center;
  }

  .drop-icon {
    font-size: 28px;
  }

  .drop-text strong {
    display: block;
    font-size: 14px;
    font-weight: 600;
    color: var(--ink);
  }

  .drop-text span {
    font-size: 12px;
    color: var(--ink-3);
  }

  .acts {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    justify-content: center;
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

