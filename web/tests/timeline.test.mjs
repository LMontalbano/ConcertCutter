import assert from 'node:assert/strict'
import { test } from 'node:test'

const { audibleAt, crossfadeLane, crossfades, reconcileMontage, reorderAt, titledAt } =
  await import('../src/lib/timeline.ts')

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

test('deux morceaux qui se touchent se chevauchent de la durée du fondu, et la suite suit', () => {
  const audio = [
    { id: 'a', start: 0, end: 60 },
    { id: 'b', start: 60, end: 120 },
    { id: 'c', start: 130, end: 190 },
  ]
  const images = [{ id: 'x', start: 0, end: 60 }, { id: 'y', start: 60, end: 190 }]
  const settled = crossfadeLane(audio, images, 2)
  assert.deepEqual(compact(settled.audio), [
    { id: 'a', start: 0, end: 60 },
    { id: 'b', start: 58, end: 118 },
    { id: 'c', start: 128, end: 188 },
  ])
  // Le changement d'image suit le début du fondu, la fin suit la piste.
  assert.deepEqual(compact(settled.images), [
    { id: 'x', start: 0, end: 58 },
    { id: 'y', start: 58, end: 188 },
  ])
  // Déjà posé, rien ne bouge.
  assert.deepEqual(compact(crossfadeLane(settled.audio, [], 2).audio), compact(settled.audio))
  // Un fondu plus long reprend les mêmes jointures, et zéro les remet bord à bord.
  assert.deepEqual(compact(crossfadeLane(settled.audio, [], 4).audio).map(({ start }) => start), [0, 56, 126])
  assert.deepEqual(compact(crossfadeLane(settled.audio, [], 0).audio).map(({ start }) => start), [0, 60, 130])
})

test('un fondu ne mange jamais plus de la moitié d’un plan', () => {
  const settled = crossfadeLane([{ id: 'a', start: 0, end: 3 }, { id: 'b', start: 3, end: 4 }], [], 2)
  assert.deepEqual(compact(settled.audio), [{ id: 'a', start: 0, end: 3 }, { id: 'b', start: 2.5, end: 3.5 }])
})

test('pendant le fondu, l’un s’éteint pendant que l’autre monte, et le titre passe au milieu', () => {
  const lane = [{ id: 'a', start: 0, end: 10 }, { id: 'b', start: 8, end: 20 }]
  assert.deepEqual(audibleAt(lane, 5).map(({ clip, gain }) => [clip.id, gain]), [['a', 1]])
  const middle = audibleAt(lane, 9)
  assert.deepEqual(middle.map(({ clip }) => clip.id), ['a', 'b'])
  for (const { gain } of middle) assert.ok(Math.abs(gain - Math.SQRT1_2) < 1e-9)
  assert.deepEqual(audibleAt(lane, 12).map(({ clip, gain }) => [clip.id, gain]), [['b', 1]])
  assert.equal(titledAt(lane, 8.9).id, 'a')
  assert.equal(titledAt(lane, 9).id, 'b')
  assert.equal(titledAt(lane, 25), null)
  assert.deepEqual(crossfades(lane), [{ start: 8, end: 10 }])
})

test('un plan pris dans un fondu peut bouger sans empiéter davantage sur ses voisins', () => {
  const lane = [
    { id: 'a', start: 0, end: 10 },
    { id: 'b', start: 8, end: 20 },
    { id: 'c', start: 18, end: 30 },
  ]
  assert.deepEqual(compact(reorderAt(lane, lane[1], 7)).find(({ id }) => id === 'b'),
    { id: 'b', start: 8, end: 20 })
  assert.deepEqual(compact(reorderAt(lane, lane[1], 8.5)).find(({ id }) => id === 'b'),
    { id: 'b', start: 8, end: 20 })
})
