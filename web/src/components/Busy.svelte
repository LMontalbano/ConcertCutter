<script lang="ts">
  /* Ce qui se passe pendant qu'on attend.

     Deux barres différentes, parce que deux attentes différentes : l'export
     compte des étapes et sait où il en est ; l'extraction des descripteurs ne
     compte rien, et une barre qui prétendrait le contraire mentirait. Elle
     glisse alors sans fin, ce qui dit « ça travaille » sans promettre de
     terme. */
  import type { Job } from '../lib/api'

  let { job }: { job: Job } = $props()

  const share = $derived(job.total > 0 ? Math.min(1, job.done / job.total) : 0)
</script>

<div class="veil">
  <div class="panel">
    <div class="phase">{job.phase || 'Un instant…'}</div>
    <div class="track" class:endless={job.total === 0}>
      <div class="fill" style={job.total > 0 ? `width:${share * 100}%` : ''}></div>
    </div>
    {#if job.total > 0}
      <div class="mono count">{job.done} sur {job.total}</div>
    {:else}
      <div class="mono count">durée inconnue</div>
    {/if}
  </div>
</div>

<style>
  .veil {
    position: fixed;
    inset: 0;
    background: var(--glass);
    display: grid;
    place-items: center;
    z-index: 40;
  }

  .panel {
    width: 380px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-float);
    padding: 24px 26px;
  }

  .phase {
    font: 500 14px var(--sans);
    margin-bottom: 14px;
  }

  .track {
    height: 4px;
    border-radius: 2px;
    background: var(--border);
    overflow: hidden;
  }

  .fill {
    height: 100%;
    border-radius: 2px;
    background: var(--accent);
    transition: width 0.25s ease-out;
  }

  .track.endless .fill {
    width: 34%;
    animation: slide 1.4s ease-in-out infinite;
  }

  @keyframes slide {
    0% {
      transform: translateX(-100%);
    }
    100% {
      transform: translateX(320%);
    }
  }

  .count {
    margin-top: 10px;
    font-size: 11.5px;
    color: var(--ink-3);
  }
</style>
