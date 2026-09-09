import assert from 'node:assert/strict'
import { test } from 'node:test'
import { readFileSync, readdirSync } from 'node:fs'

globalThis.document = { documentElement: { lang: '' }, querySelector: () => null }
const { t, applyLanguage, translatePayload, locale } = await import('../src/lib/i18n.svelte.ts')
const { tenths, parseTime, savedAgo } = await import('../src/lib/format.ts')

test('language changes update plurals, dates and decimal times without changing input parsing', () => {
  applyLanguage({ language: 'fr', effectiveLanguage: 'fr' })
  assert.equal(document.documentElement.lang, 'fr')
  assert.equal(t('count.tracks', { count: 1 }), '1 morceau')
  assert.equal(t('count.tracks', { count: 2 }), '2 morceaux')
  assert.equal(tenths(217.1), '03:37,1')
  const stamp = '2020-02-03T12:00:00Z'
  assert.ok(savedAgo(stamp).endsWith(new Date(stamp).toLocaleDateString('fr')))
  applyLanguage({ language: 'en', effectiveLanguage: 'en' })
  assert.equal(locale.language, 'en')
  assert.equal(t('count.tracks', { count: 0 }), '0 tracks')
  assert.equal(t('count.tracks', { count: 1 }), '1 track')
  assert.equal(tenths(217.1), '03:37.1')
  assert.equal(parseTime('754,5'), 754.5)
  assert.equal(parseTime('754.5'), 754.5)
  assert.equal(parseTime('bad'), null)
  assert.ok(savedAgo(stamp).endsWith(new Date(stamp).toLocaleDateString('en')))
})

test('server descriptors translate recursively without changing titles or paths', () => {
  const description = { key: 'server.value_must_be_a_number', params: { p0: { key: 'settings.fades' } } }
  const payload = {
    error: 'Fondus doit être un nombre.', errorMessage: description,
    title: 'Fondus', path: 'C:\\Mes concerts\\Piste 01.wav',
    warnings: ['Fondus doit être un nombre.'], warningsMessages: [description],
    opening: { phase: 'Import en cours…', phaseMessage: { key: 'server.importing' } },
  }
  applyLanguage({ language: 'en', effectiveLanguage: 'en' })
  const english = translatePayload(payload)
  assert.equal(english.error, 'Fades must be a number.')
  assert.equal(english.warnings[0], english.error)
  assert.equal(english.opening.phase, 'Importing…')
  assert.equal(english.title, payload.title)
  assert.equal(english.path, payload.path)
  applyLanguage({ language: 'fr', effectiveLanguage: 'fr' })
  assert.equal(translatePayload(english).error, payload.error)
})

test('every static translation key used by the frontend exists in both catalogs', () => {
  const root = new URL('../src/', import.meta.url)
  const catalogs = ['fr', 'en'].map(language => JSON.parse(readFileSync(
    new URL(`../../concertcutter/locales/${language}.json`, import.meta.url), 'utf8')))
  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const file = new URL(entry.name + (entry.isDirectory() ? '/' : ''), directory)
      if (entry.isDirectory()) walk(file)
      else if (/\.(svelte|ts)$/.test(entry.name)) {
        const source = readFileSync(file, 'utf8')
        for (const [, key] of source.matchAll(/\bt\(['"]([^'"]+)['"]/g)) {
          for (const catalog of catalogs) assert.ok(key in catalog, `${file}: ${key}`)
        }
      }
    }
  }
  walk(root)
})
