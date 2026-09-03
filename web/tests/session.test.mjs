import assert from 'node:assert/strict'
import { beforeEach, test } from 'node:test'

// Seule la lecture du jeton au chargement de l'API demande un document.
globalThis.document = { querySelector: () => null }
const { session } = await import('../src/lib/session.svelte.ts')

beforeEach(() => {
  session.state = {
    duration: 120,
    segments: [[0, 20, 'gap'], [20, 50, 'music'], [50, 70, 'gap'],
               [70, 110, 'music'], [110, 120, 'gap']].map(([start, end, kind], index) =>
      ({ index, start, end, kind })),
  }
  session.loop = null
  session.select(1)
  session.scrub(30)
})

const focus = () => [session.selected, session.viewStart, session.viewSpan]

test('glisser dans les deux marges garde le morceau et ses deux bornes', () => {
  const before = focus()
  for (const time of [60, 10]) {
    session.scrub(time)
    session.tick(time + 1)
    assert.deepEqual(focus(), before)
    assert.equal(session.segment.start, 20)
    assert.equal(session.segment.end, 50)
  }
})

test('le suivi automatique conserve le focus en entrant dans une marge', () => {
  session.seek(49)
  const before = focus()
  session.tick(51)
  assert.deepEqual(focus(), before)
})

test('le suivi change ensemble le segment et le cadrage en quittant la vue', () => {
  session.seek(49)
  session.tick(71)
  assert.equal(session.selected, 3)
  assert.ok(session.viewStart > 5)
  assert.ok(session.viewStart <= 70)
  assert.ok(session.viewStart + session.viewSpan >= 110)
})

test('naviguer vers une marge depuis le transport la sélectionne et la cadre', () => {
  const before = focus()
  session.seek(55)
  assert.equal(session.selected, 2)
  assert.notEqual(session.viewStart, before[1])
  assert.equal(session.segment.start, 50)
  assert.equal(session.segment.end, 70)
})

test('un zoom ne permet pas au suivi de remplacer les poignées par celles du voisin', () => {
  session.seek(49)
  session.zoom(.5, 49)
  const before = focus()
  session.tick(75)
  assert.deepEqual(focus(), before)
})

test('recommencer une boucle voisine préserve le morceau choisi pour édition', () => {
  session.loop = 2
  const before = focus()
  session.scrub(69)
  session.tick(70)
  assert.equal(session.playhead, 50)
  assert.deepEqual(focus(), before)
})
