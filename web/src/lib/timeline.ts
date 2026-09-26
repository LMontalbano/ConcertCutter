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

export type SourceClip = Positioned & {
  trackNumber: number
  sourceStart: number
  sourceEnd: number
  /** Bounds of the track when the clip was cut from it. */
  trackStart?: number
  trackEnd?: number
}

export type TrackSpan = { number: number; start: number; end: number }

/** A source edge within this distance of its track edge follows the track. */
const EDGE_S = 0.05
/** Shortest audio clip the montage accepts, as in the editor. */
const MINIMUM_AUDIO_S = 0.5

/**
 * Realign a montage on the current cuts.
 *
 * An audio clip freezes its track number and source span when it is placed.
 * Moving a boundary, merging tracks or analysing again afterwards used to
 * leave it stale: the export silently used the old cut, or failed on an
 * unknown track. Each clip is matched to the track it overlaps most (the
 * number alone means nothing after a new analysis), an edge that sat on its
 * track edge follows that edge, and the span is clamped inside the track.
 *
 * A clip whose length changes ripples the later clips so that gaps are kept,
 * and image clips are remapped with them. A clip that no longer overlaps any
 * track is dropped; its place stays empty rather than pulling the rest.
 */
export function reconcileMontage<A extends SourceClip, I extends Positioned>(
  audio: A[], images: I[], tracks: TrackSpan[],
): { audio: A[]; images: I[]; adjusted: number; removed: number } {
  const kept: A[] = []
  const shifts: { at: number; delta: number }[] = []
  let offset = 0
  let adjusted = 0
  let removed = 0

  for (const clip of [...audio].sort((a, b) => a.start - b.start)) {
    const track = matchTrack(clip, tracks)
    let sourceStart = clip.sourceStart
    let sourceEnd = clip.sourceEnd
    if (track) {
      if (clip.trackStart !== undefined && Math.abs(sourceStart - clip.trackStart) <= EDGE_S) {
        sourceStart = track.start
      }
      if (clip.trackEnd !== undefined && Math.abs(sourceEnd - clip.trackEnd) <= EDGE_S) {
        sourceEnd = track.end
      }
      sourceStart = Math.max(sourceStart, track.start)
      sourceEnd = Math.min(sourceEnd, track.end)
    }
    if (!track || sourceEnd - sourceStart < MINIMUM_AUDIO_S) {
      removed++
      continue
    }

    const length = sourceEnd - sourceStart
    const delta = length - (clip.end - clip.start)
    if (track.number !== clip.trackNumber || Math.abs(sourceStart - clip.sourceStart) > 0.001
      || Math.abs(sourceEnd - clip.sourceEnd) > 0.001) adjusted++

    const start = clip.start + offset
    kept.push({
      ...clip, trackNumber: track.number,
      sourceStart: rounded(sourceStart), sourceEnd: rounded(sourceEnd),
      trackStart: track.start, trackEnd: track.end,
      start: rounded(start), end: rounded(start + length),
    })
    if (Math.abs(delta) > 0.0005) shifts.push({ at: clip.end, delta })
    offset += delta
  }

  // An image edge moves with every audio clip that ended before it: an image
  // that ended with a clip keeps ending with it, one that started with the
  // next clip keeps starting with it.
  const remap = (time: number) =>
    time + shifts.reduce((sum, shift) => sum + (shift.at <= time + 0.01 ? shift.delta : 0), 0)
  const remapped = shifts.length
    ? images.map((clip) => ({ ...clip, start: rounded(Math.max(0, remap(clip.start))),
      end: rounded(Math.max(0, remap(clip.end))) }))
      .filter((clip) => clip.end > clip.start)
    : images.map((clip) => ({ ...clip }))

  return { audio: kept, images: remapped, adjusted, removed }
}

function matchTrack(clip: SourceClip, tracks: TrackSpan[]): TrackSpan | undefined {
  const overlap = (track: TrackSpan) =>
    Math.min(track.end, clip.sourceEnd) - Math.max(track.start, clip.sourceStart)
  let best: TrackSpan | undefined
  let bestOverlap = 0
  for (const track of tracks) {
    const shared = overlap(track)
    if (shared > bestOverlap
      || (shared > 0 && shared === bestOverlap && track.number === clip.trackNumber)) {
      best = track
      bestOverlap = shared
    }
  }
  return best
}

function rounded(value: number): number {
  return Number(value.toFixed(3))
}
