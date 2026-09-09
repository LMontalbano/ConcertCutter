<script lang="ts">
  import { locale, t } from '../lib/i18n.svelte'

  let { id, value = $bindable(), min = 0, max, step = 0.1, disabled = false }:
    { id: string; value: number; min?: number; max: number; step?: number; disabled?: boolean } = $props()
  let input: HTMLInputElement
  let raw = $state('')
  let focused = $state(false)
  let displayedLanguage = $state('')

  function formatted(number: number): string {
    return Number.isFinite(number) ? new Intl.NumberFormat(locale.effectiveLanguage,
      { useGrouping: false, maximumFractionDigits: 10 }).format(number) : ''
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
    const cleaned = raw.trim().replace(',', '.')
    value = /^\d+(?:\.\d*)?$/.test(cleaned) ? Number(cleaned) : NaN
    validate()
  }

  function nudge(event: KeyboardEvent): void {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
    event.preventDefault()
    const current = Number.isFinite(value) ? value : min
    value = Math.min(max, Math.max(min, Number((current + (event.key === 'ArrowUp' ? step : -step)).toFixed(10))))
    raw = formatted(value)
    validate()
  }
</script>

<!-- A native number input follows Chromium's own locale, even when HTML lang changes. -->
<input bind:this={input} {id} type="text" inputmode="decimal" class="mono" {disabled}
  value={raw} oninput={edit} onkeydown={nudge}
  onfocus={() => (focused = true)} onblur={() => (focused = false)} />
