import fr from '../../../concertcutter/locales/fr.json' with { type: 'json' }
import en from '../../../concertcutter/locales/en.json' with { type: 'json' }

export type Language = 'fr' | 'en'
export type LanguageChoice = 'auto' | Language
export interface Preferences { language: LanguageChoice; effectiveLanguage: Language }
export interface LocalizedMessage { key: string; params?: Record<string, string | number | LocalizedMessage> }
type Entry = string | { one: string; other: string }
const catalogs: Record<Language, Record<string, Entry>> = { fr, en }
export const locale = $state<Preferences>({ language: 'auto', effectiveLanguage: 'en' })

export function applyLanguage(preferences: Preferences): void {
  locale.language = preferences.language
  locale.effectiveLanguage = preferences.effectiveLanguage
  document.documentElement.lang = preferences.effectiveLanguage
}

export function t(key: string, params: Record<string, string | number | undefined | LocalizedMessage> = {}): string {
  const language = locale.effectiveLanguage
  const entry = catalogs[language][key] ?? catalogs.en[key] ?? key
  const text = typeof entry === 'string' ? entry : entry[
    new Intl.PluralRules(language).select(Number(params.count ?? 0)) === 'one' ? 'one' : 'other'
  ]
  return text.replace(/\{(\w+)\}/g, (_, name: string) => {
    const value = params[name]
    return typeof value === 'object' ? t(value.key, value.params) : String(value ?? '')
  })
}

/** Only explicitly marked server messages are translated; titles and paths are data. */
export function translatePayload<T>(payload: T): T {
  if (Array.isArray(payload)) return payload.map(translatePayload) as T
  if (!payload || typeof payload !== 'object') return payload
  const result = Object.fromEntries(Object.entries(payload).map(([key, value]) => [key, translatePayload(value)]))
  for (const [key, value] of Object.entries(payload)) {
    if (key.endsWith('Messages') && Array.isArray(value)) {
      const original = result[key.slice(0, -8)] as string[]
      result[key.slice(0, -8)] = value.map((message: LocalizedMessage | null, index) =>
        message ? t(message.key, message.params) : original[index])
    }
    if (key.endsWith('Message') && value && typeof value === 'object' && 'key' in value) {
      const message = value as LocalizedMessage
      result[key.slice(0, -7)] = t(message.key, message.params)
    }
  }
  return result as T
}
