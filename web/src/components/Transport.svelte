<script lang="ts">
  /* Le transport : lecture, position, durée.

     Cent soixante-quatre lignes de MCI Windows piloté par ctypes ont disparu
     ici. La balise `<audio>` les remplace et rend la lecture portable, à une
     condition que le serveur tient : servir le WAV avec les requêtes `Range`,
     pour que le navigateur ne lise que ce qu'il joue. */
  import { session } from '../lib/session.svelte'
  import { hms } from '../lib/format'

  let bar: HTMLDivElement
  let scrubbing = $state(false)

  const share = $derived(
    session.duration ? Math.min(1, session.playhead / session.duration) : 0,
  )

  function seekFrom(clientX: number): void {
    const box = bar.getBoundingClientRect()
    session.seek(((clientX - box.left) / box.width) * session.duration)
  }

  function onPointerDown(event: PointerEvent): void {
    scrubbing = true
    bar.setPointerCapture(event.pointerId)
    seekFrom(event.clientX)
  }

  function onPointerMove(event: PointerEvent): void {
    if (scrubbing) seekFrom(event.clientX)
  }

  function onPointerUp(event: PointerEvent): void {
    scrubbing = false
    bar.releasePointerCapture(event.pointerId)
  }
</script>

<footer>
  <button
    class="play"
    onclick={() => session.toggle()}
    title={session.playing ? 'Pause (espace)' : 'Lecture (espace)'}
    aria-label={session.playing ? 'Pause' : 'Lecture'}
  >
    {session.playing ? '❚❚' : '▶'}
  </button>
  <span class="mono now">{hms(session.playhead)}</span>
  <div
    class="bar"
    bind:this={bar}
    onpointerdown={onPointerDown}
    onpointermove={onPointerMove}
    onpointerup={onPointerUp}
    role="slider"
    tabindex="0"
    aria-label="Position dans le concert"
    aria-valuemin="0"
    aria-valuemax={session.duration}
    aria-valuenow={session.playhead}
  >
    <div class="done" style="width:{share * 100}%"></div>
    <div class="knob" style="left:{share * 100}%"></div>
  </div>
  <span class="mono total">{hms(session.duration)}</span>
  <button
    class="btn quiet loop"
    class:on={session.loop !== null}
    onclick={() => session.toggleLoop()}
    title="Répéter le segment sous le curseur (B)"
  >
    Boucler
  </button>
</footer>

<style>
  footer {
    margin-top: auto;
    height: 58px;
    flex: none;
    border-top: 1px solid var(--border);
    background: var(--surface);
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 0 26px;
  }

  .play {
    width: 32px;
    height: 32px;
    border-radius: 17px;
    background: var(--ink);
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    flex: none;
  }

  .now {
    font-weight: 500;
    font-size: 14px;
  }

  .total {
    font-size: 14px;
    color: var(--ink-3);
  }

  .bar {
    flex: 1;
    height: 4px;
    border-radius: 2px;
    background: var(--border);
    position: relative;
    cursor: pointer;
    touch-action: none;
  }

  .done {
    position: absolute;
    inset: 0 auto 0 0;
    border-radius: 2px;
    background: var(--ink);
  }

  .knob {
    position: absolute;
    top: -4px;
    width: 12px;
    height: 12px;
    margin-left: -6px;
    border-radius: 6px;
    background: var(--ink);
    border: 2px solid var(--surface);
  }

  .loop.on {
    background: var(--accent-soft);
    color: var(--accent);
  }
</style>
