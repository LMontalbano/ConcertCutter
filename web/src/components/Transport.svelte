<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  /* Le transport : lecture, position, durée. */
  import { session } from '../lib/session.svelte'
  import { hms } from '../lib/format'

  let bar: HTMLDivElement
  let scrubbing = $state(false)

  const share = $derived(
    session.duration ? Math.min(1, session.playhead / session.duration) : 0,
  )

  function seekFrom(clientX: number): void {
    const box = bar.getBoundingClientRect()
    const pos = Math.max(0, Math.min(1, (clientX - box.left) / box.width))
    session.seek(pos * session.duration)
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
  <div class="transport-inner">
    <button
      class="play-btn"
      class:playing={session.playing}
      onclick={() => session.toggle()}
      title={session.playing ? t('ui.pause_space') : t('ui.start_playback_space')}
      aria-label={session.playing ? t('ui.pause') : t('ui.play')}
    >
      <span class="play-glyph">{session.playing ? '❚❚' : '▶'}</span>
    </button>

    <div class="time-display mono">
      <span class="now">{hms(session.playhead)}</span>
      <span class="sep">/</span>
      <span class="total">{hms(session.duration)}</span>
    </div>

    <div
      class="bar-wrapper"
      bind:this={bar}
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      role="slider"
      tabindex="0"
      aria-label={t('ui.position_in_the_concert')}
      aria-valuemin="0"
      aria-valuemax={session.duration}
      aria-valuenow={session.playhead}
    >
      <div class="bar-track">
        <div class="bar-fill" style="width:{share * 100}%"></div>
        <div class="knob" style="left:{share * 100}%"></div>
      </div>
    </div>

    <button
      class="btn loop-btn"
      class:active={session.loop !== null}
      onclick={() => session.toggleLoop()}
      title={t('ui.loop_the_segment_under_the_playhead_b')}
    >
      <span class="loop-dot"></span>
      <span>{t('ui.loop_b')}</span>
    </button>
  </div>
</footer>

<style>
  footer {
    margin-top: auto;
    height: 72px;
    flex: none;
    border-top: 1px solid var(--border);
    background: var(--surface);
    box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.05);
    z-index: 10;
  }

  .transport-inner {
    height: 100%;
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 0 26px;
    max-width: 100%;
  }

  .play-btn {
    width: 42px;
    height: 42px;
    border-radius: 21px;
    background: var(--ink);
    color: var(--on-ink);
    display: grid;
    place-items: center;
    font-size: 13px;
    flex: none;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
    transition: all 0.12s ease;
  }

  .play-btn:hover {
    background: var(--accent);
    color: var(--on-accent);
    transform: scale(1.06);
    box-shadow: 0 4px 12px var(--accent-soft);
  }

  .play-btn:active {
    transform: scale(0.96);
  }

  .play-glyph {
    line-height: 1;
    margin-left: 2px;
  }

  .play-btn.playing .play-glyph {
    margin-left: 0;
  }

  .time-display {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 14px;
    font-weight: 600;
    min-width: 140px;
  }

  .now {
    color: var(--ink);
  }

  .sep {
    color: var(--ink-3);
    opacity: 0.5;
  }

  .total {
    color: var(--ink-3);
    font-weight: 500;
  }

  .bar-wrapper {
    flex: 1;
    height: 32px;
    display: flex;
    align-items: center;
    cursor: pointer;
    touch-action: none;
    position: relative;
  }

  .bar-track {
    width: 100%;
    height: 6px;
    border-radius: 3px;
    background: var(--surface-raised);
    border: 1px solid var(--border);
    position: relative;
    transition: height 0.1s ease;
  }

  .bar-wrapper:hover .bar-track {
    height: 8px;
    border-radius: 4px;
  }

  .bar-fill {
    position: absolute;
    inset: 0 auto 0 0;
    border-radius: 3px;
    background: var(--accent);
    box-shadow: 0 0 8px var(--accent-soft);
  }

  .knob {
    position: absolute;
    top: 50%;
    width: 14px;
    height: 14px;
    margin-left: -7px;
    transform: translateY(-50%) scale(0.85);
    border-radius: 7px;
    background: var(--ink);
    border: 2px solid var(--surface);
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
    transition: transform 0.1s ease, background 0.1s ease;
  }

  .bar-wrapper:hover .knob {
    transform: translateY(-50%) scale(1.15);
    background: var(--accent);
  }

  .loop-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 12px;
    border-radius: var(--radius);
    background: var(--surface-raised);
    border: 1px solid var(--border);
    color: var(--ink-2);
    font: 600 12px var(--sans);
    transition: all 0.12s ease;
  }

  .loop-dot {
    width: 6px;
    height: 6px;
    border-radius: 3px;
    background: var(--ink-3);
    transition: background 0.12s ease;
  }

  .loop-btn:hover {
    background: var(--hover);
    color: var(--ink);
  }

  .loop-btn.active {
    background: var(--accent-soft);
    border-color: var(--accent);
    color: var(--accent);
  }

  .loop-btn.active .loop-dot {
    background: var(--accent);
    box-shadow: 0 0 6px var(--accent);
  }
</style>

