import { t, locale } from './i18n.svelte'
/* Les horaires, tels qu'ils s'écrivent et se relisent.

   Trois formes, et une seule raison à chacune : `hms` pour situer (11:24),
   `tenths` pour caler une coupe (11:24,3 — le dixième est la précision du
   geste), `clock` pour le transport, qui montre l'heure du concert. */

export function hms(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const rest = total % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return hours ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${pad(minutes)}:${pad(rest)}`
}

export function tenths(seconds: number): string {
  // Arrondi au dixième *avant* de séparer les deux parts. En tronquant, 217,1
  // — qui vaut 217,099999… en virgule flottante — s'affichait « 03:37,0 » :
  // le stepper avait bougé la coupe, et le champ jurait le contraire.
  const dixiemes = Math.round(Math.max(0, seconds) * 10)
  const separator = locale.effectiveLanguage === 'fr' ? ',' : '.'
  return `${hms(Math.floor(dixiemes / 10))}${separator}${dixiemes % 10}`
}

export function duration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  if (total < 60) return `${total} s`
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes} min ${String(total % 60).padStart(2, '0')}`
  return hms(total)
}

/** Relit un horaire saisi à la main. Accepte 12:34, 1:02:14 et 754,5.

    Le pendant de `excerpts.parse_time` côté Python — les steppers écrivent
    dans le même champ que le clavier, et les deux doivent lire pareil. */
export function parseTime(text: string): number | null {
  const cleaned = text.trim().replace(',', '.')
  if (!cleaned) return null
  const parts = cleaned.split(':')
  if (parts.some((part) => !/^\d*\.?\d*$/.test(part) || part === '')) return null
  const numbers = parts.map(Number)
  if (numbers.some(Number.isNaN)) return null
  if (numbers.length === 1) return numbers[0]
  if (numbers.length === 2) return numbers[0] * 60 + numbers[1]
  if (numbers.length === 3) return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
  return null
}

export function trackLabel(number: number | null): string {
  return number ? String(number).padStart(2, '0') : '—'
}

/** « Enregistré à l'instant », et ce qui suit.

    L'horodatage exact ne dit rien d'utile ici : ce qu'on veut savoir, c'est
    si le travail des dix dernières minutes est à l'abri. */
export function savedAgo(stamp: string): string {
  if (!stamp) return ''
  const when = new Date(stamp)
  if (Number.isNaN(when.getTime())) return ''
  const elapsed = (Date.now() - when.getTime()) / 1000
  if (elapsed < 45) return t('ui.saved_just_now')
  if (elapsed < 90) return t('ui.saved_a_minute_ago')
  if (elapsed < 3600) return t('ui.saved_value_minutes_ago', { p0: Math.round(elapsed / 60) })
  if (elapsed < 7200) return t('ui.saved_an_hour_ago')
  if (elapsed < 86400) return t('ui.saved_value_hours_ago', { p0: Math.round(elapsed / 3600) })
  return t('ui.saved_on_value', { p0: when.toLocaleDateString(locale.effectiveLanguage) })
}
