<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  /* Ce qui se passe pendant qu'on attend.

     Deux barres différentes, parce que deux attentes différentes : l'export
     compte des étapes et sait où il en est ; l'extraction des descripteurs ne
     compte rien, et une barre qui prétendrait le contraire mentirait. Elle
     glisse alors sans fin, ce qui dit « ça travaille » sans promettre de
     terme. */
  import { api, type Job } from '../lib/api'

  let { job }: { job: Job } = $props()

  const share = $derived(job.total > 0 ? Math.min(1, job.done / job.total) : 0)

  /* Seul l'export s'arrête. L'analyse dure une minute et ne laisse rien
     derrière elle ; l'export en dure cinq, davantage avec des vidéos, et c'est
     là qu'on s'aperçoit qu'on a coché la mauvaise case. */
  const stoppable = $derived(job.kind === 'export' && job.state === 'running')

  let asked = $state(false)

  async function stop(): Promise<void> {
    asked = true
    try {
      await api.cancel(job.id)
    } catch {
      /* Un travail déjà fini ne se laisse pas arrêter, et n'a plus à l'être. */
    }
  }
</script>

<div class="veil">
  <div class="panel">
    <div class="phase">{job.phase || t('ui.one_moment')}</div>
    <div class="track" class:endless={job.total === 0}>
      <div class="fill" style={job.total > 0 ? `width:${share * 100}%` : ''}></div>
    </div>
    <!-- Rien sous la barre quand on ne compte pas d'étapes. « Durée inconnue »
         y figurait, et c'était la seule chose que la fenêtre disait pendant
         une lecture de quinze secondes : une phrase qui n'apprend rien vaut
         moins que le silence. -->
    {#if job.total > 0}
      <div class="mono count">
        {job.kind === 'update'
          ? t('update.download_progress', {
              done: (job.done / 1024 / 1024).toFixed(1),
              total: (job.total / 1024 / 1024).toFixed(1),
            })
          : t('progress.count', { done: job.done, total: job.total })}
      </div>
    {/if}

    <!-- L'arrêt se demande, il ne s'impose pas : l'export finit le morceau
         qu'il tient avant de se dénouer, ce qui peut prendre le temps d'un
         encodage. Le bouton dit donc ce qui se passe plutôt que de disparaître
         et laisser croire que le clic s'est perdu. -->
    {#if stoppable}
      <div class="acts">
        <button class="btn quiet" onclick={stop} disabled={asked}>
          {asked ? t('ui.stop_requested') : t('ui.stop_export')}
        </button>
      </div>
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
    margin-top: 12px;
    font-size: 11.5px;
    color: var(--ink-3);
  }

  .acts {
    margin-top: 16px;
    display: flex;
    justify-content: flex-end;
  }
</style>
