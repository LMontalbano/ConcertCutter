<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  /* Le concert entier, en une bande. Cliquer y déplace la loupe, et le
     rectangle clair montre ce que la carte d'édition regarde en ce moment. */
  import { session } from '../lib/session.svelte'
  import { paint, palette, slice, surface, type Palette } from '../lib/wave'
  import { hms } from '../lib/format'

  const HEIGHT = 50

  let canvas: HTMLCanvasElement
  let colours: Palette = palette()
  let width = $state(1196)

  function draw(): void {
    if (!canvas) return
    const context = surface(canvas)
    if (!context) return
    colours = palette()
    const columns = Math.max(1, Math.round(canvas.clientWidth))
    const duration = session.duration || 1
    paint(context, canvas.clientWidth, HEIGHT, {
      heights: slice(session.envelope, session.envelopeFps, 0, duration, columns),
      start: 0,
      span: duration,
      segments: session.segments,
      palette: colours,
      radius: 6,
      showCenterLine: false,
    })

    const left = (session.viewStart / duration) * canvas.clientWidth
    const right = ((session.viewStart + session.viewSpan) / duration) * canvas.clientWidth
    
    // Voile sur les zones non zoomées
    context.fillStyle = colours.veil
    context.fillRect(0, 0, left, HEIGHT)
    context.fillRect(right, 0, canvas.clientWidth - right, HEIGHT)
    
    // Cadre de la loupe active
    context.strokeStyle = colours.handleActive || colours.handle
    context.lineWidth = 1.5
    context.strokeRect(
      Math.round(left) + 0.5,
      0.5,
      Math.max(2, Math.round(right - left) - 1),
      HEIGHT - 1,
    )

    // Tête de lecture globale
    const x = (session.playhead / duration) * canvas.clientWidth
    context.fillStyle = colours.halo
    context.fillRect(x - 2, 0, 4, HEIGHT)
    context.fillStyle = colours.cursor
    context.fillRect(x - 1, 0, 2, HEIGHT)
  }

  function moment(event: MouseEvent): number {
    const box = canvas.getBoundingClientRect()
    return ((event.clientX - box.left) / box.width) * session.duration
  }

  function onClick(event: MouseEvent): void {
    const at = moment(event)
    const index = session.segments.findIndex(
      (segment) => segment.start <= at && at < segment.end,
    )
    if (index >= 0) session.select(index)
    else session.pan(at - session.viewSpan / 2)
    session.seek(at)
  }

  $effect(() => {
    void session.theme
    void session.envelope
    void session.segments
    void session.viewStart
    void session.viewSpan
    void session.playhead
    void width
    draw()
  })

  $effect(() => {
    const observer = new ResizeObserver(() => {
      width = canvas.clientWidth
    })
    observer.observe(canvas)
    return () => observer.disconnect()
  })
</script>

<section class="ribbon">
  <header>
    <span class="label">{t('ui.full_concert_view')}</span>
    <span class="rule"></span>
    <span class="hint">
      {#if session.duration}<span class="badge accent mono">{hms(session.duration)}</span>{/if}
      <span>{t('ui.click_to_move_the_detail_view')}</span>
    </span>
  </header>
  <canvas
    bind:this={canvas}
    style="height:{HEIGHT}px"
    onclick={onClick}
    aria-label={t('ui.concert_overview')}
  ></canvas>
</section>

<style>
  .ribbon {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 12px 24px 14px;
  }

  header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 8px;
  }

  .rule {
    flex: 1;
    height: 1px;
    background: var(--rule);
  }

  .hint {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  canvas {
    display: block;
    width: 100%;
    border-radius: 6px;
    cursor: crosshair;
    border: 1px solid var(--border-subtle);
  }
</style>

