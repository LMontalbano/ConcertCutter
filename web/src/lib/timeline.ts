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
    // An item that already overlaps a neighbour (an audio crossfade) may stay
    // where it is, but may not overlap it further.
    const current = ordered[sourceIndex].start
    const floor = Math.min(previous?.end ?? 0, current)
    const ceiling = next ? Math.max(next.start - span, current) : Number.POSITIVE_INFINITY
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

  return { audio: kept, images: follow(images, shifts), adjusted, removed }
}

type Shift = { at: number; delta: number }

/**
 * Move image edges along with the audio they were laid against.
 *
 * An edge moves with every shift that happened at or before it: an image that
 * ended where an audio clip ended keeps ending with it, one that started with
 * the next clip keeps starting with it.
 */
function follow<I extends Positioned>(images: I[], shifts: Shift[]): I[] {
  if (!shifts.length) return images.map((clip) => ({ ...clip }))
  const remap = (time: number) =>
    time + shifts.reduce((sum, shift) => sum + (shift.at <= time + 0.01 ? shift.delta : 0), 0)
  return images.map((clip) => ({ ...clip, start: rounded(Math.max(0, remap(clip.start))),
    end: rounded(Math.max(0, remap(clip.end))) }))
    .filter((clip) => clip.end > clip.start)
}

/** Clips closer than this are joined: it is rounding, not a wanted gap. */
const JOIN_S = 0.02

/**
 * Overlap every pair of joined audio clips by the transition fade.
 *
 * A true crossfade mixes the end of one track with the start of the next, so
 * the second clip has to start before the first one ends. Two clips that
 * touch or overlap are joined; the second one (and everything after it) is
 * moved so that they overlap by exactly `fade`, never more than half of
 * either clip. Clips separated by a gap are left alone. The images follow the
 * audio, so that what is heard and what is shown stay together.
 *
 * Idempotent: a lane that is already settled comes back unchanged.
 */
export function crossfadeLane<A extends Positioned, I extends Positioned>(
  audio: A[], images: I[], fade: number,
): { audio: A[]; images: I[] } {
  const ordered = audio.map((clip) => ({ ...clip })).sort((a, b) => a.start - b.start)
  const original = ordered.map((clip) => clip.start)
  const shifts: Shift[] = []
  for (let index = 1; index < ordered.length; index++) {
    const previous = ordered[index - 1]
    const clip = ordered[index]
    if (clip.start > previous.end + JOIN_S) continue
    const overlap = Math.max(0, Math.min(fade, (previous.end - previous.start) / 2,
      (clip.end - clip.start) / 2))
    const delta = previous.end - overlap - clip.start
    if (Math.abs(delta) < 0.0005) continue
    for (const later of ordered.slice(index)) {
      later.start = rounded(later.start + delta)
      later.end = rounded(later.end + delta)
    }
    shifts.push({ at: original[index], delta })
  }
  return { audio: ordered, images: follow(images, shifts) }
}

/**
 * Which clips are heard at `time`, and how loud.
 *
 * Inside an overlap the outgoing clip fades out while the incoming one fades
 * in, on the constant-power curves the export uses.
 */
export function audibleAt<A extends Positioned>(lane: A[], time: number): { clip: A; gain: number }[] {
  const ordered = [...lane].sort((a, b) => a.start - b.start)
  const heard: { clip: A; gain: number }[] = []
  ordered.forEach((clip, index) => {
    if (time < clip.start || time >= clip.end) return
    const previous = ordered[index - 1]
    const next = ordered[index + 1]
    let gain = 1
    if (previous && previous.end > clip.start && time < previous.end) {
      gain = Math.sin((time - clip.start) / (previous.end - clip.start) * Math.PI / 2)
    } else if (next && next.start < clip.end && time >= next.start) {
      gain = Math.cos((time - next.start) / (clip.end - next.start) * Math.PI / 2)
    }
    heard.push({ clip, gain })
  })
  return heard
}

/** The clip whose title shows at `time`: titles hand over mid-crossfade. */
export function titledAt<A extends Positioned>(lane: A[], time: number): A | null {
  const ordered = [...lane].sort((a, b) => a.start - b.start)
  for (let index = 0; index < ordered.length; index++) {
    const clip = ordered[index]
    const previous = ordered[index - 1]
    const next = ordered[index + 1]
    const start = previous && previous.end > clip.start ? (clip.start + previous.end) / 2 : clip.start
    const end = next && next.start < clip.end ? (clip.end + next.start) / 2 : clip.end
    if (start <= time && time < end) return clip
  }
  return null
}

/** Each crossfade of the lane, for drawing. */
export function crossfades<A extends Positioned>(lane: A[]): { start: number; end: number }[] {
  const ordered = [...lane].sort((a, b) => a.start - b.start)
  return ordered.slice(1).flatMap((clip, index) =>
    ordered[index].end > clip.start + 0.0005 ? [{ start: clip.start, end: ordered[index].end }] : [])
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
