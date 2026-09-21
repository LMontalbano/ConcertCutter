import assert from 'node:assert/strict'
import { test } from 'node:test'

const { reorderAt } = await import('../src/lib/timeline.ts')

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
