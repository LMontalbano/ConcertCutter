import { t, translatePayload, type Preferences, type LanguageChoice } from './i18n.svelte'
/* Le seul endroit qui parle au serveur.

   Toutes les requêtes portent le jeton du lancement, lu une fois dans la page
   servie. Aucune autre page ne l'a, et c'est ce qui empêche un onglet ouvert
   ailleurs d'utiliser ce serveur comme une lecture du disque. */

const TOKEN =
  document.querySelector<HTMLMetaElement>('meta[name="cc-token"]')?.content ?? ''

export interface Segment {
  index: number
  start: number
  end: number
  kind: 'music' | 'gap'
  confidence: number
  title: string
  number: number | null
  trackTitle: string
  isTrackStart: boolean
}

export interface Track {
  number: number
  title: string
  start: number
  end: number
  confidence: number
}

export interface Settings {
  min_gap: number
  min_song: number
  expected: number
  pad_start: number
  pad_end: number
  fade_ms: number
}

export interface ExportChoice {
  dir: string
  image: string
  images: string[]
  crossfade: number
  /** Celui de la vidéo du concert entier : deux documents, deux montages. */
  video_crossfade: number
  slide_fade: number
  one_per_track: boolean
  selection: number[] | null
  full: boolean
  tracks: boolean
  video_full: boolean
  video_tracks: boolean
}

export interface State {
  source: string
  name: string
  duration: number
  samplerate: number
  channels: number
  levelsFps: number
  hasLevels: boolean
  hasFeatures: boolean
  canUndo: boolean
  canRedo: boolean
  saved: string
  settings: Settings
  export: ExportChoice
  warnings: string[]
  video: string | null
  segments: Segment[]
  tracks: Track[]
  opening?: Job
  cancelled?: boolean
}

export interface Job {
  id: string
  kind: string
  phase: string
  done: number
  total: number
  state: 'running' | 'done' | 'failed' | 'cancelled'
  result: unknown
  error: string
  missing?: string
  project?: string
}

export interface UpdateInfo {
  status: 'idle' | 'upToDate' | 'available' | 'failed'
  currentVersion: string
  latestVersion?: string
  size?: number
  canAutoUpdate: boolean
  error?: string
}

export class ApiError extends Error {
  /** Ce que le serveur refuse porte sa phrase : on la montre telle quelle. */
  constructor(
    message: string,
    readonly status: number,
    readonly extra: Record<string, unknown> = {},
  ) {
    super(message)
  }
}

async function call<T>(route: string, body?: unknown): Promise<T> {
  const answer = await fetch(route, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      'X-ConcertCutter-Token': TOKEN,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const payload = translatePayload(await answer.json().catch(() => ({})))
  if (!answer.ok) {
    const { error, ...extra } = payload as { error?: string }
    throw new ApiError(error ?? t('ui.error_value', { p0: answer.status }), answer.status, extra)
  }
  return payload as T
}

/** Un POST sans corps reste un POST.

    Sans ce raccourci, `call('/api/analyze')` partait en GET — le corps absent
    décidait de la méthode — et le serveur répondait « route inconnue » à une
    demande d'analyse parfaitement formée. */
const post = <T>(route: string, body: unknown = {}) => call<T>(route, body)

async function binary(
  route: string,
  signal?: AbortSignal,
): Promise<{ data: Float32Array; headers: Headers }> {
  const answer = await fetch(route, {
    headers: { 'X-ConcertCutter-Token': TOKEN },
    signal,
  })
  if (!answer.ok) throw new ApiError(t('ui.error_value', { p0: answer.status }), answer.status)
  return { data: new Float32Array(await answer.arrayBuffer()), headers: answer.headers }
}

export const api = {
  preferences: () => call<Preferences>('/api/preferences'),
  setLanguage: (language: LanguageChoice) => call<Preferences>('/api/preferences', { language }),
  setPreferences: (language: LanguageChoice, checkUpdates: boolean) =>
    call<Preferences>('/api/preferences', { language, checkUpdates }),
  updateStatus: () => call<UpdateInfo>('/api/update?online=0'),
  checkUpdate: () => call<UpdateInfo>('/api/update'),
  downloadUpdate: () => post<Job>('/api/update/download'),
  restartForUpdate: () => post<{ restarting: boolean }>('/api/update/restart'),
  openUpdateSite: () => post<{ opened: boolean }>('/api/update/site'),
  token: TOKEN,
  state: () => call<State>('/api/state'),
  open: (path?: string, kind?: string, source?: string) =>
    call<Job & Partial<State>>('/api/open', { path, kind, source }),
  pick: (kind: string, extra: Record<string, unknown> = {}) =>
    call<{ path?: string; paths?: string[] }>('/api/pick', { kind, ...extra }),
  analyze: () => post<Job>('/api/analyze'),
  edit: (body: Record<string, unknown>) => call<State>('/api/edit', body),
  undo: () => post<State>('/api/undo'),
  redo: () => post<State>('/api/redo'),
  settings: (settings: Partial<Settings>) => call<State>('/api/settings', { settings }),
  planExport: (choice: ExportChoice) =>
    call<{
      target: string
      conflict: boolean
      proposed?: string
      overwritten?: number
      leftovers?: number
    }>('/api/export/plan', choice),
  render: (choice: ExportChoice & { target: string; replace: boolean }) =>
    call<Job>('/api/export', choice),
  job: (id: string) => call<Job>(`/api/job?id=${encodeURIComponent(id)}`),
  navigate: (from: number, to: 'next' | 'previous' | 'section') =>
    call<{ moment: number }>(`/api/navigate?from=${from.toFixed(3)}&to=${to}`),
  save: () => post<{ saved: string; when: string }>('/api/save'),
  cancel: (id: string) => call<Job>('/api/cancel', { id }),
  theme: (theme: 'dark' | 'light') => call<{ theme: string }>('/api/theme', { theme }),
  recent: () => call<{ projects: RecentProject[]; dialogs: boolean }>('/api/recent'),
  installFfmpeg: () => post<Job>('/api/ffmpeg'),
  envelope: () => binary('/api/envelope'),
  peaks: (start: number, duration: number, width: number, signal?: AbortSignal) =>
    binary(
      `/api/peaks?start=${start.toFixed(3)}&duration=${duration.toFixed(3)}&width=${width}`,
      signal,
    ),
  audioUrl: () => `/api/audio?token=${encodeURIComponent(TOKEN)}`,
  /** Vignette d'un fond vidéo. Le serveur ne sert que les images choisies
      dans le sélecteur : c'est ce qui empêche cette route de devenir une
      lecture de disque à travers une simple balise `<img>`. */
  imageUrl: (path: string) =>
    `/api/image?path=${encodeURIComponent(path)}&token=${encodeURIComponent(TOKEN)}`,
}

export interface RecentProject {
  path: string
  name: string
  saved: string
  tracks: number
}

/** Suit un travail long jusqu'à son terme, en demandant deux fois par seconde.

    Pas de SSE ni de WebSocket : ils économiseraient deux requêtes par seconde
    sur une boucle locale, au prix d'une connexion à tenir ouverte. */
/** Suit un travail jusqu'à son terme, quel qu'il soit.

    Trois fins possibles, et `cancelled` n'en est pas une mauvaise : un export
    qu'on a soi-même arrêté n'a rien d'une erreur, et l'annoncer en rouge
    reviendrait à reprocher à l'utilisateur ce qu'il vient de demander. Seul
    `failed` lève. */
export async function follow(job: Job, onTick: (job: Job) => void): Promise<Job> {
  let current = job
  onTick(current)
  while (current.state === 'running') {
    await new Promise((resume) => setTimeout(resume, 500))
    current = await api.job(current.id)
    onTick(current)
  }
  if (current.state === 'failed') {
    const { error: _error, ...extra } = current
    throw new ApiError(current.error, 500, extra)
  }
  return current
}
