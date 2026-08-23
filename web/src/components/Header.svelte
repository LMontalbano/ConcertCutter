<script lang="ts">
  /* La barre du haut : ce qui est ouvert, ce qui est à l'abri, et l'export. */
  import { session } from '../lib/session.svelte'
  import { hms, savedAgo } from '../lib/format'

  let { onExport, onOptions }: { onExport: () => void; onOptions: () => void } = $props()

  // Relu chaque minute : « à l'instant » cesse d'être vrai sans que rien ne se
  // passe à l'écran, et un « à l'instant » d'il y a une heure serait un
  // mensonge sur la seule chose que cette phrase promet.
  let clock = $state(Date.now())
  $effect(() => {
    const timer = setInterval(() => (clock = Date.now()), 30_000)
    return () => clearInterval(timer)
  })

  const saved = $derived((void clock, savedAgo(session.state?.saved ?? '')))
</script>

<header>
  <span class="brand">ConcertCutter</span>
  <span class="split"></span>
  <span class="name">{session.state?.name}</span>
  <span class="mono facts">
    {hms(session.duration)} · {session.counts.tracks} morceaux
  </span>

  <div class="right">
    {#if saved}<span class="saved">{saved}</span>{/if}
    <button
      class="btn quiet"
      disabled={!session.state?.canUndo}
      onclick={() => session.undo()}
      title="Annuler (Ctrl+Z)"
    >
      Annuler
    </button>
    <button
      class="btn quiet"
      disabled={!session.state?.canRedo}
      onclick={() => session.redo()}
      title="Rétablir (Ctrl+Y)"
    >
      Rétablir
    </button>
    <button class="btn quiet" onclick={onOptions}>Options</button>
    <button class="btn strong" disabled={!session.analysed} onclick={onExport}>
      Exporter
    </button>
  </div>
</header>

<style>
  header {
    display: flex;
    align-items: center;
    gap: 16px;
    height: 56px;
    flex: none;
    padding: 0 22px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
  }

  .brand {
    font: 600 13px/1 var(--sans);
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--ink);
  }

  .split {
    width: 1px;
    height: 18px;
    background: var(--border);
  }

  .name {
    font: 500 13.5px var(--sans);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 340px;
  }

  .facts {
    font-size: 12px;
    color: var(--ink-3);
    white-space: nowrap;
  }

  .right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .saved {
    font: 400 12.5px var(--sans);
    color: var(--ink-2);
    white-space: nowrap;
    margin-right: 4px;
  }
</style>
