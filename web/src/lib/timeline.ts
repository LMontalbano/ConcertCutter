export type Positioned = { id: string; start: number; end: number }

/**
 * Move an existing timeline item without making the whole lane ripple.
 *
 * Inside its current gap the item moves freely. Once its centre crosses a
 * neighbour's centre, the affected items are reordered inside their original
 * combined span. The switch happens after one quarter of the neighbouring
 * item has been crossed, so the lane reacts before both items fully overlap.
 * Items outside that span never move and the lane does not grow.
 */
export function reorderAt<T extends Positioned>(lane: T[], moving: T, wanted: number): T[] {
  const ordered = lane.map((item) => ({ ...item })).sort((a, b) => a.start - b.start)
  const sourceIndex = ordered.findIndex((item) => item.id === moving.id)
  if (sourceIndex < 0) return ordered

  const span = moving.end - moving.start
  const desiredStart = Math.max(0, wanted)
  const desiredCentre = desiredStart + span / 2
  const others = ordered.filter((item) => item.id !== moving.id)
  let destinationIndex = sourceIndex
  if (desiredStart > moving.start) {
    for (let index = sourceIndex + 1; index < ordered.length; index++) {
      const item = ordered[index]
      const threshold = item.start + (item.end - item.start) / 4
      if (desiredCentre > threshold) destinationIndex = index
      else break
    }
  } else if (desiredStart < moving.start) {
    for (let index = sourceIndex - 1; index >= 0; index--) {
      const item = ordered[index]
      const threshold = item.end - (item.end - item.start) / 4
      if (desiredCentre < threshold) destinationIndex = index
      else break
    }
  }

  if (destinationIndex === sourceIndex) {
    const previous = ordered[sourceIndex - 1]
    const next = ordered[sourceIndex + 1]
    const floor = previous?.end ?? 0
    const ceiling = next ? next.start - span : Number.POSITIVE_INFINITY
    const start = Math.max(floor, Math.min(desiredStart, ceiling))
    const placed = { ...ordered[sourceIndex], start: rounded(start), end: rounded(start + span) }
    return ordered.map((item, index) => index === sourceIndex ? placed : item)
  }

  const reordered = [...others]
  reordered.splice(destinationIndex, 0, { ...ordered[sourceIndex] })
  const first = Math.min(sourceIndex, destinationIndex)
  const last = Math.max(sourceIndex, destinationIndex)

  // Keep the empty spaces that already existed between positions in the
  // affected block. They belong to the timeline, not to a particular clip.
  const gaps = ordered.slice(first, last).map((item, index) =>
    Math.max(0, ordered[first + index + 1].start - item.end))
  let cursor = ordered[first].start
  for (let index = first; index <= last; index++) {
    const item = reordered[index]
    const duration = item.end - item.start
    reordered[index] = { ...item, start: rounded(cursor), end: rounded(cursor + duration) }
    cursor += duration + (gaps[index - first] ?? 0)
  }
  return reordered
}

function rounded(value: number): number {
  return Number(value.toFixed(3))
}
