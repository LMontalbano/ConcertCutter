<script lang="ts">
  /* La barre du haut : ce qui est ouvert, ce qui est à l'abri, et l'export. */
  import { session } from '../lib/session.svelte'
  import { hms, savedAgo } from '../lib/format'

  let {
    onExport,
    onOptions,
  }: { onExport: () => void; onOptions: () => void } = $props()

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

<!--
  Trois groupes, séparés par un filet, et dans l'ordre où l'on s'en sert :
  ce qu'on défait, ce qu'on règle, ce qu'on produit.

  Les boutons étaient auparavant alignés à la file — Importer, thème, Annuler,
  Rétablir, Options, Exporter — sans que rien ne dise lesquels vont ensemble.
  « Importer » y voisinait avec « Annuler », qui n'ont ni la même portée ni les
  mêmes conséquences, et le soleil du thème tombait au milieu de l'édition.

  Ce qui décrit le document — son nom, sa durée, l'heure du dernier
  enregistrement — reste à gauche avec lui : ce n'est pas une commande, et
  l'aligner parmi des boutons invitait à cliquer dessus.
-->
<header>
  <span class="brand">ConcertCutter</span>
  <span class="split"></span>
  <div class="doc">
    <span class="name">{session.state?.name}</span>
    <span class="mono facts">
      {hms(session.duration)} · {session.counts.tracks} morceaux{saved ? ` · ${saved.toLowerCase()}` : ''}
    </span>
  </div>

  <div class="right">
    <div class="group">
      <button
        class="btn quiet icon"
        disabled={!session.state?.canUndo}
        onclick={() => session.undo()}
        aria-label="Annuler"
        title="Annuler (Ctrl+Z)"
      >
        ↺
      </button>
      <button
        class="btn quiet icon"
        disabled={!session.state?.canRedo}
        onclick={() => session.redo()}
        aria-label="Rétablir"
        title="Rétablir (Ctrl+Y)"
      >
        ↻
      </button>
    </div>

    <span class="split"></span>

    <div class="group">
      <button
        class="btn quiet"
        onclick={() => session.openFile('wav')}
        title="Ouvrir un autre enregistrement, ou reprendre un travail"
      >
        Importer
      </button>
      <button class="btn quiet" onclick={onOptions} title="Réglages de détection et de montage">
        Options
      </button>
      <button
        class="btn quiet icon"
        onclick={() => session.flip()}
        aria-label={session.theme === 'dark' ? 'Passer en clair' : 'Passer en sombre'}
        title={session.theme === 'dark' ? 'Passer en clair' : 'Passer en sombre'}
      >
        {session.theme === 'dark' ? '☀' : '☾'}
      </button>
    </div>

    <span class="split"></span>

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

  .doc {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .name {
    font: 500 13.5px var(--sans);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 420px;
  }

  .facts {
    font-size: 11.5px;
    color: var(--ink-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .right {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 12px;
  }

  /* Les boutons d'un même groupe se touchent presque ; ce sont les filets et
     l'écart entre groupes qui font la séparation. */
  .group {
    display: flex;
    align-items: center;
    gap: 2px;
  }

  .icon {
    width: 32px;
    padding: 0;
    justify-content: center;
    font-size: 15px;
  }
</style>
