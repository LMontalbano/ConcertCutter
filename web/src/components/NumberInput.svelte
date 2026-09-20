<script lang="ts">
  import { locale, t } from '../lib/i18n.svelte'

  /* `parse` et `format` ouvrent le champ à autre chose qu'un décimal nu.

     L'inspecteur de montage y écrit des instants : sur un concert de deux
     heures, taper « 3754,5 » pour dire 1:02:34 n'est pas une saisie, c'est un
     calcul mental. Sans ces deux fonctions, le champ garde exactement le
     comportement qu'il avait — c'est ce que font les réglages et l'export. */
  let { id, value = $bindable(), min = 0, max, step = 0.1, disabled = false,
    parse, format, title, onchange }:
    { id: string; value: number; min?: number; max: number; step?: number
      disabled?: boolean
      parse?: (text: string) => number | null
      format?: (value: number) => string
      title?: string
      /* Pour les champs dont la valeur ne s'écrit pas telle quelle.

         L'inspecteur de montage borne ce qu'on tape — un clip ne peut pas
         commencer sur son voisin — et `bind:value` lui ferait accepter puis
         corriger. Il écoute donc la saisie et décide lui-même. */
      onchange?: (value: number) => void } = $props()
  let input: HTMLInputElement
  let raw = $state('')
  let focused = $state(false)
  let displayedLanguage = $state('')

  function formatted(number: number): string {
    if (!Number.isFinite(number)) return ''
    if (format) return format(number)
    return new Intl.NumberFormat(locale.effectiveLanguage,
      { useGrouping: false, maximumFractionDigits: 10 }).format(number)
  }

  function validate(): void {
    const invalid = !Number.isFinite(value) || value < min || value > max || (step === 1 && !Number.isInteger(value))
    input?.setCustomValidity(invalid ? t('number.invalid', { min, max }) : '')
  }

  $effect(() => {
    const language = locale.effectiveLanguage
    if (!focused || displayedLanguage !== language) raw = formatted(value)
    displayedLanguage = language
    validate()
  })

  function edit(event: Event): void {
    raw = (event.target as HTMLInputElement).value
    if (parse) {
      const read = parse(raw)
      value = read === null ? NaN : read
    } else {
      const cleaned = raw.trim().replace(',', '.')
      value = /^\d+(?:\.\d*)?$/.test(cleaned) ? Number(cleaned) : NaN
    }
    validate()
    if (Number.isFinite(value) && value >= min && value <= max) onchange?.(value)
  }

  function nudge(event: KeyboardEvent): void {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
    event.preventDefault()
    const current = Number.isFinite(value) ? value : min
    value = Math.min(max, Math.max(min, Number((current + (event.key === 'ArrowUp' ? step : -step)).toFixed(10))))
    raw = formatted(value)
    validate()
    onchange?.(value)
  }
</script>

<!-- A native number input follows Chromium's own locale, even when HTML lang changes. -->
<input bind:this={input} {id} type="text" inputmode="decimal" class="mono" {disabled} {title}
  value={raw} oninput={edit} onkeydown={nudge}
  onfocus={() => (focused = true)} onblur={() => (focused = false)} />
