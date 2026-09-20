import { tick } from 'svelte'

/* Le comportement commun des fenêtres modales.

   Les quatre fenêtres de l'application en avaient besoin, trois l'avaient
   recopié, et la quatrième — le montage vidéo — s'en passait : la tabulation
   en sortait vers l'application restée derrière, et le focus ne revenait pas
   d'où il venait. Le comportement vit ici pour qu'une modale de plus n'ait
   pas à le redécouvrir.

   Trois choses, et rien d'autre : Échap ferme, Tab tourne en rond dans le
   panneau, et le focus retourne à son point de départ quand on s'en va. */

const FOCUSABLE = [
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

export interface ModalOptions {
  onClose: () => void
  /** Ce qui prend le focus à l'ouverture. Par défaut, le premier contrôle.

      L'éditeur de montage y désigne sa commande de lecture : Espace est son
      geste le plus fréquent, et le poser sur la croix de fermeture en aurait
      fait une sortie accidentelle. */
  autofocus?: string
}

export function modal(panel: HTMLElement, options: ModalOptions) {
  let settings = options
  const previous = document.activeElement as HTMLElement | null

  /** Les contrôles réellement atteignables — `offsetParent` écarte ce qui est
      masqué, par exemple les boutons d'une section repliée. */
  function reachable(): HTMLElement[] {
    return [...panel.querySelectorAll<HTMLElement>(FOCUSABLE)]
      .filter((item) => item.offsetParent !== null)
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault()
      // Une modale posée sur une autre — la confirmation d'écrasement sur le
      // montage — ne doit fermer qu'elle-même.
      event.stopPropagation()
      settings.onClose()
      return
    }
    if (event.key !== 'Tab') return
    const focusable = reachable()
    if (!focusable.length) {
      event.preventDefault()
      panel.focus()
      return
    }
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  panel.addEventListener('keydown', onKeyDown)
  void tick().then(() => {
    const wanted = settings.autofocus
      ? panel.querySelector<HTMLElement>(settings.autofocus)
      : null
    ;(wanted ?? reachable()[0] ?? panel).focus()
  })

  return {
    update(next: ModalOptions): void {
      settings = next
    },
    destroy(): void {
      panel.removeEventListener('keydown', onKeyDown)
      previous?.focus()
    },
  }
}
