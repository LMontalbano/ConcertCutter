<script lang="ts">
  /* La barre du haut : ce qui est ouvert, ce qui est à l'abri, et l'export. */
  import { session } from '../lib/session.svelte'
  import { hms, savedAgo } from '../lib/format'
  import logoUrl from '../assets/logo.png'

  let {
    onExport,
    onOptions,
  }: { onExport: () => void; onOptions: () => void } = $props()

  let clock = $state(Date.now())
  $effect(() => {
    const timer = setInterval(() => (clock = Date.now()), 30_000)
    return () => clearInterval(timer)
  })

  const saved = $derived((void clock, savedAgo(session.state?.saved ?? '')))
</script>

<header>
  <div class="left">
    <div class="brand-group">
      <img class="brand-logo" src={logoUrl} alt="Logo ConcertCutter" width="24" height="24" />
      <span class="brand">ConcertCutter</span>
    </div>

    <span class="split"></span>

    <div class="doc">
      <span class="name" title={session.state?.name}>{session.state?.name}</span>
      <div class="meta">
        <span class="mono badge accent">{hms(session.duration)}</span>
        <span class="badge">{session.counts.tracks} morceaux</span>
        {#if saved}
          <span class="saved-status" title={saved}>
            <span class="dot"></span>
            <span class="saved-text">{saved.toLowerCase()}</span>
          </span>
        {/if}
      </div>
    </div>
  </div>

  <div class="right">
    <div class="group" role="toolbar" aria-label="Historique">
      <button
        class="btn quiet icon"
        disabled={!session.state?.canUndo}
        onclick={() => session.undo()}
        aria-label="Annuler"
        title="Annuler (Ctrl+Z)"
      >
        <span class="icon-glyph">↺</span>
      </button>
      <button
        class="btn quiet icon"
        disabled={!session.state?.canRedo}
        onclick={() => session.redo()}
        aria-label="Rétablir"
        title="Rétablir (Ctrl+Y)"
      >
        <span class="icon-glyph">↻</span>
      </button>
    </div>

    <span class="split"></span>

    <div class="group" role="toolbar" aria-label="Projet et réglages">
      <button
        class="btn quiet"
        onclick={() => session.openFile('wav')}
        title="Ouvrir un autre enregistrement, ou reprendre un travail"
      >
        <span>Importer…</span>
      </button>
      <button class="btn quiet" onclick={onOptions} title="Réglages de détection et de montage">
        <span>Options</span>
      </button>
      <button
        class="btn quiet icon theme-btn"
        onclick={() => session.flip()}
        aria-label={session.theme === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre'}
        title={session.theme === 'dark' ? 'Passer en clair' : 'Passer en sombre'}
      >
        <span class="theme-icon">{session.theme === 'dark' ? '☀' : '☾'}</span>
      </button>
    </div>

    <span class="split"></span>

    <button
      class="btn strong export-btn"
      disabled={!session.analysed}
      onclick={onExport}
      title="Exporter le concert et ses morceaux"
    >
      <span>Exporter</span>
    </button>
  </div>
</header>

<style>
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    height: 60px;
    flex: none;
    padding: 0 24px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    box-shadow: var(--shadow);
    z-index: 10;
  }

  .left {
    display: flex;
    align-items: center;
    gap: 16px;
    min-width: 0;
  }

  .brand-group {
    display: flex;
    align-items: center;
    gap: 8px;
    flex: none;
  }

  .brand-logo {
    width: 24px;
    height: 24px;
    border-radius: 6px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
  }

  .brand {
    font: 700 13px/1 var(--sans);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--ink);
  }

  .split {
    width: 1px;
    height: 22px;
    background: var(--border);
    flex: none;
  }

  .doc {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .name {
    font: 600 14px/1.2 var(--sans);
    color: var(--ink);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 380px;
  }

  .meta {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11.5px;
  }

  .saved-status {
    display: flex;
    align-items: center;
    gap: 5px;
    color: var(--ink-3);
    font-size: 11px;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 3px;
    background: var(--accent);
    opacity: 0.85;
  }

  .saved-text {
    white-space: nowrap;
  }

  .right {
    display: flex;
    align-items: center;
    gap: 12px;
    flex: none;
  }

  .group {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .icon {
    width: 34px;
    height: 32px;
    padding: 0;
    justify-content: center;
  }

  .icon-glyph {
    font-size: 16px;
    line-height: 1;
  }

  .theme-icon {
    font-size: 15px;
  }

  .export-btn {
    padding: 0 20px;
    letter-spacing: 0.02em;
  }
</style>

