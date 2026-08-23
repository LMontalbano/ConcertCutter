<script lang="ts">
  /* L'écran d'avant : rien n'est ouvert.

     Deux gestes, et pas un de plus — ouvrir un enregistrement, ou reprendre le
     travail d'hier. Les travaux récents sont posés là plutôt que derrière un
     menu : découper un concert de deux heures ne se fait pas d'une traite, donc
     la reprise est le cas courant, pas l'exception. */
  import { api, type RecentProject } from '../lib/api'
  import { session } from '../lib/session.svelte'
  import { savedAgo } from '../lib/format'

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
</script>

<main>
  <div class="sheet">
    <h1>ConcertCutter</h1>
    <p class="lead">
      Ouvrez l'enregistrement d'un concert : la forme d'onde s'affiche en
      quelques secondes, écoutable avant même d'analyser.
    </p>

    {#if session.dialogs}
      <div class="acts">
        <button class="btn strong" onclick={() => session.openFile('wav')}>
          Ouvrir un enregistrement
        </button>
        <button class="btn" onclick={() => session.openFile('project')}>
          Reprendre un travail…
        </button>
      </div>
    {:else}
      <!-- Sans coquille native, aucun dialogue à ouvrir : on demande le chemin.
           C'est le cas d'un serveur lancé seul, pour un contrôle automatique. -->
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
        <span class="label">Travaux en cours</span>
        {#each recent as work (work.path)}
          <button class="work" onclick={() => session.openFile('project', work.path)}>
            <span class="who">{work.name}</span>
            <span class="mono when">
              {work.tracks} morceaux · {savedAgo(work.saved) || 'enregistré'}
            </span>
          </button>
        {/each}
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
    width: min(560px, 100%);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow);
    padding: 40px 40px 32px;
  }

  h1 {
    margin: 0;
    font: 600 13px/1 var(--sans);
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .lead {
    margin: 18px 0 26px;
    font-size: 15px;
    line-height: 1.55;
    color: var(--ink-2);
  }

  .acts,
  .typed {
    display: flex;
    gap: 10px;
  }

  .typed input {
    flex: 1;
    height: 34px;
    padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    outline: none;
  }

  .typed input:focus {
    border-color: var(--accent);
  }

  .recent {
    margin-top: 30px;
    padding-top: 20px;
    border-top: 1px solid var(--rule);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .recent .label {
    margin-bottom: 8px;
  }

  .work {
    display: flex;
    align-items: baseline;
    gap: 12px;
    padding: 9px 10px;
    margin: 0 -10px;
    border-radius: var(--radius);
    text-align: left;
  }

  .work:hover {
    background: var(--rule);
  }

  .who {
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .when {
    margin-left: auto;
    font-size: 11.5px;
    color: var(--ink-3);
    white-space: nowrap;
  }
</style>
