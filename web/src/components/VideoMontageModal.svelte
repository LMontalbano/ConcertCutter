<script lang="ts">
  import { onMount } from 'svelte'
  import { t } from '../lib/i18n.svelte'
  import {
    api, follow, type TimelineAudioClip, type TimelineClip,
    type VideoMontageConfig, type ExportChoice, type Job, type Track,
  } from '../lib/api'
  import { session, message } from '../lib/session.svelte'
  import { duration as spell, hms, tenths, parseTime, trackLabel } from '../lib/format'
  import { modal } from '../lib/modal'
  import { palette, slice } from '../lib/wave'
  import { reorderAt } from '../lib/timeline'
  import NumberInput from './NumberInput.svelte'
  import ExportConflictModal from './ExportConflictModal.svelte'
  import Hint from './Hint.svelte'

  let { initialConfig, initialDir = '', onClose, onSave, onBusy }: {
    initialConfig: VideoMontageConfig | null
    initialDir?: string
    onClose: () => void
    onSave?: (config: VideoMontageConfig, dir: string) => void
    onBusy?: (job: Job | null) => void
  } = $props()

  const tracks = $derived(session.state?.tracks ?? [])

  function makeId(prefix: string): string {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  }

  function legacyAudioClips(): TimelineAudioClip[] {
    if (initialConfig?.audioClips?.length) return initialConfig.audioClips.map((clip) => ({ ...clip }))
    const wanted = new Set(initialConfig?.selectedTracks ?? [])
    if (!wanted.size) return []
    const trims = initialConfig?.trackTrims ?? {}
    let cursor = 0
    return tracks.flatMap((track) => {
      if (!wanted.has(track.number)) return []
      const trim = trims[track.number] ?? { trimStart: 0, trimEnd: 0 }
      const sourceStart = Math.min(track.end - 0.5, track.start + Math.max(0, trim.trimStart))
      const sourceEnd = Math.max(sourceStart + 0.5, track.end - Math.max(0, trim.trimEnd))
      const start = cursor
      cursor += sourceEnd - sourceStart
      return [{ id: makeId(`audio-${track.number}`), trackNumber: track.number,
        start, end: cursor, sourceStart, sourceEnd }]
    })
  }

  let audioClips = $state<TimelineAudioClip[]>(legacyAudioClips())
  // svelte-ignore state_referenced_locally
  let clips = $state<TimelineClip[]>(initialConfig?.clips?.map((clip) => ({ ...clip })) ?? [])
  // svelte-ignore state_referenced_locally
  let library = $state<string[]>([...(initialConfig?.library ?? [])])
  // svelte-ignore state_referenced_locally
  let titleOverlay = $state(initialConfig?.titleOverlay ?? true)
  // svelte-ignore state_referenced_locally
  let titlePosition = $state<'bottom' | 'top' | 'center'>(initialConfig?.titlePosition ?? 'bottom')
  // svelte-ignore state_referenced_locally
  let transitionFade = $state(initialConfig?.transitionFade ?? 2)
  // svelte-ignore state_referenced_locally
  let dir = $state(initialDir)
  let blocked = $state(session.state?.video ?? null)
  let installing = $state<Job | null>(null)
  let refused = $state('')
  let conflict = $state<{ target: string; proposed: string; overwritten: number; leftovers: number } | null>(null)

  let playhead = $state(0)
  let playing = $state(false)
  let zoomLevel = $state(1)
  let containerWidth = $state(900)
  let timelineContainer = $state<HTMLElement | null>(null)
  let previewCanvas = $state<HTMLCanvasElement | null>(null)
  let audioEl: HTMLAudioElement | null = null
  let selected = $state<{ kind: 'image' | 'audio'; id: string } | null>(null)
  let activeSnapTime = $state<number | null>(null)
  let dragOverLane = $state<'image' | 'audio' | null>(null)
  let draggedSource = $state<{ kind: 'image'; image: string } | { kind: 'audio'; trackNumber: number } | null>(null)
  let playheadDragging = $state(false)

  type MontageSnapshot = {
    audioClips: TimelineAudioClip[]
    clips: TimelineClip[]
    library: string[]
    titleOverlay: boolean
    titlePosition: 'bottom' | 'top' | 'center'
    transitionFade: number
    selected: { kind: 'image' | 'audio'; id: string } | null
  }
  let undoStack = $state<MontageSnapshot[]>([])
  let redoStack = $state<MontageSnapshot[]>([])
  let fadeBefore = $state<MontageSnapshot | null>(null)

  function snapshot(): MontageSnapshot {
    return {
      audioClips: audioClips.map((clip) => ({ ...clip })),
      clips: clips.map((clip) => ({ ...clip })),
      library: [...library],
      titleOverlay,
      titlePosition,
      transitionFade,
      selected: selected ? { ...selected } : null,
    }
  }

  function restore(state: MontageSnapshot): void {
    audioClips = state.audioClips.map((clip) => ({ ...clip }))
    clips = state.clips.map((clip) => ({ ...clip }))
    library = [...state.library]
    titleOverlay = state.titleOverlay
    titlePosition = state.titlePosition
    transitionFade = state.transitionFade
    selected = state.selected ? { ...state.selected } : null
    seekTo(Math.min(playhead, Math.max(0, ...audioClips.map((clip) => clip.end))))
  }

  function recordChange(before: MontageSnapshot): void {
    if (JSON.stringify(before) === JSON.stringify(snapshot())) return
    undoStack = [...undoStack.slice(-79), before]
    redoStack = []
  }

  function undo(): void {
    const previous = undoStack.at(-1)
    if (!previous) return
    const current = snapshot()
    undoStack = undoStack.slice(0, -1)
    redoStack = [...redoStack, current]
    restore(previous)
  }

  function redo(): void {
    const next = redoStack.at(-1)
    if (!next) return
    const current = snapshot()
    redoStack = redoStack.slice(0, -1)
    undoStack = [...undoStack, current]
    restore(next)
  }

  const selectedTrackNumbers = $derived(new Set(audioClips.map((clip) => clip.trackNumber)))
  const timelineDuration = $derived(audioClips.reduce((largest, clip) => Math.max(largest, clip.end), 0))
  const contentDuration = $derived(Math.max(timelineDuration,
    clips.reduce((largest, clip) => Math.max(largest, clip.end), 0)))
  function initialTimelineDuration(): number {
    return Math.max(30,
      audioClips.reduce((largest, clip) => Math.max(largest, clip.end), 0),
      clips.reduce((largest, clip) => Math.max(largest, clip.end), 0))
  }
  let fittedDuration = $state(initialTimelineDuration())
  const scaleDuration = $derived(Math.max(30, fittedDuration))
  const rulerDuration = $derived(Math.max(scaleDuration, contentDuration))
  const minimumZoom = $derived(Math.min(1, scaleDuration / rulerDuration))
  const activeAudioClip = $derived(audioClips.find((clip) => clip.start <= playhead && playhead < clip.end) ?? null)
  const activeTrack = $derived(activeAudioClip
    ? tracks.find((track) => track.number === activeAudioClip.trackNumber) ?? null : null)
  const activeClip = $derived(clips.find((clip) => clip.start <= playhead && playhead < clip.end) ?? null)
  /* Les quatre conditions, montrées ensemble.

     Elles étaient évaluées en cascade, et n'en affichaient qu'une : on posait
     la piste audio pour découvrir qu'il manquait une image, puis un dossier,
     puis ffmpeg. Quatre allers-retours pour une seule liste. */
  const blockers = $derived([
    { done: audioClips.length > 0, text: t('montage.audio_timeline_empty') },
    { done: clips.length > 0, text: t('montage.empty_timeline') },
    { done: Boolean(dir), text: t('ui.choose_a_destination') },
    { done: !blocked, text: t('ui.video_requires_ffmpeg_a_tool_supplied_separately_from') },
  ])
  const missing = $derived(blockers.some((step) => !step.done))
  const pps = $derived((containerWidth / scaleDuration) * zoomLevel)
  const timelineWidth = $derived(Math.max(containerWidth, rulerDuration * pps))

  const imageCache = new Map<string, HTMLImageElement>()
  function getImage(src: string): HTMLImageElement | null {
    const url = api.imageUrl(src)
    let image = imageCache.get(url)
    if (!image) {
      image = new Image()
      image.src = url
      image.onload = drawPreview
      imageCache.set(url, image)
    }
    return image.complete ? image : null
  }

  function drawPreview(): void {
    if (!previewCanvas) return
    const context = previewCanvas.getContext('2d')
    if (!context) return
    const width = previewCanvas.width
    const height = previewCanvas.height
    context.fillStyle = '#080b10'
    context.fillRect(0, 0, width, height)

    /* L'image entière, centrée sur du noir — rien d'autre.

       L'aperçu posait derrière l'image une copie d'elle-même agrandie et
       floutée, qui remplissait les côtés. Joli, mais faux : `_framed` dans
       `video.py` fait `force_original_aspect_ratio=decrease` puis `pad` en
       noir. Le MP4 a donc des bandes noires, et l'aperçu montrait une image
       qui débordait du cadre. On ne peut pas se projeter sur un aperçu qui
       ne dit pas où l'image s'arrête. */
    function fitted(path: string) {
      const image = getImage(path)
      if (!image?.naturalWidth || !image.naturalHeight) return
      const imageRatio = image.naturalWidth / image.naturalHeight
      const frameRatio = width / height
      const drawnWidth = imageRatio > frameRatio ? width : height * imageRatio
      const drawnHeight = imageRatio > frameRatio ? width / imageRatio : height
      return { image, x: (width - drawnWidth) / 2, y: (height - drawnHeight) / 2,
        width: drawnWidth, height: drawnHeight }
    }

    function paintStill(path: string, alpha = 1): void {
      const paintContext = context!
      const frame = fitted(path)
      if (!frame) return
      paintContext.save()
      paintContext.globalAlpha = alpha
      paintContext.drawImage(frame.image, frame.x, frame.y, frame.width, frame.height)
      paintContext.restore()
    }

    function paintIncomingMatte(path: string, alpha: number): void {
      const frame = fitted(path)
      if (!frame) return
      context!.save()
      context!.globalAlpha = alpha
      context!.fillStyle = '#000'
      context!.fillRect(0, 0, width, frame.y)
      context!.fillRect(0, frame.y, frame.x, frame.height)
      context!.fillRect(frame.x + frame.width, frame.y,
        width - frame.x - frame.width, frame.height)
      context!.fillRect(0, frame.y + frame.height, width,
        height - frame.y - frame.height)
      context!.restore()
    }

    if (activeClip) {
      const ordered = [...clips].sort((a, b) => a.start - b.start)
      const index = ordered.findIndex((clip) => clip.id === activeClip.id)
      const previous = index > 0 ? ordered[index - 1] : null
      const fade = Math.min(transitionFade, activeClip.end - activeClip.start,
        previous ? previous.end - previous.start : 0)
      const joinsPrevious = previous && Math.abs(previous.end - activeClip.start) < 0.02
      const progress = fade > 0 ? (playhead - activeClip.start) / fade : 1
      if (joinsPrevious && progress < 1) {
        paintStill(previous.image)
        /* Même calcul que le fondu historique de l'export : l'image entrante
           et son cadre noir gagnent ensemble en opacité. Le centre mélange
           donc les deux images tandis que les futures bandes passent
           progressivement de l'ancienne image au noir. */
        paintIncomingMatte(activeClip.image, Math.max(0, progress))
        paintStill(activeClip.image, Math.max(0, progress))
      } else {
        paintStill(activeClip.image)
      }
    }
    if (titleOverlay && activeTrack) {
      const label = activeTrack.title ? `${trackLabel(activeTrack.number)}. ${activeTrack.title}`
        : t('ui.track_value_116', { p0: trackLabel(activeTrack.number) })
      const fontSize = Math.round(height * 0.045)
      context.save()
      context.font = `600 ${fontSize}px "Instrument Sans", "Segoe UI", sans-serif`
      const boxWidth = context.measureText(label).width + fontSize * 1.4
      const boxHeight = fontSize * 1.7
      const x = (width - boxWidth) / 2
      let y = height - boxHeight - height * 0.08
      if (titlePosition === 'top') y = height * 0.08
      if (titlePosition === 'center') y = (height - boxHeight) / 2
      context.fillStyle = 'rgba(0, 0, 0, 0.68)'
      context.beginPath()
      context.roundRect(x, y, boxWidth, boxHeight, 8)
      context.fill()
      context.fillStyle = '#fff'
      context.textAlign = 'center'
      context.textBaseline = 'middle'
      context.fillText(label, width / 2, y + boxHeight / 2)
      context.restore()
    }
  }

  $effect(() => {
    void playhead; void activeClip; void activeTrack; void titleOverlay; void titlePosition; void transitionFade
    drawPreview()
  })

  function trackFor(number: number): Track | undefined {
    return tracks.find((track) => track.number === number)
  }

  function snapTargets(excluded?: { kind: 'image' | 'audio'; id: string }): number[] {
    const targets = [0, playhead, timelineDuration]
    for (const clip of clips) if (excluded?.kind !== 'image' || excluded.id !== clip.id) targets.push(clip.start, clip.end)
    for (const clip of audioClips) if (excluded?.kind !== 'audio' || excluded.id !== clip.id) targets.push(clip.start, clip.end)
    return [...new Set(targets.filter((value) => Number.isFinite(value) && value >= 0))]
  }

  function snapEdge(value: number, excluded?: { kind: 'image' | 'audio'; id: string }) {
    const limit = 14 / Math.max(1, pps)
    let best = value
    let distance = limit + Number.EPSILON
    let target: number | null = null
    for (const candidate of snapTargets(excluded)) {
      const delta = Math.abs(candidate - value)
      if (delta <= limit && delta < distance) { best = candidate; distance = delta; target = candidate }
    }
    return { value: best, target, distance }
  }

  function snapPlacement(start: number, end: number, excluded: { kind: 'image' | 'audio'; id: string }) {
    const duration = end - start
    const left = snapEdge(start, excluded)
    const right = snapEdge(end, excluded)
    if (left.target !== null && (right.target === null || left.distance <= right.distance)) {
      activeSnapTime = left.target
      return { start: left.value, end: left.value + duration }
    }
    if (right.target !== null) {
      activeSnapTime = right.target
      return { start: Math.max(0, right.value - duration), end: right.value }
    }
    activeSnapTime = null
    return { start, end }
  }

  /** Pose un clip à l'instant voulu en repoussant vers la droite ce qui gêne.

      On lâche où l'on veut, et la piste fait de la place. Le décalage est en
      chaîne : un clip repoussé pousse à son tour le suivant s'il le rattrape,
      et s'arrête dès qu'un espace suffit. */
  function insertAt<T extends { id: string; start: number; end: number }>(
    lane: T[], moving: T, wanted: number): T[] {
    const span = moving.end - moving.start
    const start = Math.max(0, wanted)
    const placed = { ...moving, start: Number(start.toFixed(3)),
      end: Number((start + span).toFixed(3)) }
    const kept: T[] = []
    let cursor = placed.end
    for (const clip of lane.filter((item) => item.id !== moving.id)
      .sort((a, b) => a.start - b.start)) {
      if (clip.end <= start + 0.01) { kept.push(clip); continue }
      if (clip.start >= cursor - 0.01) { kept.push(clip); cursor = Math.max(cursor, clip.end); continue }
      const shifted = { ...clip, start: Number(cursor.toFixed(3)),
        end: Number((cursor + clip.end - clip.start).toFixed(3)) }
      kept.push(shifted)
      cursor = shifted.end
    }
    return [...kept, placed].sort((a, b) => a.start - b.start)
  }

  function clampImagesToAudio(): void {
    if (!timelineDuration) return
    clips = clips.map((clip) => ({ ...clip, end: Math.min(clip.end, timelineDuration) }))
      .filter((clip) => clip.end - clip.start >= 0.25 && clip.start < timelineDuration)
  }

  /* Sans instant précisé, on ajoute à la suite.

     Le « + » d'une source et le glisser-déposer ne demandent pas la même
     chose : lâcher désigne un endroit, cliquer « + » veut dire « et celui-ci
     ensuite ». Ajouté à la tête de lecture, trois clics d'affilée posaient
     chaque élément au même endroit et repoussaient les précédents — la liste
     sortait à l'envers. */
  function laneEnd(lane: { end: number }[]): number {
    return lane.reduce((largest, clip) => Math.max(largest, clip.end), 0)
  }

  function addTrack(track: Track, targetTime = laneEnd(audioClips)): void {
    const before = snapshot()
    const duration = Math.max(0.5, track.end - track.start)
    if (!audioClips.length) targetTime = 0
    const clip: TimelineAudioClip = { id: makeId(`audio-${track.number}`), trackNumber: track.number,
      start: 0, end: duration, sourceStart: track.start, sourceEnd: track.end }
    const wanted = snapPlacement(Math.max(0, targetTime), Math.max(0, targetTime) + duration,
      { kind: 'audio', id: clip.id }).start
    audioClips = insertAt([...audioClips, clip], clip, wanted)
    const posed = audioClips.find((item) => item.id === clip.id)!
    if (audioClips.length === 1) { fittedDuration = Math.max(30, posed.end); zoomLevel = 1 }
    selected = { kind: 'audio', id: clip.id }
    activeSnapTime = null
    seekTo(posed.start)
    recordChange(before)
  }

  function addAllTracks(): void {
    const before = snapshot()
    const wasEmpty = !audioClips.length
    let cursor = audioClips.reduce((largest, clip) => Math.max(largest, clip.end), 0)
    const additions: TimelineAudioClip[] = []
    for (const track of tracks) {
      if (selectedTrackNumbers.has(track.number)) continue
      const duration = Math.max(0.5, track.end - track.start)
      additions.push({ id: makeId(`audio-${track.number}`), trackNumber: track.number,
        start: cursor, end: cursor + duration, sourceStart: track.start, sourceEnd: track.end })
      cursor += duration
    }
    audioClips = [...audioClips, ...additions]
    if (wasEmpty && additions.length) { fittedDuration = Math.max(30, cursor); zoomLevel = 1 }
    if (additions.length) selected = { kind: 'audio', id: additions[0].id }
    recordChange(before)
  }

  async function addImages(): Promise<void> {
    const before = snapshot()
    const found = await api.pick('images')
    if (found.paths?.length) library = [...new Set([...library, ...found.paths])]
    recordChange(before)
  }

  function addImage(image: string, targetTime = laneEnd(clips)): void {
    const before = snapshot()
    const duration = Math.min(12, Math.max(2, timelineDuration || 12))
    const clip: TimelineClip = { id: makeId('image'), image, start: 0, end: duration }
    const wanted = snapPlacement(Math.max(0, targetTime), Math.max(0, targetTime) + duration,
      { kind: 'image', id: clip.id }).start
    clips = insertAt([...clips, clip], clip, wanted)
    clampImagesToAudio()
    const posed = clips.find((item) => item.id === clip.id)
    if (!posed) return
    selected = { kind: 'image', id: clip.id }
    activeSnapTime = null
    seekTo(posed.start)
    recordChange(before)
  }

  function removeLibraryImage(index: number): void {
    const before = snapshot()
    library = library.filter((_, current) => current !== index)
    recordChange(before)
  }

  function startSourceDrag(event: DragEvent,
    source: { kind: 'image'; image: string } | { kind: 'audio'; trackNumber: number }): void {
    draggedSource = source
    if (!event.dataTransfer) return
    event.dataTransfer.effectAllowed = 'copy'
    const mime = source.kind === 'image' ? 'application/cc-image' : 'application/cc-audio'
    event.dataTransfer.setData(mime, source.kind === 'image' ? source.image : String(source.trackNumber))
  }

  function clearSourceDrag(): void { draggedSource = null; dragOverLane = null }
  function dragLane(event: DragEvent, lane: 'image' | 'audio'): void {
    event.preventDefault(); event.stopPropagation()
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
    dragOverLane = lane
  }
  function timeAtPointer(event: DragEvent | MouseEvent | PointerEvent): number {
    const rect = timelineContainer?.getBoundingClientRect()
    return Math.max(0, (event.clientX - (rect?.left ?? 0) + (timelineContainer?.scrollLeft ?? 0)) / pps)
  }
  function dropSource(event: DragEvent, lane: 'image' | 'audio'): void {
    event.preventDefault(); event.stopPropagation()
    const at = timeAtPointer(event)
    if (lane === 'image') {
      const image = draggedSource?.kind === 'image' ? draggedSource.image
        : event.dataTransfer?.getData('application/cc-image') ?? ''
      if (image) { if (!library.includes(image)) library = [...library, image]; addImage(image, at) }
    } else {
      const number = draggedSource?.kind === 'audio' ? draggedSource.trackNumber
        : Number(event.dataTransfer?.getData('application/cc-audio'))
      const track = trackFor(number)
      if (track) addTrack(track, at)
    }
    clearSourceDrag()
  }

  type DragState = { kind: 'image' | 'audio'; id: string; action: 'move' | 'start' | 'end';
    pointerX: number; start: number; end: number; sourceStart?: number; sourceEnd?: number
    visualOffset: number
    /* La piste telle qu'elle était au premier appui. Le décalage se recalcule
       à partir d'elle à chaque mouvement : appliqué à la piste courante, il
       se serait ajouté à lui-même et les voisins auraient fui vers la
       droite tant qu'on tenait le bouton. */
    laneLayout?: (TimelineClip | TimelineAudioClip)[]
    historyBefore: MontageSnapshot }
  let dragging = $state<DragState | null>(null)

  /* Le pointeur, pas la souris.

     Le transport du concert travaille déjà ainsi (`setPointerCapture`) : un
     écran tactile ou un stylet y déplacent la lecture, alors qu'ici tout le
     montage restait à la souris seule. Le même geste, la même API. */
  function beginDrag(kind: 'image' | 'audio', item: TimelineClip | TimelineAudioClip,
    action: 'move' | 'start' | 'end', event: PointerEvent): void {
    event.preventDefault(); event.stopPropagation()
    selected = { kind, id: item.id }
    dragging = { kind, id: item.id, action, pointerX: event.clientX, start: item.start, end: item.end,
      visualOffset: 0,
      historyBefore: snapshot(),
      laneLayout: action === 'move'
        ? (kind === 'audio' ? audioClips : clips).map((clip) => ({ ...clip }))
        : undefined,
      ...('sourceStart' in item ? { sourceStart: item.sourceStart, sourceEnd: item.sourceEnd } : {}) }
    window.addEventListener('pointermove', moveDrag)
    window.addEventListener('pointerup', endDrag)
    window.addEventListener('pointercancel', endDrag)
  }

  function moveDrag(event: PointerEvent): void {
    if (!dragging) return
    const delta = (event.clientX - dragging.pointerX) / pps
    const minimum = dragging.kind === 'audio' ? 0.5 : 0.25
    const lane = dragging.kind === 'audio' ? audioClips : clips
    const index = lane.findIndex((clip) => clip.id === dragging!.id)
    if (index < 0) return
    let start = dragging.start
    let end = dragging.end
    if (dragging.action === 'move') {
      const duration = dragging.end - dragging.start
      const desiredStart = Math.max(0, dragging.start + delta)
      const snapped = snapPlacement(desiredStart, desiredStart + duration,
        { kind: dragging.kind, id: dragging.id })
      const layout = dragging.laneLayout ?? lane
      const moving = layout.find((clip) => clip.id === dragging!.id)
      if (!moving) return
      const posed = reorderAt(layout, moving, snapped.start)
      const placed = posed.find((clip) => clip.id === dragging!.id)
      dragging.visualOffset = placed ? snapped.start - placed.start : 0
      if (dragging.kind === 'image') clips = posed as TimelineClip[]
      else audioClips = posed as TimelineAudioClip[]
      return
    } else {
      const edge = snapEdge(Math.max(0, (dragging.action === 'start' ? dragging.start : dragging.end) + delta),
        { kind: dragging.kind, id: dragging.id })
      activeSnapTime = edge.target
      if (dragging.action === 'start') start = Math.min(end - minimum, edge.value)
      else end = Math.max(start + minimum, edge.value)
      const others = lane.filter((clip) => clip.id !== dragging!.id)
      if (dragging.action === 'start') {
        const previousEnd = others.filter((clip) => clip.end <= dragging!.end)
          .reduce((largest, clip) => Math.max(largest, clip.end), 0)
        start = Math.max(previousEnd, start)
      } else {
        const nextStart = others.filter((clip) => clip.start >= dragging!.start)
          .reduce((smallest, clip) => Math.min(smallest, clip.start), Number.POSITIVE_INFINITY)
        end = Math.min(end, nextStart)
        if (dragging.kind === 'image' && timelineDuration) end = Math.min(end, timelineDuration)
      }
      if (dragging.kind === 'audio') {
        const audioClip = audioClips.find((clip) => clip.id === dragging!.id)
        if (!audioClip) return
        const track = trackFor(audioClip.trackNumber)
        if (track && dragging.action === 'start') {
          start = Math.max(start, dragging.start - ((dragging.sourceStart ?? track.start) - track.start))
        }
        if (track && dragging.action === 'end') {
          end = Math.min(end, dragging.end + (track.end - (dragging.sourceEnd ?? track.end)))
        }
      }
    }
    if (dragging.kind === 'image') {
      const updated = { ...clips[index], start: Number(start.toFixed(3)), end: Number(end.toFixed(3)) }
      clips = clips.map((clip) => clip.id === updated.id ? updated : clip)
    } else {
      const currentClip = audioClips.find((clip) => clip.id === dragging!.id)
      if (!currentClip) return
      const sourceStart = dragging.sourceStart ?? 0
      const sourceEnd = dragging.sourceEnd ?? sourceStart + (dragging.end - dragging.start)
      const updated: TimelineAudioClip = { ...currentClip, start: Number(start.toFixed(3)),
        end: Number(end.toFixed(3)),
        sourceStart: Number((dragging.action === 'start' ? sourceStart + start - dragging.start : sourceStart).toFixed(3)),
        sourceEnd: Number((dragging.action === 'end' ? sourceEnd + end - dragging.end : sourceEnd).toFixed(3)) }
      audioClips = audioClips.map((clip) => clip.id === updated.id ? updated : clip)
    }
  }

  function endDrag(): void {
    const before = dragging?.historyBefore
    dragging = null; activeSnapTime = null
    audioClips = [...audioClips].sort((a, b) => a.start - b.start)
    clips = [...clips].sort((a, b) => a.start - b.start)
    clampImagesToAudio()
    window.removeEventListener('pointermove', moveDrag)
    window.removeEventListener('pointerup', endDrag)
    window.removeEventListener('pointercancel', endDrag)
    if (before) recordChange(before)
  }

  /** Le clip désigné par la sélection, ou rien. */
  const selectedClip = $derived(!selected ? null
    : (selected.kind === 'image' ? clips : audioClips)
        .find((clip) => clip.id === selected!.id) ?? null)

  /** Déplace un bord du clip sélectionné à un instant saisi au clavier.

      Les bornes sont celles du glissement, à la lettre : durée minimale, pas
      d'empiètement sur le voisin, et pour l'audio, l'impossibilité de
      redemander à l'enregistrement plus qu'il ne contient. Un champ qui
      accepterait ce que la souris refuse serait une deuxième vérité. */
  function retime(edge: 'start' | 'end', wanted: number): void {
    const clip = selectedClip
    if (!clip || !selected || !Number.isFinite(wanted)) return
    const kind = selected.kind
    const others = (kind === 'audio' ? audioClips : clips)
      .filter((other) => other.id !== clip.id)
    const minimum = kind === 'audio' ? 0.5 : 0.25
    const track = 'trackNumber' in clip ? trackFor(clip.trackNumber) : undefined
    let { start, end } = clip

    if (edge === 'start') {
      const floor = others.filter((other) => other.end <= clip.end)
        .reduce((largest, other) => Math.max(largest, other.end), 0)
      start = Math.max(floor, Math.min(end - minimum, Math.max(0, wanted)))
      if (track && 'sourceStart' in clip) {
        start = Math.max(start, clip.start - (clip.sourceStart - track.start))
      }
    } else {
      const ceiling = others.filter((other) => other.start >= clip.start)
        .reduce((smallest, other) => Math.min(smallest, other.start), Number.POSITIVE_INFINITY)
      end = Math.min(ceiling, Math.max(start + minimum, wanted))
      if (kind === 'image' && timelineDuration) end = Math.min(end, timelineDuration)
      if (track && 'sourceEnd' in clip) {
        end = Math.min(end, clip.end + (track.end - clip.sourceEnd))
      }
    }
    if (start === clip.start && end === clip.end) return

    const before = snapshot()
    const moved = { ...clip, start: Number(start.toFixed(3)), end: Number(end.toFixed(3)),
      ...('sourceStart' in clip ? {
        sourceStart: Number((edge === 'start'
          ? clip.sourceStart + start - clip.start : clip.sourceStart).toFixed(3)),
        sourceEnd: Number((edge === 'end'
          ? clip.sourceEnd + end - clip.end : clip.sourceEnd).toFixed(3)),
      } : {}) }
    if (kind === 'image') {
      clips = clips.map((item) => item.id === moved.id ? moved as TimelineClip : item)
        .sort((a, b) => a.start - b.start)
    } else {
      audioClips = audioClips.map((item) => item.id === moved.id ? moved as TimelineAudioClip : item)
        .sort((a, b) => a.start - b.start)
      clampImagesToAudio()
    }
    recordChange(before)
  }

  /** La durée saisie se lit comme une fin déplacée : un seul chemin, une
      seule série de bornes, et l'annulation ne voit qu'un geste. */
  function resize(wanted: number): void {
    if (selectedClip) retime('end', selectedClip.start + wanted)
  }

  /** Décale le clip sélectionné, sans lui faire chevaucher ses voisins. */
  function nudgeClip(delta: number): void {
    const clip = selectedClip
    if (!clip || !selected) return
    const wanted = Math.max(0, clip.start + delta)
    if (Math.abs(wanted - clip.start) < 0.001) return
    const before = snapshot()
    if (selected.kind === 'image') {
      clips = reorderAt(clips, clip as TimelineClip, wanted)
      clampImagesToAudio()
    } else {
      audioClips = reorderAt(audioClips, clip as TimelineAudioClip, wanted)
    }
    recordChange(before)
  }

  /** Le montage au clavier : flèches pour déplacer, Alt pour rogner la fin.

      Sans cela, poser un plan tenait entièrement de la souris — les clips
      n'étaient même pas atteignables à la tabulation. Le dixième sous Maj,
      comme partout ailleurs dans l'application. */
  function clipKeydown(event: KeyboardEvent, kind: 'image' | 'audio',
    clip: TimelineClip | TimelineAudioClip): void {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault(); event.stopPropagation()
    selected = { kind, id: clip.id }
    const delta = (event.key === 'ArrowRight' ? 1 : -1) * (event.shiftKey ? 0.1 : 1)
    if (event.altKey) retime('end', clip.end + delta)
    else nudgeClip(delta)
  }

  function removeSelected(): void {
    if (!selected) return
    const before = snapshot()
    if (selected.kind === 'image') clips = clips.filter((clip) => clip.id !== selected!.id)
    else { audioClips = audioClips.filter((clip) => clip.id !== selected!.id); setTimeout(clampImagesToAudio) }
    selected = null
    recordChange(before)
  }

  /* Le tracé d'un clip, repeint quand le thème ou l'enveloppe changent.

     Le thème et l'enveloppe passent par le paramètre de l'action, comme pour
     les vignettes de la liste des morceaux : c'est ce qui déclenche `update`.
     Sans eux, le tracé gardait les couleurs du thème d'ouverture, et un clip
     posé avant l'arrivée de l'enveloppe restait vide. */
  type WaveArgs = { clip: TimelineAudioClip; theme: string; envelope: Float32Array }

  function renderWaveform(canvas: HTMLCanvasElement, args: WaveArgs) {
    let current = args
    function draw(): void {
      if (!current.envelope.length) return
      const ratio = window.devicePixelRatio || 1
      const width = Math.max(8, Math.round(canvas.clientWidth)); const height = Math.max(8, Math.round(canvas.clientHeight))
      canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio)
      const context = canvas.getContext('2d'); if (!context) return
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      const heights = slice(current.envelope, session.envelopeFps, current.clip.sourceStart,
        current.clip.sourceEnd - current.clip.sourceStart, width)
      const middle = height / 2
      const colours = palette()
      context.fillStyle = colours.wave; context.beginPath(); context.moveTo(0, middle)
      heights.forEach((value, index) => context.lineTo(index, middle - value * middle * 0.82))
      for (let index = heights.length - 1; index >= 0; index--) context.lineTo(index, middle + heights[index] * middle * 0.82)
      context.closePath(); context.fill()
    }
    const observer = new ResizeObserver(draw); observer.observe(canvas); draw()
    return { update(next: WaveArgs) { current = next; draw() }, destroy() { observer.disconnect() } }
  }

  let animationFrame = 0
  let lastFrameAt = 0
  let syncedAudioId = ''
  function syncAudio(): void {
    if (!audioEl) return
    const clip = audioClips.find((candidate) => candidate.start <= playhead && playhead < candidate.end)
    if (!clip) { audioEl.pause(); syncedAudioId = ''; return }
    // Tant que les métadonnées ne sont pas arrivées, écrire `currentTime` ne
    // retient rien et `play()` est refusé : c'est ce qui faisait perdre le
    // tout premier appui sur Lecture, qu'il fallait redonner. On demande la
    // lecture quand même, et la boucle d'animation repasse ici à chaque
    // image — elle posera la position dès que l'enregistrement est prêt.
    if (audioEl.readyState >= 1) {
      const wanted = clip.sourceStart + playhead - clip.start
      if (syncedAudioId !== clip.id || Math.abs(audioEl.currentTime - wanted) > 0.22) {
        audioEl.currentTime = wanted; syncedAudioId = clip.id
      }
    } else {
      syncedAudioId = ''
    }
    // Un refus passager — une position réécrite pendant que `play()` démarre
    // — ne doit pas arrêter la lecture : la boucle réessaie à l'image suivante.
    if (playing && audioEl.paused) void audioEl.play().catch(() => undefined)
  }
  function playbackFrame(now: number): void {
    if (!playing) return
    if (!lastFrameAt) lastFrameAt = now
    playhead = Math.min(timelineDuration, playhead + (now - lastFrameAt) / 1000); lastFrameAt = now; syncAudio()
    if (playhead >= timelineDuration) { stopPlayback(false); return }
    animationFrame = requestAnimationFrame(playbackFrame)
  }
  function startPlayback(): void {
    if (!audioClips.length) return
    if (playhead >= timelineDuration) playhead = 0
    playing = true; lastFrameAt = performance.now(); syncAudio(); cancelAnimationFrame(animationFrame)
    animationFrame = requestAnimationFrame(playbackFrame)
  }
  function stopPlayback(keepPosition = true): void {
    playing = false; audioEl?.pause(); cancelAnimationFrame(animationFrame); animationFrame = 0; lastFrameAt = 0
    if (!keepPosition) playhead = timelineDuration
  }
  function togglePlay(): void { if (playing) stopPlayback(); else startPlayback() }
  function seekTo(value: number): void {
    playhead = Math.max(0, Math.min(timelineDuration || rulerDuration, value)); syncedAudioId = ''; syncAudio()
    if (playing) lastFrameAt = performance.now()
  }
  function beginPlayheadDrag(event: PointerEvent): void {
    event.preventDefault(); event.stopPropagation()
    playheadDragging = true
    seekTo(timeAtPointer(event))
    window.addEventListener('pointermove', movePlayhead)
    window.addEventListener('pointerup', endPlayheadDrag)
    window.addEventListener('pointercancel', endPlayheadDrag)
  }
  function movePlayhead(event: PointerEvent): void {
    if (playheadDragging) seekTo(timeAtPointer(event))
  }
  function endPlayheadDrag(): void {
    playheadDragging = false
    window.removeEventListener('pointermove', movePlayhead)
    window.removeEventListener('pointerup', endPlayheadDrag)
    window.removeEventListener('pointercancel', endPlayheadDrag)
  }
  function playheadKeydown(event: KeyboardEvent): void {
    if (event.key === 'Home') { event.preventDefault(); seekTo(0); return }
    if (event.key === 'End') { event.preventDefault(); seekTo(timelineDuration); return }
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    // Maj pour le dixième : c'est la précision du geste de coupe ailleurs
    // dans l'application, et la seconde est trop grosse pour caler un fondu.
    const step = event.shiftKey ? 0.1 : 1
    seekTo(playhead + (event.key === 'ArrowRight' ? step : -step))
  }
  /* La barre de lecture, reprise telle quelle du transport du concert.

     Un `<input type=range>` restylé n'avait ni la même hauteur, ni le même
     bouton, ni le grossissement au survol : côte à côte, les deux écrans
     n'avaient pas la même barre. Celle-ci est la même — même balisage, même
     capture du pointeur, même `share`. */
  let scrubBar: HTMLDivElement | null = $state(null)
  let scrubbing = $state(false)
  const share = $derived(timelineDuration ? Math.min(1, playhead / timelineDuration) : 0)

  function seekFromPointer(clientX: number): void {
    if (!scrubBar || !timelineDuration) return
    const box = scrubBar.getBoundingClientRect()
    seekTo(Math.max(0, Math.min(1, (clientX - box.left) / box.width)) * timelineDuration)
  }
  function beginScrub(event: PointerEvent): void {
    if (!audioClips.length) return
    scrubbing = true
    scrubBar?.setPointerCapture(event.pointerId)
    seekFromPointer(event.clientX)
  }
  function moveScrub(event: PointerEvent): void {
    if (scrubbing) seekFromPointer(event.clientX)
  }
  function endScrub(event: PointerEvent): void {
    scrubbing = false
    scrubBar?.releasePointerCapture(event.pointerId)
  }
  function fitTimeline(): void {
    fittedDuration = Math.max(30, contentDuration)
    zoomLevel = 1
    if (timelineContainer) timelineContainer.scrollLeft = 0
  }
  /* Un clic sur la timeline déplace la lecture — y compris sur un clip.

     Les clips avaient été rendus sourds au clic pour que sélectionner ne
     déplace pas la lecture. Mais une fois la piste remplie, les clips *sont*
     la timeline : il ne restait plus rien à cliquer, et la tête de lecture
     devenait inatteignable à la souris. Sélectionner et écouter sont ici le
     même geste. */
  function onTimelineClick(event: MouseEvent): void { seekTo(timeAtPointer(event)) }
  function onTimelineWheel(event: WheelEvent): void {
    // La molette agrandit autour du curseur, comme la carte d'édition de
    // l'écran principal (`session.zoom` y est appelé de la même façon). Le
    // déplacement latéral reste à la barre sous la timeline.
    event.preventDefault()
    if (dragging || !timelineContainer) return
    const rect = timelineContainer.getBoundingClientRect()
    const pointerX = event.clientX - rect.left
    const focus = (pointerX + timelineContainer.scrollLeft) / pps
    const nextZoom = Math.max(minimumZoom, Math.min(12,
      zoomLevel * (event.deltaY > 0 ? 0.8 : 1.25)))
    const nextPps = (containerWidth / scaleDuration) * nextZoom
    zoomLevel = nextZoom
    timelineContainer.scrollLeft = Math.max(0, focus * nextPps - pointerX)
  }
  function onKeyDown(event: KeyboardEvent): void {
    const target = event.target as HTMLElement | null
    // Deux gardes, et non une seule : taper efface un raccourci, alors qu'un
    // bouton ne retient que l'Espace, qui est son geste d'activation. Les
    // confondre rendait Suppr. inopérant dès qu'un clip avait le focus.
    const typing = target?.matches('input, select, textarea')
    const activating = typing || target?.matches('button, [role="button"]')
    const modifier = event.ctrlKey || event.metaKey
    if (modifier && !typing && event.key.toLowerCase() === 'z') {
      event.preventDefault()
      if (event.shiftKey) redo(); else undo()
    } else if (modifier && !typing && event.key.toLowerCase() === 'y') {
      event.preventDefault(); redo()
    } else if (event.key === ' ' && !activating) { event.preventDefault(); togglePlay() }
    else if ((event.key === 'Delete' || event.key === 'Backspace') && selected && !typing) {
      event.preventDefault(); removeSelected()
    }
  }

  function changeTitleOverlay(event: Event): void {
    const before = snapshot()
    titleOverlay = (event.currentTarget as HTMLInputElement).checked
    recordChange(before)
  }
  function changeTitlePosition(position: typeof titlePosition): void {
    const before = snapshot()
    titlePosition = position
    recordChange(before)
  }
  function beginFadeEdit(): void { fadeBefore ??= snapshot() }
  function endFadeEdit(): void {
    if (fadeBefore) recordChange(fadeBefore)
    fadeBefore = null
  }

  async function chooseDir(): Promise<void> {
    const found = await api.pick('dir', { start: dir }); if (found.path) dir = found.path
  }
  async function installFfmpeg(): Promise<void> {
    try {
      const done = await follow(await api.installFfmpeg(), (tick) => (installing = tick))
      blocked = (done.result as { blocked: string | null })?.blocked ?? null
    } catch (failure) { refused = message(failure) } finally { installing = null }
  }
  function currentConfig(): VideoMontageConfig {
    const selectedTracks = [...new Set(audioClips.map((clip) => clip.trackNumber))]
    return { enabled: Boolean(audioClips.length && clips.length), clips, audioClips, library,
      selectedTracks, titleOverlay, titlePosition, transitionFade, full: true, tracks: false }
  }
  function payload(): ExportChoice {
    const config = currentConfig()
    return { dir, image: library[0] ?? '', images: library, crossfade: 0, video_crossfade: 0,
      slide_fade: transitionFade, one_per_track: false, selection: config.selectedTracks ?? [],
      full: false, tracks: false, video_full: true, video_tracks: false, video_montage: config }
  }

  /** Ferme en mettant le montage à l'abri.

      Le serveur ne retient un export qu'au moment où il le lance : tant qu'on
      n'a pas exporté, ce placement n'existe nulle part ailleurs. Toutes les
      sorties passent donc par ici — la croix, Échap et « Fermer ». */
  function dismiss(): void {
    onSave?.(currentConfig(), dir)
    onClose()
  }

  async function start(target?: string, replace = false): Promise<void> {
    refused = ''; if (missing && !target) return
    const body = payload()
    let job: Job
    try {
      if (!target) {
        const plan = await api.planExport(body)
        if (plan.conflict) {
          conflict = { target: plan.target, proposed: plan.proposed ?? plan.target,
            overwritten: plan.overwritten ?? 0, leftovers: plan.leftovers ?? 0 }; return
        }
        target = plan.target
      }
      conflict = null
      job = await api.render({ ...body, target, replace })
    } catch (failure) {
      // Tant que le travail n'est pas parti, la fenêtre reste : le refus se
      // lit là où l'on vient d'agir, et le montage ne quitte pas l'écran.
      conflict = null; refused = message(failure); return
    }
    dismiss()
    if (!onBusy) return
    try {
      const done = await follow(job, (tick) => onBusy(tick)); onBusy(null)
      if (done.state === 'cancelled') { session.note(t('ui.export_stopped_the_previous_export_was_preserved')); return }
      const written = (done.result as { dir?: string })?.dir ?? target
      session.note(t('ui.export_complete_value', { p0: written })); await session.refresh()
    } catch (failure) {
      // Ici la fenêtre est partie, et `refused` n'a plus personne pour
      // l'afficher : l'échec doit remonter à l'application, sinon un export
      // raté ne se voit nulle part.
      onBusy(null); session.problem = message(failure)
    }
  }

  onMount(() => {
    const observer = new ResizeObserver((entries) => { containerWidth = entries[0]?.contentRect.width ?? containerWidth })
    if (timelineContainer) observer.observe(timelineContainer)
    return () => {
      observer.disconnect(); stopPlayback()
      for (const [name, handler] of [
        ['pointermove', moveDrag], ['pointerup', endDrag], ['pointercancel', endDrag],
        ['pointermove', movePlayhead], ['pointerup', endPlayheadDrag],
        ['pointercancel', endPlayheadDrag],
      ] as const) window.removeEventListener(name, handler as EventListener)
    }
  })
</script>

<svelte:window onkeydown={onKeyDown} />
<audio bind:this={audioEl} preload="metadata"
  src={session.open ? api.audioUrl() : undefined}></audio>

<div class="veil" role="presentation">
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="montage-title"
    tabindex="-1" use:modal={{ onClose: dismiss, autofocus: '.play' }}>

    <header class="modal-header">
      <div class="heading">
        <h1 id="montage-title">{t('montage.title')}</h1>
        <p class="meta">
          <span class="badge accent mono">{spell(timelineDuration)}</span>
          <span class="badge">{audioClips.length} {t('montage.audio_clips')}</span>
          <span class="badge">{t('count.images', { count: clips.length })}</span>
        </p>
      </div>
      <button class="btn quiet icon" onclick={dismiss} aria-label={t('ui.close')}>&#x2715;</button>
    </header>

    <div class="workspace">
      <aside class="sources">
        <section class="source-panel">
          <div class="panel-heading">
            <div>
              <h2><span class="step">1</span>{t('montage.track_sources')}</h2>
              <small>{t('montage.sources_hint')}</small>
            </div>
            <button class="btn tonal small" onclick={addAllTracks}>{t('montage.add_all')}</button>
          </div>
          <div class="track-list" role="list">
            {#each tracks as track (track.number)}
              <div class="track-source" class:used={selectedTrackNumbers.has(track.number)}
                draggable="true" role="listitem" title={t('montage.drag_track_hint')}
                ondragstart={(event) => startSourceDrag(event, { kind: 'audio', trackNumber: track.number })}
                ondragend={clearSourceDrag}>
                <span class="drag-grip" aria-hidden="true">&#x22EE;&#x22EE;</span>
                <span class="track-number mono">{trackLabel(track.number)}</span>
                <span class="source-name">{track.title || t('ui.untitled')}</span>
                <span class="source-duration mono">{spell(track.end - track.start)}</span>
                <button class="source-add" aria-label={t('montage.add_to_timeline')}
                  onclick={(event) => { event.stopPropagation(); addTrack(track) }}>+</button>
              </div>
            {/each}
          </div>
        </section>

        <section class="source-panel">
          <div class="panel-heading">
            <div>
              <h2><span class="step">2</span>{t('montage.image_sources')}</h2>
              <small>{t('montage.images_hint')}</small>
            </div>
            <button class="btn tonal small" onclick={addImages}>+ {t('montage.add_images')}</button>
          </div>
          <div class="image-grid" role="list">
            {#each library as image, index (image)}
              <div class="image-tile" draggable="true" role="listitem"
                ondragstart={(event) => startSourceDrag(event, { kind: 'image', image })}
                ondragend={clearSourceDrag}>
                <div class="image-thumbnail">
                  <img src={api.imageUrl(image)} alt={image.split(/[\\/]/).pop()} draggable="false" />
                </div>
                <span title={image}>{image.split(/[\\/]/).pop()}</span>
                <button class="remove-source" onclick={() => removeLibraryImage(index)}
                  aria-label={t('ui.remove_this_image')} title={t('ui.remove_this_image')}>&#x00D7;</button>
              </div>
            {:else}
              <button class="empty-library" onclick={addImages}>+ {t('montage.add_images')}</button>
            {/each}
          </div>
        </section>
      </aside>

      <section class="viewer">
        <div class="canvas-wrap">
          <canvas bind:this={previewCanvas} width="1280" height="720"></canvas>
          <span class="viewer-time mono">{hms(playhead)} / {hms(timelineDuration)}</span>
        </div>

        <div class="viewer-bar">
          <div class="transport">
            <button class="transport-side" onclick={() => seekTo(0)} disabled={!audioClips.length}
              title={t('montage.rewind')} aria-label={t('montage.rewind')}
            ><i class="to-start" aria-hidden="true"></i>&#x25C0;</button>
            <button class="play" class:playing onclick={togglePlay} disabled={!audioClips.length}
              title={playing ? t('montage.pause') : t('montage.play')}
              aria-label={playing ? t('montage.pause') : t('montage.play')}
            ><span class="play-glyph">{playing ? '❚❚' : '▶'}</span></button>

            <div class="time-display mono">
              <span class="now">{hms(playhead)}</span>
              <span class="sep">/</span>
              <span class="total">{hms(timelineDuration)}</span>
            </div>

            <div class="bar-wrapper" bind:this={scrubBar}
              onpointerdown={beginScrub} onpointermove={moveScrub} onpointerup={endScrub}
              onkeydown={playheadKeydown}
              role="slider" tabindex="0" aria-label={t('montage.playhead')}
              aria-valuemin="0" aria-valuemax={timelineDuration}
              aria-valuenow={playhead} aria-valuetext={hms(playhead)}>
              <div class="bar-track">
                <div class="bar-fill" style="width:{share * 100}%"></div>
                <div class="knob" style="left:{share * 100}%"></div>
              </div>
            </div>
          </div>
        </div>

        {#if blocked}
          <div class="ffmpeg-warning">
            <span>{t('ui.video_requires_ffmpeg_a_tool_supplied_separately_from')}</span>
            {#if installing}
              <span class="mono">{installing.phase}</span>
            {:else}
              <button class="btn small" onclick={installFfmpeg}>{t('ui.install_ffmpeg_110_mb')}</button>
            {/if}
          </div>
        {/if}
      </section>
    </div>

    <section class="timeline-section">
      <header class="timeline-toolbar" role="toolbar" aria-label={t('montage.timeline')}>
        <div class="tool-group" role="group" aria-label={t('history.undo')}>
          <button class="btn quiet small glyph" disabled={!undoStack.length} onclick={undo}
            title={t('ui.undo_ctrl_z')} aria-label={t('history.undo')}>&#x21B6;</button>
          <button class="btn quiet small glyph" disabled={!redoStack.length} onclick={redo}
            title={t('ui.redo_ctrl_y')} aria-label={t('history.redo')}>&#x21B7;</button>
        </div>

        <div class="tool-group" role="group" aria-label={t('montage.zoom')}>
          <span class="label">{t('montage.zoom')}</span>
          <button class="btn quiet small glyph" title={t('montage.zoom_out')} aria-label={t('montage.zoom_out')}
            onclick={() => (zoomLevel = Math.max(minimumZoom, zoomLevel / 1.35))}>&#x2212;</button>
          <button class="btn quiet small glyph" title={t('montage.zoom_in')} aria-label={t('montage.zoom_in')}
            onclick={() => (zoomLevel = Math.min(12, zoomLevel * 1.35))}>+</button>
          <button class="btn tonal small" onclick={fitTimeline}>{t('montage.fit')}</button>
        </div>

        <div class="tool-group clip-inspector">
          <label for="clip-start">{t('montage.clip_start')}</label>
          <NumberInput id="clip-start" min={0} max={Math.max(1, contentDuration)} step={0.1}
            parse={parseTime} format={tenths} disabled={!selectedClip}
            title={t('montage.time_hint')}
            value={selectedClip?.start ?? 0} onchange={(at: number) => retime('start', at)} />
          <label for="clip-end">{t('montage.clip_end')}</label>
          <NumberInput id="clip-end" min={0} max={Math.max(1, contentDuration)} step={0.1}
            parse={parseTime} format={tenths} disabled={!selectedClip}
            title={t('montage.time_hint')}
            value={selectedClip?.end ?? 0} onchange={(at: number) => retime('end', at)} />
          <label for="clip-length">{t('montage.clip_duration')}</label>
          <NumberInput id="clip-length" min={0.25} max={Math.max(1, contentDuration)} step={0.1}
            disabled={!selectedClip}
            value={selectedClip ? Number((selectedClip.end - selectedClip.start).toFixed(2)) : 0}
            onchange={(length: number) => resize(length)} />
          <span class="unit">s</span>
        </div>

        <div class="tool-group clip-actions" role="group" aria-label={t('ui.remove')}>
          <button class="btn small danger" onclick={removeSelected} disabled={!selectedClip}
          >{t('ui.remove')}</button>
        </div>

        <div class="tool-group settings">
          <label class="switch-label">
            <input type="checkbox" checked={titleOverlay} onchange={changeTitleOverlay} />
            <b>{t('montage.overlay_title')}</b>
          </label>
          <Hint text={t('montage.overlay_hint')} />
          <div class="segmented" role="group" aria-label={t('montage.title_position')}>
            {#each ['bottom', 'top', 'center'] as position}
              <button class:active={titlePosition === position} disabled={!titleOverlay}
                aria-pressed={titlePosition === position}
                onclick={() => changeTitlePosition(position as typeof titlePosition)}
              >{t(`montage.position_${position}`)}</button>
            {/each}
          </div>
        </div>

        <div class="tool-group">
          <label for="fade-input"><b>{t('montage.transition_fade')}</b></label>
          <Hint text={t('montage.fade_hint')} />
          <span class="number-wrap" onfocusin={beginFadeEdit} onfocusout={endFadeEdit}>
            <NumberInput id="fade-input" min={0} max={10} step={0.25} bind:value={transitionFade} />
            <span>s</span>
          </span>
        </div>
      </header>

      <div class="timeline-frame">
        <div class="timeline-scroll" bind:this={timelineContainer} role="presentation"
          onclick={onTimelineClick} onwheel={onTimelineWheel}>
          <div class="timeline-canvas" class:reordering={dragging?.action === 'move'}
            style="width: {timelineWidth}px;">

            <div class="lane image-lane" class:drop-target={dragOverLane === 'image'} role="presentation"
              ondragenter={(event) => dragLane(event, 'image')}
              ondragover={(event) => dragLane(event, 'image')}
              ondragleave={() => (dragOverLane = null)}
              ondrop={(event) => dropSource(event, 'image')}>
              <span class="lane-label">&#x25A3; {t('montage.images_lane')}</span>
              {#if !clips.length}<span class="lane-help">{t('montage.drop_images_here')}</span>{/if}
              {#each clips as clip (clip.id)}
                <div class="image-clip" class:selected={selected?.kind === 'image' && selected.id === clip.id}
                  class:dragging={dragging?.kind === 'image' && dragging.id === clip.id}
                  style="left: {clip.start * pps}px; width: {Math.max(8, (clip.end - clip.start) * pps)}px;
                    --drag-offset: {(dragging?.kind === 'image' && dragging.id === clip.id
                      ? dragging.visualOffset * pps : 0)}px"
                  role="button" tabindex="0"
                  aria-label="{clip.image.split(/[\/]/).pop()} — {hms(clip.start)}"
                  onfocus={() => (selected = { kind: 'image', id: clip.id })}
                  onkeydown={(event) => clipKeydown(event, 'image', clip)}
                  onpointerdown={(event) => beginDrag('image', clip, 'move', event)}>
                  <button class="handle left" aria-label={t('montage.trim_start')}
                    onpointerdown={(event) => beginDrag('image', clip, 'start', event)}></button>
                  <img class="clip-thumbnail" src={api.imageUrl(clip.image)} alt="" draggable="false" />
                  <span>{clip.image.split(/[\\/]/).pop()}</span>
                  <small class="mono">{spell(clip.end - clip.start)}</small>
                  <button class="handle right" aria-label={t('montage.trim_end')}
                    onpointerdown={(event) => beginDrag('image', clip, 'end', event)}></button>
                </div>
              {/each}
            </div>

            <div class="lane audio-lane" class:drop-target={dragOverLane === 'audio'} role="presentation"
              ondragenter={(event) => dragLane(event, 'audio')}
              ondragover={(event) => dragLane(event, 'audio')}
              ondragleave={() => (dragOverLane = null)}
              ondrop={(event) => dropSource(event, 'audio')}>
              <span class="lane-label">&#x266B; {t('montage.audio_lane')}</span>
              {#if !audioClips.length}<span class="lane-help">{t('montage.drop_tracks_here')}</span>{/if}
              {#each audioClips as clip (clip.id)}
                {@const track = trackFor(clip.trackNumber)}
                <div class="audio-clip" class:selected={selected?.kind === 'audio' && selected.id === clip.id}
                  class:dragging={dragging?.kind === 'audio' && dragging.id === clip.id}
                  style="left: {clip.start * pps}px; width: {Math.max(8, (clip.end - clip.start) * pps)}px;
                    --drag-offset: {(dragging?.kind === 'audio' && dragging.id === clip.id
                      ? dragging.visualOffset * pps : 0)}px"
                  role="button" tabindex="0"
                  aria-label="{trackLabel(clip.trackNumber)} {track?.title || t('ui.untitled')} — {hms(clip.start)}"
                  onfocus={() => (selected = { kind: 'audio', id: clip.id })}
                  onkeydown={(event) => clipKeydown(event, 'audio', clip)}
                  onpointerdown={(event) => beginDrag('audio', clip, 'move', event)}>
                  <button class="handle left" aria-label={t('montage.trim_start')}
                    onpointerdown={(event) => beginDrag('audio', clip, 'start', event)}></button>
                  <canvas use:renderWaveform={{ clip, theme: session.theme,
                    envelope: session.envelope }}></canvas>
                  <span class="audio-name">
                    <b class="mono">{trackLabel(clip.trackNumber)}</b>
                    <span>{track?.title || t('ui.untitled')}</span>
                  </span>
                  <small class="mono">{spell(clip.end - clip.start)}</small>
                  <button class="handle right" aria-label={t('montage.trim_end')}
                    onpointerdown={(event) => beginDrag('audio', clip, 'end', event)}></button>
                </div>
              {/each}
            </div>

            {#if activeSnapTime !== null}
              <span class="snap-line" style="left: {activeSnapTime * pps}px"></span>
            {/if}
            <span class="playhead" class:dragging={playheadDragging}
              style="left: {playhead * pps}px"
              onpointerdown={beginPlayheadDrag} onclick={(event) => event.stopPropagation()}
              onkeydown={playheadKeydown}
              role="slider" tabindex="0" aria-label={t('montage.playhead')}
              aria-valuemin="0" aria-valuemax={timelineDuration}
              aria-valuenow={playhead} aria-valuetext={hms(playhead)}><i></i></span>
          </div>
        </div>
      </div>
    </section>

    <footer class="modal-footer">
      <label class="destination" for="montage-dir-input">
        <span>
          <b><span class="step">3</span>{t('montage.choose_destination')}</b>
          <small>{t('montage.destination_hint')}</small>
        </span>
        <input id="montage-dir-input" class="mono" bind:value={dir}
          placeholder={t('ui.no_folder_selected')} />
        {#if session.dialogs}
          <button class="btn tonal" onclick={chooseDir}>{t('ui.browse')}</button>
        {/if}
      </label>

      <div class="footer-actions">
        {#if refused}
          <span class="refuse">{refused}</span>
        {:else if missing}
          <ul class="still-left" aria-label={t('montage.still_left')}>
            {#each blockers.filter((step) => !step.done) as step}
              <li>{step.text}</li>
            {/each}
          </ul>
        {:else}
          <span class="ready">&#x2713; {t('montage.ready')}</span>
        {/if}
        <button class="btn quiet" onclick={dismiss}>{t('ui.close')}</button>
        <button class="btn strong" disabled={missing} onclick={() => start()}
        >{t('montage.export_video')}</button>
      </div>
    </footer>
  </div>

  {#if conflict}
    <ExportConflictModal {conflict}
      onBeside={() => start(conflict!.proposed, false)}
      onReplace={() => start(conflict!.target, true)}
      onCancel={() => (conflict = null)} />
  {/if}
</div>

<style>
  /* Trois bandes, et une seule qui défile.

     De haut en bas : les sources et l'aperçu, la timeline, la destination.
     Les deux premières partagent la hauteur restante ; la timeline garde un
     plancher pour qu'un clip reste saisissable, et le pied de page ne se
     laisse jamais couper — c'est lui qui porte le bouton d'export. */

  .veil {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: grid;
    place-items: center;
    padding: 16px;
    background: var(--veil);
    backdrop-filter: blur(5px);
  }

  .modal {
    width: min(1600px, 98vw);
    height: 96vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    color: var(--ink);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-float);
  }

  /* -- en-tête ------------------------------------------------------------ */

  .modal-header {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    padding: 14px 24px;
    background: var(--surface-raised);
    border-bottom: 1px solid var(--border);
  }

  .modal-header h1 {
    margin: 0;
    font: 600 18px var(--sans);
  }

  .meta {
    display: flex;
    align-items: center;
    gap: 7px;
    margin: 5px 0 0;
  }

  .modal-header .icon {
    width: 34px;
    padding: 0;
    font-size: 15px;
  }

  /* La pastille numérotée de l'export audio : les deux fenêtres s'ouvrent du
     même bouton, et posent leurs questions dans le même ordre. */
  .step {
    width: 19px;
    height: 19px;
    flex: none;
    display: inline-grid;
    place-items: center;
    margin-right: 7px;
    color: var(--on-accent);
    background: var(--accent);
    border-radius: var(--radius-pill);
    font: 700 11px var(--sans);
  }

  /* -- sources et aperçu --------------------------------------------------- */

  .workspace {
    flex: 1;
    min-height: 240px;
    display: grid;
    grid-template-columns: 340px minmax(0, 1fr);
    gap: 14px;
    padding: 14px 24px 12px;
    overflow: hidden;
  }

  .sources {
    min-height: 0;
    display: grid;
    grid-template-rows: minmax(120px, 0.9fr) minmax(130px, 1.1fr);
    gap: 10px;
  }

  .source-panel {
    min-height: 0;
    display: flex;
    flex-direction: column;
    padding: 12px;
    overflow: hidden;
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .panel-heading {
    display: flex;
    align-items: start;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 9px;
  }

  .panel-heading h2 {
    display: flex;
    align-items: center;
    margin: 0;
    font: 600 13px var(--sans);
  }

  .panel-heading small,
  .destination small {
    display: block;
    margin-top: 3px;
    color: var(--ink-3);
    font: 400 11px var(--sans);
  }

  /* Le petit format des barres d'outils, aligné sur `.btn` en plus compact. */
  .small {
    height: 26px;
    padding: 0 9px;
    font-size: 11.5px;
  }

  .track-list {
    min-height: 0;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }

  .track-source {
    min-height: 34px;
    display: grid;
    grid-template-columns: 14px 25px 1fr auto 26px;
    align-items: center;
    gap: 7px;
    padding: 3px 6px;
    color: var(--ink-2);
    background: var(--surface);
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: grab;
    user-select: none;
  }

  .track-source:hover {
    border-color: var(--accent);
  }

  .track-source.used {
    color: var(--ink);
    background: var(--accent-soft);
  }

  .track-source.used .source-name {
    font-weight: 600;
  }

  .track-source.used .track-number,
  .track-source.used .source-duration {
    color: var(--ink-2);
  }

  .drag-grip {
    color: var(--ink-3);
    letter-spacing: -3px;
  }

  .track-number,
  .source-duration {
    color: var(--ink-3);
    font-size: 11px;
  }

  .source-name {
    overflow: hidden;
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Vingt-six pixels et non vingt-deux : en dessous, la cible devient plus
     petite que le doigt ou que la main qui tremble un peu. */
  .source-add {
    width: 26px;
    height: 26px;
    padding: 0;
    color: var(--accent);
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }

  .source-add:hover {
    color: var(--on-accent);
    background: var(--accent);
    border-color: var(--accent);
  }

  .image-grid {
    min-height: 0;
    overflow: auto;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    grid-auto-rows: max-content;
    gap: 8px;
    align-content: start;
  }

  .image-tile {
    position: relative;
    min-width: 0;
    overflow: hidden;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    cursor: grab;
  }

  .image-tile:hover {
    border-color: var(--accent);
  }

  .image-thumbnail {
    width: 100%;
    height: 72px;
    display: grid;
    place-items: center;
  }

  .image-thumbnail img {
    display: block;
    width: auto;
    height: auto;
    max-width: 100%;
    max-height: 72px;
    object-fit: contain;
    pointer-events: none;
  }

  .image-tile > span {
    display: block;
    padding: 4px 6px;
    overflow: hidden;
    color: var(--ink-2);
    font-size: 10.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .remove-source {
    position: absolute;
    top: 4px;
    right: 4px;
    width: 20px;
    height: 20px;
    padding: 0;
    color: var(--ink-2);
    background: var(--glass);
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    font-size: 14px;
    line-height: 1;
    opacity: 0.5;
    transition: opacity 0.12s ease;
  }

  .image-tile:hover .remove-source,
  .remove-source:focus-visible {
    opacity: 1;
  }

  .remove-source:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }

  .empty-library {
    grid-column: 1 / -1;
    min-height: 72px;
    color: var(--ink-3);
    background: transparent;
    border: 1px dashed var(--border);
    border-radius: var(--radius-sm);
  }

  .viewer {
    min-width: 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  /* L'aperçu est centré, jamais étiré : il sert à juger un cadrage, et une
     image déformée ne dit rien du fichier qui sortira. */
  .canvas-wrap {
    position: relative;
    min-height: 0;
    flex: 1;
    display: grid;
    place-items: center;
    overflow: hidden;
    background: var(--app);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  /* `object-fit`, et non `max-height: 100%`.

     Ni `max-height: 100%` ni `height: 100%` ne bornaient le canvas : le
     conteneur tire sa hauteur d'un `flex: 1`, que le navigateur tient pour
     indéfinie au moment de résoudre le pourcentage de l'enfant. Le canvas
     gardait donc sa hauteur propre — 654 px dans 374 — et `overflow: hidden`
     lui coupait le haut et le bas. L'image était bien peinte entière dans le
     canvas ; c'est le canvas qu'on ne voyait pas en entier.

     Hors flux, `inset: 0` se mesure sur la boîte réelle du conteneur et non
     sur un pourcentage à résoudre : le canvas épouse le cadre, et `contain`
     y loge l'image sans jamais la rogner.

     Le noir est celui du MP4 lui-même, pas une surface de l'interface : les
     bandes que ffmpeg écrit autour de l'image ne changent pas avec le thème. */
  .canvas-wrap canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    display: block;
    object-fit: contain;
    background: #000;
  }

  .viewer-time {
    position: absolute;
    right: 10px;
    bottom: 9px;
    padding: 3px 8px;
    color: var(--ink);
    background: var(--glass);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 11.5px;
  }

  /* -- transport et réglages de rendu -------------------------------------- */

  /* Les deux rangées sous l'aperçu ne parlent que de lui : ce qu'on entend,
     et ce qui sera incrusté. Les outils de la timeline sont descendus contre
     la timeline — chacun près de ce qu'il manipule. */
  .viewer-bar {
    flex: none;
    display: flex;
    align-items: center;
    gap: 14px;
    padding: 8px 14px;
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .viewer-bar {
    min-height: 56px;
    justify-content: space-between;
  }

  .transport {
    min-width: 0;
    flex: 1;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .transport-side {
    height: 32px;
    min-width: 38px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 3px;
    padding: 0 9px;
    color: var(--ink);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-size: 10px;
  }

  /* Le trait du « retour au début », dessiné plutôt que pris à une police :
     les glyphes de transport composés ne sont pas dans Instrument Sans, et
     Windows les remplaçait par un pictogramme en couleur. */
  .to-start {
    width: 2px;
    height: 10px;
    background: currentColor;
  }

  .transport-side:hover:not(:disabled) {
    background: var(--hover);
    color: var(--ink);
  }

  /* Le même bouton que le transport du concert : encre au repos, accent au
     survol. Deux lectures dans une application, c'est un bouton. */
  .play {
    width: 40px;
    height: 40px;
    flex: none;
    display: grid;
    place-items: center;
    padding: 0 0 0 2px;
    color: var(--on-ink);
    background: var(--ink);
    border: 0;
    border-radius: var(--radius-pill);
    box-shadow: var(--shadow);
    transition: background 0.12s ease, color 0.12s ease, transform 0.12s ease;
  }

  .play:hover:not(:disabled) {
    color: var(--on-accent);
    background: var(--accent);
    transform: scale(1.06);
  }

  .play-glyph {
    line-height: 1;
    font-size: 13px;
  }

  .play.playing {
    padding-left: 0;
  }

  .time-display {
    flex: none;
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 140px;
    font-size: 14px;
    font-weight: 600;
  }

  .now {
    color: var(--ink);
  }

  .sep {
    color: var(--ink-3);
    opacity: 0.5;
  }

  .total {
    color: var(--ink-3);
    font-weight: 500;
  }

  .bar-wrapper {
    position: relative;
    flex: 1;
    min-width: 120px;
    height: 32px;
    display: flex;
    align-items: center;
    cursor: pointer;
    touch-action: none;
  }

  .bar-track {
    position: relative;
    width: 100%;
    height: 6px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    transition: height 0.1s ease;
  }

  .bar-wrapper:hover .bar-track {
    height: 8px;
    border-radius: 4px;
  }

  .bar-fill {
    position: absolute;
    inset: 0 auto 0 0;
    background: var(--accent);
    border-radius: 3px;
    box-shadow: 0 0 8px var(--accent-soft);
  }

  .knob {
    position: absolute;
    top: 50%;
    width: 14px;
    height: 14px;
    margin-left: -7px;
    background: var(--ink);
    border: 2px solid var(--surface);
    border-radius: 7px;
    box-shadow: var(--shadow);
    transform: translateY(-50%) scale(0.85);
    transition: transform 0.1s ease, background 0.1s ease;
  }

  .bar-wrapper:hover .knob {
    transform: translateY(-50%) scale(1.15);
    background: var(--accent);
  }






  .switch-label {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
  }

  .segmented {
    display: flex;
    padding: 2px;
    margin-left: 4px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
  }

  .segmented button {
    padding: 4px 9px;
    color: var(--ink-2);
    background: transparent;
    border: 0;
    border-radius: 3px;
    font-size: 11px;
  }

  .segmented button.active {
    color: var(--ink-hover);
    background: var(--accent);
    font-weight: 600;
  }

  .number-wrap {
    display: flex;
    align-items: center;
    gap: 5px;
    color: var(--ink-3);
  }

  .number-wrap :global(input) {
    width: 62px;
    height: 30px;
    padding: 0 8px;
    color: var(--ink);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    outline: none;
    text-align: right;
  }

  .number-wrap :global(input:focus),
  .clip-inspector :global(input:focus) {
    background: var(--surface-raised);
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  /* L'avertissement reprend l'orange des blancs : c'est la seule couleur
     d'alerte du système, et en inventer une deuxième ne l'aurait pas rendue
     plus lisible — seulement moins reconnaissable. */
  .ffmpeg-warning {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 12px;
    color: var(--ink-2);
    background: var(--gap-soft);
    border: 1px solid var(--gap-rule);
    border-radius: var(--radius);
    font-size: 11.5px;
  }

  /* -- timeline ------------------------------------------------------------ */

  .timeline-section {
    flex: none;
    height: clamp(240px, 34vh, 340px);
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px 24px 14px;
    background: var(--surface);
    border-top: 1px solid var(--border);
  }

  /* Une vraie barre, au même niveau visuel que le transport : les commandes
     globales précèdent l'inspecteur du clip, puis les réglages de sortie sont
     regroupés à droite. */
  .timeline-toolbar {
    flex: none;
    min-height: 48px;
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    justify-content: flex-start;
    gap: 10px 0;
    padding: 7px 10px;
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
  }

  .tool-group {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 32px;
    padding: 0 16px;
    font-size: 12px;
  }

  .tool-group:not(:last-child) {
    border-right: 1px solid var(--border);
  }

  .clip-inspector {
    flex: 1 0 auto;
    justify-content: center;
  }

  .clip-actions {
    flex: 0 0 110px;
    justify-content: center;
  }

  /* Les réglages de rendu forment le bloc droit de la barre. */
  .settings {
    margin-left: 0;
  }

  .clip-inspector .unit {
    margin: 0 4px 0 -4px;
    color: var(--ink-3);
  }

  .clip-inspector label,
  .tool-group > label {
    color: var(--ink-3);
    white-space: nowrap;
  }

  /* Les boutons à glyphe se lisent à l'encre pleine : en `--ink-2`, une
     flèche de deux pixels disparaissait presque du fond. */
  .glyph {
    min-width: 30px;
    color: var(--ink);
    font-size: 14px;
  }

  .label {
    color: var(--ink);
  }

  /* L'inspecteur occupe la place quoi qu'il arrive. Un bloc qui apparaît à la
     sélection ferait sauter le zoom d'un bout à l'autre de la barre à chaque
     clic — c'est la raison pour laquelle rien ne disparaît dans cette
     application, seulement s'atténue. */

  /* « 1:02:44,3 » tient en neuf signes : à soixante-deux pixels, le champ
     coupait l'heure au moment même où elle devenait longue. */
  .clip-inspector :global(input) {
    width: 92px;
    height: 30px;
    padding: 0 8px;
    color: var(--ink);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    outline: none;
    text-align: right;
  }

  .clip-inspector :global(input:focus) {
    background: var(--surface-raised);
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  .clip-inspector label {
    color: var(--ink-3);
    font-size: 11.5px;
  }

  .clip-inspector .unit {
    margin-left: -2px;
    color: var(--ink-3);
    font-size: 11.5px;
  }


  /* L'orange des blancs sert d'alerte dans tout le dépôt — la confirmation
     d'écrasement l'emploie déjà pour « Remplacer ». */
  .danger {
    color: var(--on-accent);
    background: var(--gap);
    border-color: var(--gap);
    font-weight: 600;
  }

  .danger:hover:not(:disabled) {
    filter: brightness(1.08);
  }


  .timeline-frame {
    min-height: 0;
    flex: 1;
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
  }

  .timeline-scroll {
    width: 100%;
    height: 100%;
    overflow-x: scroll;
    overflow-y: hidden;
    background: var(--app);
    cursor: crosshair;
  }

  .timeline-canvas {
    position: relative;
    height: 100%;
    min-width: 100%;
  }

  .lane {
    position: absolute;
    left: 0;
    right: 0;
    overflow: hidden;
    border-bottom: 1px solid var(--border-subtle);
    transition: background 0.12s ease;
  }

  /* Les deux pistes se distinguent au fond, pas seulement à l'étiquette : on
     cherche « celle du son », pas « celle qui porte ce mot-là ». */
  .image-lane {
    top: 0;
    height: 105px;
    background: var(--surface);
  }

  .audio-lane {
    top: 106px;
    bottom: 0;
    background: var(--app);
  }

  .lane.drop-target {
    background: var(--accent-soft);
    outline: 1px dashed var(--accent);
    outline-offset: -2px;
  }

  /* L'étiquette passe sous les clips : au défilement à zéro elle se posait
     par-dessus le premier, et nommait la piste en cachant son contenu. */
  .lane-label {
    position: sticky;
    top: 5px;
    left: 6px;
    z-index: 1;
    display: inline-block;
    padding: 2px 7px;
    color: var(--ink-2);
    background: var(--glass);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 10px;
    pointer-events: none;
  }

  .lane-help {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: var(--ink-3);
    font-size: 11.5px;
    font-style: italic;
    pointer-events: none;
  }

  .image-clip,
  .audio-clip {
    position: absolute;
    top: 7px;
    bottom: 7px;
    z-index: 3;
    display: flex;
    align-items: center;
    gap: 7px;
    overflow: hidden;
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    box-shadow: var(--shadow);
    cursor: grab;
    user-select: none;
    touch-action: none;
    transition: transform 220ms cubic-bezier(0.22, 1, 0.36, 1),
      box-shadow 180ms ease, opacity 180ms ease;
    will-change: left, transform;
  }

  /* `left` ne s'anime que pendant une permutation. Le zoom recalcule la
     position et la largeur de tous les clips à la fois : lui appliquer cette
     transition faisait glisser les positions anciennes avant leur retour. */
  .timeline-canvas.reordering .image-clip:not(.dragging),
  .timeline-canvas.reordering .audio-clip:not(.dragging) {
    transition: left 240ms cubic-bezier(0.22, 1, 0.36, 1),
      transform 220ms cubic-bezier(0.22, 1, 0.36, 1),
      box-shadow 180ms ease, opacity 180ms ease;
  }

  .image-clip:focus-visible,
  .audio-clip:focus-visible {
    outline: 2px solid var(--ink);
    outline-offset: 2px;
  }

  .image-clip:hover,
  .audio-clip:hover {
    border-color: var(--ink-2);
  }

  .image-clip.selected,
  .audio-clip.selected {
    z-index: 4;
    border: 2px solid var(--ink);
    box-shadow: 0 0 0 2px var(--surface), var(--shadow);
  }

  .image-clip.dragging,
  .audio-clip.dragging {
    z-index: 5;
    cursor: grabbing;
    opacity: 0.96;
    box-shadow: var(--shadow-float);
    transform: translateX(var(--drag-offset)) scale(1.025);
    /* La translation compense instantanément le changement de case. L'animer
       additionnerait brièvement les deux mouvements — le « ressort » surtout
       visible de droite à gauche. */
    transition: box-shadow 180ms ease, opacity 180ms ease;
  }

  /* Les poignées couvrent 12 px à chaque bord du clip. Le contenu commence
     après elles pour que la vignette entière reste visible. */
  .image-clip {
    padding-inline: 13px;
  }

  .clip-thumbnail {
    display: block;
    flex: 0 1 auto;
    min-width: 0;
    width: auto;
    height: auto;
    max-width: min(112px, 100%);
    max-height: 72px;
    object-fit: contain;
    pointer-events: none;
  }

  .image-clip > span {
    min-width: 0;
    flex: 1;
    overflow: hidden;
    font-size: 11px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .image-clip small,
  .audio-clip small {
    z-index: 2;
    margin-right: 10px;
    color: var(--ink-3);
    font-size: 10.5px;
    pointer-events: none;
  }

  .audio-clip {
    background: var(--wave-bed);
    border-color: var(--wave);
  }

  .audio-clip.selected .audio-name b {
    color: var(--on-ink);
    background: var(--ink);
  }

  .audio-clip canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }

  .audio-name {
    z-index: 2;
    min-width: 0;
    flex: 1;
    display: flex;
    align-items: center;
    gap: 6px;
    margin-left: 13px;
    overflow: hidden;
    color: var(--ink);
    font-size: 11.5px;
    text-overflow: ellipsis;
    white-space: nowrap;
    pointer-events: none;
  }

  .audio-name b {
    flex: none;
    padding: 2px 5px;
    color: var(--on-accent);
    background: var(--accent);
    border-radius: 3px;
  }

  /* Le titre est posé sur le tracé, dont la couleur est celle de l'accent :
     en thème clair, une encre sombre sur une onde sombre ne se lisait plus.
     La même pastille de verre que les étiquettes de piste le détache, quel
     que soit ce qu'il y a derrière. */
  .audio-name > span {
    min-width: 0;
    padding: 1px 6px;
    overflow: hidden;
    background: var(--glass);
    border-radius: var(--radius-sm);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .audio-clip small {
    padding: 1px 5px;
    background: var(--glass);
    border-radius: var(--radius-sm);
  }

  .handle {
    position: absolute;
    top: 0;
    bottom: 0;
    z-index: 6;
    width: 12px;
    padding: 0;
    background: var(--surface);
    border: 0;
    border-inline: 1px solid var(--border);
    cursor: ew-resize;
    touch-action: none;
  }

  .handle:hover {
    background: var(--handle-active);
  }

  .handle.left {
    left: 0;
  }

  .handle.right {
    right: 0;
  }

  .snap-line {
    position: absolute;
    top: 0;
    bottom: 0;
    z-index: 12;
    width: 2px;
    background: var(--handle-active);
    box-shadow: 0 0 8px var(--accent-soft);
    transform: translateX(-1px);
    pointer-events: none;
  }

  .playhead {
    position: absolute;
    top: 0;
    bottom: 0;
    z-index: 13;
    width: 14px;
    outline: none;
    cursor: ew-resize;
    touch-action: none;
    transform: translateX(-7px);
  }

  .playhead::before {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    left: 6px;
    width: 2px;
    background: var(--cursor);
    box-shadow: 0 0 0 1px var(--cursor-halo);
  }

  .playhead i {
    position: absolute;
    top: 0;
    left: 2px;
    width: 10px;
    height: 10px;
    background: var(--cursor);
    transform: rotate(45deg);
  }

  .playhead:hover::before,
  .playhead.dragging::before {
    width: 3px;
    box-shadow: 0 0 0 2px var(--cursor-halo), 0 0 10px var(--cursor);
  }

  .playhead:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  /* -- destination et export ----------------------------------------------- */

  .modal-footer {
    min-height: 72px;
    flex: none;
    display: flex;
    align-items: center;
    gap: 18px;
    padding: 12px 24px;
    background: var(--surface-raised);
    border-top: 1px solid var(--border);
  }

  .destination {
    min-width: 0;
    flex: 1;
    display: grid;
    grid-template-columns: 190px minmax(180px, 1fr) auto;
    align-items: center;
    gap: 10px;
    font-size: 12px;
  }

  .destination b {
    display: flex;
    align-items: center;
  }

  .destination input {
    height: 32px;
    min-width: 0;
    padding: 0 10px;
    color: var(--ink);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    font-size: 11.5px;
  }

  .destination input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  .footer-actions {
    flex: none;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  /* Les quatre conditions restantes, ensemble. Une seule à la fois faisait
     découvrir la suivante après l'avoir corrigée, une par aller-retour. */
  .still-left {
    max-width: 320px;
    margin: 0;
    padding-left: 16px;
    color: var(--gap);
    font-size: 11px;
    line-height: 1.4;
  }

  .refuse {
    max-width: 320px;
    color: var(--gap);
    font-size: 11.5px;
  }

  .ready {
    color: var(--accent);
    font: 600 11.5px var(--sans);
  }

  @media (max-width: 1050px) {
    .workspace {
      grid-template-columns: 285px minmax(0, 1fr);
    }

    .image-grid {
      grid-template-columns: repeat(2, 1fr);
    }

    .timeline-toolbar {
      flex-wrap: wrap;
    }

    .tool-group .label {
      display: none;
    }
  }
</style>
