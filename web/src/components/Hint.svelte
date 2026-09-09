<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  /* Une explication qui ne prend de la place que si on la demande.

     La fenêtre d'export portait sous chaque case le paragraphe qui l'explique.
     Ces phrases sont justes — elles disent ce qu'on obtient, pas comment ça
     s'appelle — mais toutes déployées à la fois, elles font un mur qu'on ne lit
     plus : la troisième fois qu'on exporte, on cherche les cases entre les
     paragraphes. Elles se replient donc derrière un « ? », à côté de ce qu'elles
     expliquent.

     La bulle est posée en `fixed`, aux coordonnées relevées à l'ouverture : la
     colonne de droite défile, et une bulle en `absolute` se ferait couper par
     le bord de sa zone de défilement au lieu de flotter par-dessus. */
  let { text, side = 'top' }: { text: string; side?: 'top' | 'right' } = $props()

  const MARGIN = 12

  let badge: HTMLButtonElement
  let bubble = $state<HTMLElement | null>(null)
  let open = $state(false)
  let at = $state({ x: 0, y: 0 })
  let placed = false

  function show(): void {
    const box = badge.getBoundingClientRect()
    at =
      side === 'right'
        ? { x: box.right + 10, y: box.top + box.height / 2 }
        : { x: box.left + box.width / 2, y: box.top - 10 }
    placed = false
    open = true
  }

  /* Ramenée dans son cadre une fois mesurée.

     Le cadre, c'est le panneau de dialogue quand il y en a un, et la fenêtre
     sinon. Se contenter de la fenêtre ne suffisait pas : les bulles des deux
     réglages de fondu tenaient dans l'écran tout en débordant du panneau, et
     une explication qui déborde sur le fond assombri se lit mal — elle n'a
     plus l'air d'appartenir à ce qu'elle explique.

     On ne peut pas le savoir avant de connaître la largeur du texte, d'où ce
     second temps — invisible, la bulle n'ayant pas encore été peinte à sa
     première position. */
  $effect(() => {
    if (!open || !bubble || placed) return
    // Une seule fois par ouverture : le recadrage écrit la position qu'il
    // vient de lire, et sans ce garde-fou l'effet se rappellerait lui-même.
    placed = true

    const panel = badge.closest('[role="dialog"]')
    const frame = panel
      ? panel.getBoundingClientRect()
      : new DOMRect(0, 0, window.innerWidth, window.innerHeight)
    const box = bubble.getBoundingClientRect()
    let { x, y } = at

    const tooFarRight = box.right - (frame.right - MARGIN)
    const tooFarLeft = frame.left + MARGIN - box.left
    if (tooFarRight > 0) x -= tooFarRight
    else if (tooFarLeft > 0) x += tooFarLeft
    // Trop haut : la bulle bascule sous son « ? » plutôt que de sortir par le
    // haut du cadre.
    if (box.top < frame.top + MARGIN) y += box.height + 2 * MARGIN
    at = { x, y }
  })
</script>

<button
  bind:this={badge}
  class="badge"
  type="button"
  aria-label={t('ui.learn_more')}
  onmouseenter={show}
  onmouseleave={() => (open = false)}
  onfocus={show}
  onblur={() => (open = false)}
  onclick={(event) => event.preventDefault()}
>
  ?
</button>

{#if open}
  <span
    bind:this={bubble}
    class="bubble"
    class:right={side === 'right'}
    role="tooltip"
    style="left:{at.x}px; top:{at.y}px"
  >
    {text}
  </span>
{/if}

<style>
  .badge {
    display: inline-grid;
    place-items: center;
    width: 15px;
    height: 15px;
    margin-left: 6px;
    border-radius: 8px;
    border: 1px solid var(--border);
    color: var(--ink-3);
    font: 500 10px var(--sans);
    vertical-align: 1px;
    /* Reprend le curseur que `.badge` retire aux pastilles : celle-ci répond
       bien au survol et au clic. */
    cursor: pointer;
  }

  .badge:hover,
  .badge:focus-visible {
    background: var(--ink);
    border-color: var(--ink);
    color: var(--on-ink);
  }

  .bubble {
    position: fixed;
    z-index: 60;
    transform: translate(-50%, -100%);
    max-width: 280px;
    /* La bulle reste un enfant de ce qu'elle explique, et hérite donc de sa
       mise en page : les titres des deux réglages de fondu tiennent sur une
       ligne (`nowrap`), et la phrase sortait de la boîte au lieu d'y revenir
       à la ligne. Elle se coupe où elle veut, où qu'on la pose. */
    white-space: normal;
    overflow-wrap: break-word;
    padding: 9px 12px;
    border-radius: 9px;
    background: var(--ink);
    color: var(--on-ink);
    font: 400 12px/1.5 var(--sans);
    box-shadow: var(--shadow-float);
    pointer-events: none;
  }

  .bubble.right {
    transform: translate(0, -50%);
  }
</style>
