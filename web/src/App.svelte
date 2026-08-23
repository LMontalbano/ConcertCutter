<script lang="ts">
  /* L'assemblage, et les raccourcis.

     Les raccourcis sont ceux de l'application Tkinter, à l'identique — garde-fou
     compris : ils sont neutralisés pendant une saisie, faute de quoi taper « c »
     dans un titre de morceau le couperait en deux. */
  import { api, type Job } from './lib/api'
  import { session } from './lib/session.svelte'
  import Header from './components/Header.svelte'
  import Ribbon from './components/Ribbon.svelte'
  import TrackList from './components/TrackList.svelte'
  import EditCard from './components/EditCard.svelte'
  import Transport from './components/Transport.svelte'
  import Empty from './components/Empty.svelte'
  import Busy from './components/Busy.svelte'
  import Options from './components/Options.svelte'
  import ExportDialog from './components/ExportDialog.svelte'

  let audio: HTMLAudioElement
  let exportOpen = $state(false)
  let extra = $state<Job | null>(null)

  $effect(() => {
    session.useAudio(audio)
    void session.boot()
  })

  /** Vrai quand le curseur est dans un champ : les raccourcis se taisent. */
  function typing(): boolean {
    const active = document.activeElement
    return Boolean(
      active &&
        (active.tagName === 'INPUT' ||
          active.tagName === 'TEXTAREA' ||
          (active as HTMLElement).isContentEditable),
    )
  }

  async function onKey(event: KeyboardEvent): Promise<void> {
    if (typing() || session.job || exportOpen) {
      if (event.key === 'Escape' && exportOpen) exportOpen = false
      return
    }
    const control = event.ctrlKey || event.metaKey

    if (control && event.key.toLowerCase() === 'z') {
      event.preventDefault()
      await (event.shiftKey ? session.redo() : session.undo())
      return
    }
    if (control && event.key.toLowerCase() === 'y') {
      event.preventDefault()
      await session.redo()
      return
    }
    if (control) return

    switch (event.key) {
      case ' ':
        event.preventDefault()
        session.toggle()
        break
      case 'c':
        await session.edit({ op: 'split_here', moment: session.playhead })
        break
      case 'C':
        await session.edit({ op: 'split_track', moment: session.playhead })
        break
      case 'b':
      case 'B':
        session.toggleLoop()
        break
      case 'Delete':
        await session.edit({ op: 'delete_boundary', index: session.selected })
        break
      case 'ArrowLeft':
      case 'ArrowRight':
        event.preventDefault()
        session.seek(
          (await api.navigate(
            session.playhead,
            event.key === 'ArrowRight' ? 'next' : 'previous',
          )).moment,
        )
        break
      case 'Home':
        event.preventDefault()
        session.seek((await api.navigate(session.playhead, 'section')).moment)
        break
      case 'Escape':
        session.stop()
        break
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<audio
  bind:this={audio}
  src={session.open ? api.audioUrl() : undefined}
  preload="none"
  ontimeupdate={() => session.tick(audio.currentTime)}
  onplay={() => (session.playing = true)}
  onpause={() => (session.playing = false)}
  onended={() => (session.playing = false)}
  onerror={() => session.note("L'enregistrement n'a pas pu être lu.")}
></audio>

<div class="app">
  {#if !session.open}
    <Empty />
  {:else if session.screen === 'options'}
    <Header onExport={() => (exportOpen = true)} onOptions={() => (session.screen = 'main')} />
    <Options onClose={() => (session.screen = 'main')} />
  {:else}
    <Header
      onExport={() => (exportOpen = true)}
      onOptions={() => (session.screen = 'options')}
    />
    <Ribbon />
    <div class="panes">
      {#if session.analysed}
        <TrackList />
        <div class="detail">
          <EditCard />
          <Transport />
        </div>
      {:else}
        <!-- Le concert est ouvert, l'analyse n'a pas tourné : la forme d'onde
             est déjà là et s'écoute, ce qui est tout l'intérêt de ne pas faire
             attendre l'extraction des descripteurs. -->
        <div class="detail">
          <div class="waiting">
            <p>
              La forme d'onde est là, et le concert s'écoute déjà. L'analyse
              cherche les morceaux : elle prend environ une minute par demi-heure
              d'enregistrement.
            </p>
            <button class="btn strong" onclick={() => session.analyze()}>
              Analyser
            </button>
          </div>
          <Transport />
        </div>
      {/if}
    </div>
  {/if}

  {#if session.message}
    <div class="toast">{session.message}</div>
  {/if}

  {#if session.problem}
    <div class="veil">
      <div class="alert" role="alertdialog">
        <b>Quelque chose n'a pas marché</b>
        <p>{session.problem}</p>
        <div class="issues">
          {#if session.problem.includes('introuvable')}
            <button
              class="btn accent"
              onclick={() => {
                session.problem = ''
                void session.openFile('project')
              }}
            >
              Choisir un autre fichier…
            </button>
          {/if}
          <button class="btn" onclick={() => (session.problem = '')}>Fermer</button>
        </div>
      </div>
    </div>
  {/if}
</div>

{#if session.job}
  <Busy job={session.job} />
{:else if extra}
  <Busy job={extra} />
{/if}

{#if exportOpen}
  <ExportDialog
    onClose={() => (exportOpen = false)}
    onBusy={(job) => (extra = job)}
  />
{/if}

<style>
  .app {
    height: 100vh;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  .panes {
    flex: 1;
    display: flex;
    min-height: 0;
  }

  .detail {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
  }

  .waiting {
    flex: 1;
    display: grid;
    place-content: center;
    justify-items: center;
    gap: 18px;
    padding: 40px;
    text-align: center;
  }

  .waiting p {
    max-width: 46ch;
    margin: 0;
    color: var(--ink-2);
    line-height: 1.6;
  }

  .toast {
    position: fixed;
    left: 50%;
    bottom: 74px;
    transform: translateX(-50%);
    background: var(--ink);
    color: #fff;
    font-size: 12.5px;
    padding: 9px 16px;
    border-radius: 20px;
    box-shadow: var(--shadow-float);
    z-index: 20;
    pointer-events: none;
    max-width: 70vw;
  }

  .veil {
    position: fixed;
    inset: 0;
    background: rgba(27, 32, 41, 0.28);
    display: grid;
    place-items: center;
    z-index: 50;
  }

  .alert {
    width: min(460px, 90vw);
    background: var(--surface);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-float);
    padding: 22px 24px;
  }

  .alert p {
    margin: 10px 0 18px;
    color: var(--ink-2);
    font-size: 13px;
    line-height: 1.55;
    white-space: pre-wrap;
  }

  .issues {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
  }
</style>
