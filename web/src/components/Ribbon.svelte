<script lang="ts">
  /* Le concert entier, en une bande. Cliquer y déplace la loupe, et le
     rectangle clair montre ce que la carte d'édition regarde en ce moment. */
  import { session } from '../lib/session.svelte'
  import { paint, palette, slice, surface, type Palette } from '../lib/wave'
  import { hms } from '../lib/format'

  const HEIGHT = 46

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
    })

    // La fenêtre de la loupe, en creux : on assombrit ce qu'on ne regarde pas
    // plutôt que d'encadrer ce qu'on regarde — le cadre se perdait dans le
    // tracé dès que la fenêtre devenait étroite.
    const left = (session.viewStart / duration) * canvas.clientWidth
    const right = ((session.viewStart + session.viewSpan) / duration) * canvas.clientWidth
    // Assombrir ce qu'on ne regarde pas, plutôt qu'encadrer ce qu'on regarde :
    // le cadre se perdait dans le tracé dès que la fenêtre devenait étroite.
    // La teinte suit le thème — un voile clair sur fond sombre effacerait le
    // concert au lieu de le mettre en retrait.
    context.fillStyle = colours.veil
    context.fillRect(0, 0, left, HEIGHT)
    context.fillRect(right, 0, canvas.clientWidth - right, HEIGHT)
    context.strokeStyle = colours.handle
    context.lineWidth = 1
    context.strokeRect(
      Math.round(left) + 0.5,
      0.5,
      Math.max(2, Math.round(right - left) - 1),
      HEIGHT - 1,
    )

    const x = (session.playhead / duration) * canvas.clientWidth
    context.fillStyle = colours.handle
    context.fillRect(x - 0.5, 0, 1, HEIGHT)
  }

  function moment(event: MouseEvent): number {
    const box = canvas.getBoundingClientRect()
    return ((event.clientX - box.left) / box.width) * session.duration
  }

  function onClick(event: MouseEvent): void {
    const at = moment(event)
    // Cliquer déplace la loupe, et cale la sélection sur ce qu'on désigne :
    // regarder un endroit du concert sans que la carte suive n'aurait servi à
    // rien.
    const index = session.segments.findIndex(
      (segment) => segment.start <= at && at < segment.end,
    )
    if (index >= 0) session.select(index)
    else session.pan(at - session.viewSpan / 2)
    session.seek(at)
  }

  $effect(() => {
    // Toutes les dépendances lues ici déclenchent le redessin : l'enveloppe,
    // les segments, la fenêtre, la tête de lecture.
    // Le thème repeint : les couleurs du tracé sont lues au moment de
    // peindre, mais rien ne redemandait de peindre. Basculer en clair
    // laissait le lit des ondes en sombre jusqu'au geste suivant.
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
    <span class="label">Le concert</span>
    <span class="rule"></span>
    <span class="hint">
      {#if session.duration}{hms(session.duration)} · {/if}cliquer pour déplacer la loupe
    </span>
  </header>
  <canvas
    bind:this={canvas}
    style="height:{HEIGHT}px"
    onclick={onClick}
    aria-label="Vue d'ensemble du concert"
  ></canvas>
</section>

<style>
  .ribbon {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 12px 22px 14px;
  }

  header {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }

  .rule {
    flex: 1;
    height: 1px;
    background: var(--rule);
  }

  canvas {
    display: block;
    width: 100%;
    border-radius: 6px;
    cursor: crosshair;
  }
</style>
