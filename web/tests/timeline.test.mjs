import assert from 'node:assert/strict'
import { test } from 'node:test'

const { reconcileMontage, reorderAt } = await import('../src/lib/timeline.ts')

const compact = (lane) => lane.map(({ id, start, end }) => ({ id, start, end }))

test('déplacer le premier clip vers la droite ne décale pas la fin de la piste', () => {
  const lane = [
    { id: 'a', start: 0, end: 2 },
    { id: 'b', start: 2, end: 5 },
    { id: 'c', start: 5, end: 6 },
  ]
  assert.deepEqual(compact(reorderAt(lane, lane[0], 4)), [
    { id: 'b', start: 0, end: 3 },
    { id: 'a', start: 3, end: 5 },
    { id: 'c', start: 5, end: 6 },
  ])
})

test('déplacer le dernier clip vers la gauche est symétrique', () => {
  const lane = [
    { id: 'a', start: 0, end: 2 },
    { id: 'b', start: 2, end: 5 },
    { id: 'c', start: 5, end: 6 },
  ]
  assert.deepEqual(compact(reorderAt(lane, lane[2], 0)), [
    { id: 'c', start: 0, end: 1 },
    { id: 'a', start: 1, end: 3 },
    { id: 'b', start: 3, end: 6 },
  ])
})

test('un déplacement libre dans un espace ne touche pas aux voisins', () => {
  const lane = [
    { id: 'a', start: 0, end: 2 },
    { id: 'b', start: 4, end: 5 },
    { id: 'c', start: 8, end: 10 },
  ]
  assert.deepEqual(compact(reorderAt(lane, lane[1], 5.5)), [
    { id: 'a', start: 0, end: 2 },
    { id: 'b', start: 5.5, end: 6.5 },
    { id: 'c', start: 8, end: 10 },
  ])
})

test('un switch conserve les espaces et ne déplace pas les clips extérieurs', () => {
  const lane = [
    { id: 'a', start: 0, end: 2 },
    { id: 'b', start: 3, end: 5 },
    { id: 'c', start: 7, end: 8 },
    { id: 'd', start: 10, end: 12 },
  ]
  assert.deepEqual(compact(reorderAt(lane, lane[1], 7)), [
    { id: 'a', start: 0, end: 2 },
    { id: 'c', start: 3, end: 4 },
    { id: 'b', start: 6, end: 8 },
    { id: 'd', start: 10, end: 12 },
  ])
})

test('le voisin bouge après le franchissement de son premier quart', () => {
  const lane = [
    { id: 'a', start: 0, end: 2 },
    { id: 'b', start: 2, end: 4 },
  ]
  assert.deepEqual(reorderAt(lane, lane[0], 1.5).map(({ id }) => id), ['a', 'b'])
  assert.deepEqual(reorderAt(lane, lane[0], 1.501).map(({ id }) => id), ['b', 'a'])
  assert.deepEqual(reorderAt(lane, lane[1], 0.5).map(({ id }) => id), ['a', 'b'])
  assert.deepEqual(reorderAt(lane, lane[1], 0.499).map(({ id }) => id), ['b', 'a'])
})

const tracks = [
  { number: 1, start: 10, end: 60 },
  { number: 2, start: 65, end: 125 },
]
const montage = () => [
  { id: 'a', trackNumber: 1, start: 0, end: 50, sourceStart: 10, sourceEnd: 60, trackStart: 10, trackEnd: 60 },
  { id: 'b', trackNumber: 2, start: 50, end: 110, sourceStart: 65, sourceEnd: 125, trackStart: 65, trackEnd: 125 },
]

test('un montage à jour ressort intact', () => {
  const images = [{ id: 'i', start: 0, end: 110 }]
  const found = reconcileMontage(montage(), images, tracks)
  assert.equal(found.adjusted, 0)
  assert.equal(found.removed, 0)
  assert.deepEqual(compact(found.audio), compact(montage()))
  assert.deepEqual(found.images, images)
})

test('une coupe déplacée entraîne les bords de plan qui la suivaient, et la suite du montage', () => {
  const moved = [{ number: 1, start: 10, end: 70 }, { number: 2, start: 72, end: 125 }]
  const images = [{ id: 'x', start: 45, end: 55 }, { id: 'y', start: 50, end: 110 }]
  const found = reconcileMontage(montage(), images, moved)
  assert.equal(found.adjusted, 2)
  assert.deepEqual(found.audio.map(({ id, start, end, sourceStart, sourceEnd }) =>
    ({ id, start, end, sourceStart, sourceEnd })), [
    { id: 'a', start: 0, end: 60, sourceStart: 10, sourceEnd: 70 },
    { id: 'b', start: 60, end: 113, sourceStart: 72, sourceEnd: 125 },
  ])
  assert.deepEqual(compact(found.images), [
    { id: 'x', start: 45, end: 65 },
    { id: 'y', start: 60, end: 113 },
  ])
})

test('après une nouvelle analyse, un plan retrouve son morceau par recouvrement', () => {
  const legacy = [{ id: 'a', trackNumber: 7, start: 0, end: 50, sourceStart: 100, sourceEnd: 150 }]
  const found = reconcileMontage(legacy, [], [{ number: 1, start: 20, end: 90 }, { number: 2, start: 95, end: 200 }])
  assert.equal(found.adjusted, 1)
  assert.equal(found.audio[0].trackNumber, 2)
  assert.deepEqual([found.audio[0].sourceStart, found.audio[0].sourceEnd], [100, 150])
})

test('un plan qui ne tombe plus dans aucun morceau est retiré sans tirer les suivants', () => {
  const found = reconcileMontage(montage(), [], [{ number: 2, start: 65, end: 125 }])
  assert.equal(found.removed, 1)
  assert.deepEqual(compact(found.audio), [{ id: 'b', start: 50, end: 110 }])
})
