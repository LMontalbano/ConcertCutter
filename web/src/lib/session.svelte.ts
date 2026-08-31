/* L'état de l'écran : ce que le serveur dit, plus ce qui ne le regarde pas.

   La segmentation, l'historique et les réglages vivent côté Python — le
   navigateur les reçoit, il ne les détient pas. Ce qui vit ici est ce que le
   serveur n'a aucune raison de connaître : où en est la lecture, quel segment
   on regarde, quelle fenêtre est zoomée, quel message est affiché.

   La distinction n'est pas de principe. Elle décide de ce qui survit à un
   rechargement de la page : le travail, oui ; la position de la loupe, non. */

import { api, follow, ApiError, type Job, type Segment, type State } from './api'

export const MIN_VIEW_S = 4
/** Ce que la carte d'édition montre au-delà du morceau, de chaque côté.

    C'est l'évolution A : sans cette marge, les deux poignées tombent sur les
    bords du tracé — impossible de les saisir, et on ne voit jamais les
    applaudissements, seule chose qui dise si la coupe est au bon endroit. */
export const CONTEXT_S = 15

class Session {
  state = $state<State | null>(null)
  envelope = $state<Float32Array>(new Float32Array(0))
  envelopeFps = $state(4)

  /** Rang du segment regardé dans la carte d'édition. */
  selected = $state(0)
  playhead = $state(0)
  playing = $state(false)
  loop = $state<number | null>(null)

  /** Fenêtre de la carte d'édition : instant de gauche, et durée montrée. */
  viewStart = $state(0)
  viewSpan = $state(60)
  zoomed = $state(false)
  /** Vrai quand la vue a été choisie à la main, et ne doit plus suivre le son. */
  pinned = $state(false)
  /** Vrai dès que la fenêtre a été cadrée sur un segment de ce concert.

      Un travail rouvert arrive avec sa segmentation déjà faite : il ne repasse
      pas par `analyze`, donc rien n'appelait `frame`, et la carte gardait la
      fenêtre de soixante secondes du démarrage. Le premier morceau s'y
      trouvait coupé, et il fallait dézoomer pour le voir en entier. */
  private framed = false

  screen = $state<'empty' | 'main' | 'options'>('empty')
  theme = $state<'dark' | 'light'>('dark')
  exporting = $state(false)
  message = $state('')
  problem = $state('')
  missingSource = $state<{ project: string; missing: string } | null>(null)
  job = $state<Job | null>(null)
  dialogs = $state(true)

  private audio: HTMLAudioElement | null = null
  private noteTimer = 0
  private levelsTimer = 0

  // -- ce qui se déduit --------------------------------------------------

  get segments(): Segment[] {
    return this.state?.segments ?? []
  }

  get duration(): number {
    return this.state?.duration ?? 0
  }

  get open(): boolean {
    return Boolean(this.state?.source)
  }

  get analysed(): boolean {
    return this.segments.length > 0
  }

  get segment(): Segment | null {
    return this.segments[this.selected] ?? null
  }

  /** Les zones à retirer comptées à part : c'est ce que l'en-tête dit. */
  get counts(): { tracks: number; gaps: number } {
    return {
      tracks: this.state?.tracks.length ?? 0,
      gaps: this.segments.filter((segment) => segment.kind === 'gap').length,
    }
  }

  // -- démarrage ----------------------------------------------------------

  /** Pose le thème sur le document, et s'en souvient.

      Le sombre est le défaut : on découpe un concert le soir, longtemps, en
      regardant un tracé lumineux. Le choix est retenu d'une séance à l'autre —
      le redemander à chaque lancement reviendrait à ne pas l'avoir offert. */
  dress(wanted?: 'dark' | 'light'): void {
    const chosen =
      wanted ??
      ((localStorage.getItem('cc-theme') as 'dark' | 'light' | null) ?? 'dark')
    this.theme = chosen
    document.documentElement.dataset.theme = chosen
    try {
      localStorage.setItem('cc-theme', chosen)
    } catch {
      /* un stockage refusé ne doit pas empêcher de changer de thème */
    }
    void api.theme(chosen).catch(() => {})
  }

  flip(): void {
    this.dress(this.theme === 'dark' ? 'light' : 'dark')
  }

  async boot(): Promise<void> {
    this.dress()
    try {
      const found = await api.recent()
      this.dialogs = found.dialogs
    } catch {
      /* l'accueil se passe de la liste des travaux */
    }
    await this.run(() => this.refresh())
  }

  async refresh(): Promise<void> {
    const found = await api.state()
    if (found.opening) {
      await this.watch(found.opening)
      return this.refresh()
    }
    this.adopt(found)
    if (this.state?.hasLevels && !this.envelope.length) await this.loadEnvelope()
    this.awaitLevels()
  }

  /** Redemande l'état tant que l'enveloppe n'est pas lue.

      Lire l'enveloppe d'un concert de deux heures prend une quinzaine de
      secondes, et un fichier passé en argument est ouvert pendant que la
      fenêtre s'affiche : la page arrivait alors sur un concert sans niveaux,
      ne le redemandait jamais, et gardait un ruban et vingt-cinq vignettes
      vides jusqu'au prochain geste — ou pour toujours. */
  private awaitLevels(): void {
    window.clearTimeout(this.levelsTimer)
    if (!this.open || this.state?.hasLevels) return
    this.levelsTimer = window.setTimeout(() => void this.refresh(), 700)
  }

  private adopt(found: State): void {
    this.state = found
    if (!found.source) {
      this.screen = 'empty'
      return
    }
    if (this.screen === 'empty') this.screen = 'main'
    if (this.selected >= found.segments.length) {
      this.selected = 0
      this.frame()
    } else if (!this.framed && found.segments.length) {
      // Première segmentation reçue pour ce concert : c'est ici qu'arrive un
      // travail rouvert, qui ne passe jamais par `analyze`.
      this.showFirstTrack()
    }
    // La vue ne se recadre pas sur une édition. Elle le faisait, et déplacer
    // une poignée vers la droite faisait alors sauter le tracé sous le
    // curseur : la fenêtre se recentrait sur un segment qui venait de
    // rétrécir, en plein glissé. Le cadrage appartient aux gestes qui
    // *changent de segment*, pas à ceux qui le modifient.
  }

  private async loadEnvelope(): Promise<void> {
    const { data, headers } = await api.envelope()
    this.envelope = data
    this.envelopeFps = Number(headers.get('X-Fps')) || 4
  }

  // -- ouverture ----------------------------------------------------------

  async openFile(kind: 'wav' | 'project' = 'wav', path?: string): Promise<void> {
    this.missingSource = null
    await this.run(async () => {
      const started = await api.open(path, kind)
      if ('cancelled' in started && started.cancelled) return
      await this.watch(started as Job)
      this.envelope = new Float32Array(0)
      this.stop()
      this.selected = 0
      this.playhead = 0
      this.framed = false
      await this.refresh()
      this.note(`« ${this.state?.name ?? ''} » ouvert.`)
    })
  }

  /** Reprend un travail dont l'enregistrement a bougé, en le redemandant. */
  async relocate(projectPath: string, missing: string): Promise<void> {
    const name = missing.split(/[\\/]/).pop() ?? ''
    const found = await api.pick('source', { name })
    if (!found.path) return
    await this.run(async () => {
      await this.watch((await api.open(projectPath, 'project', found.path)) as Job)
      this.envelope = new Float32Array(0)
      this.framed = false
      await this.refresh()
      this.missingSource = null
      this.problem = ''
    })
  }

  async analyze(): Promise<void> {
    await this.run(async () => {
      await this.watch(await api.analyze())
      this.envelope = new Float32Array(0)
      await this.refresh()
      this.showFirstTrack()
      this.note(`${this.counts.tracks} morceaux trouvés.`)
    })
  }

  // -- édition ------------------------------------------------------------

  /** Une édition ne s'annonce pas quand elle réussit.

      Chacune portait sa phrase — « Coupe déplacée à 3:37,0 », « Titre
      enregistré », « Passage conservé ». Or régler un concert, c'est enchaîner
      ces gestes par dizaines : la bulle repassait à chaque poignée lâchée pour
      redire ce que le tracé venait de montrer. Elle ne sert plus qu'à ce que
      l'écran ne peut pas dire — voir `note`. Un refus, lui, parle toujours :
      c'est le seul cas où rien ne bouge à l'écran. */
  async edit(body: Record<string, unknown>): Promise<boolean> {
    try {
      this.adopt(await api.edit(body))
      return true
    } catch (failure) {
      this.note(message(failure))
      return false
    }
  }

  async undo(): Promise<void> {
    try {
      this.adopt(await api.undo())
    } catch (failure) {
      this.note(message(failure))
    }
  }

  async redo(): Promise<void> {
    try {
      this.adopt(await api.redo())
    } catch (failure) {
      this.note(message(failure))
    }
  }

  select(index: number): void {
    if (index < 0 || index >= this.segments.length) return
    this.selected = index
    // Désigner un segment, c'est vouloir le regarder — y compris pendant que
    // le son avance ailleurs. La lecture cessait sinon de laisser choisir :
    // elle ramenait la vue sur le morceau en cours à chaque battement, et
    // cliquer sur un autre dans la liste ne tenait pas une demi-seconde.
    this.pinned = true
    this.zoomed = false
    this.frame()
  }

  /** Écoute ce segment depuis son début, ou s'arrête s'il joue déjà.

      Séparé de la sélection : parcourir la liste pour regarder les découpes
      déclenchait le son vingt-cinq fois de suite, ce qui devient vite pénible.
      Chaque ligne porte donc son propre bouton. */
  playing_at(index: number): boolean {
    const segment = this.segments[index]
    return Boolean(
      segment && this.playing &&
        this.playhead >= segment.start && this.playhead < segment.end,
    )
  }

  play(index: number): void {
    const segment = this.segments[index]
    if (!segment) return
    if (this.playing_at(index)) {
      this.audio?.pause()
      return
    }
    this.loop = null
    this.select(index)
    this.seek(segment.start)
    void this.audio?.play().catch(() => {
      /* le navigateur peut refuser avant le premier geste : rien à dire */
    })
  }

  /** Fait suivre la sélection à la tête de lecture.

      La vue d'ensemble déplace la loupe quand on y clique ; le transport doit
      faire de même, sinon écouter un concert d'un bout à l'autre laisse la
      carte d'édition sur le premier morceau. Le zoom, lui, est respecté : on
      ne recadre que si l'utilisateur ne s'est pas placé lui-même.

      Et la vue ne suit plus quand on l'a choisie à la main : `pinned` tient
      jusqu'au prochain déplacement volontaire de la tête de lecture. */
  private follow(): void {
    const index = this.segments.findIndex(
      (segment) => segment.start <= this.playhead && this.playhead < segment.end,
    )
    if (index < 0) return
    // La vue ne bouge que quand la lecture est **sortie du cadre**, et non à
    // chaque changement de segment : la carte montre exprès les zones à
    // retirer voisines, et y entrer recadrait dessus alors qu'on regardait le
    // morceau. Le test vaut aussi à segment inchangé — la lecture finit par
    // quitter une longue zone montrée en partie, et la tête sortirait de
    // l'écran sans que rien ne la rattrape.
    const shown = this.shows(this.playhead)
    this.selected = index
    if (!this.zoomed && !shown) this.frame()
  }

  /** Vrai quand cet instant est déjà dans la fenêtre montrée. */
  private shows(moment: number): boolean {
    return moment >= this.viewStart && moment <= this.viewStart + this.viewSpan
  }

  /** Se place sur le premier morceau du concert, et cadre la vue dessus. */
  private showFirstTrack(): void {
    const first = this.segments.findIndex((segment) => segment.kind === 'music')
    this.selected = first < 0 ? 0 : first
    this.frame()
  }

  /** Cadre la fenêtre sur le segment regardé, marges comprises.

      La fenêtre glisse vers la gauche plutôt que de se raboter quand le
      segment touche la fin du concert : `duration - viewStart` mangeait sinon
      la marge de droite, et le dernier morceau arrivait collé au bord. */
  frame(): void {
    const segment = this.segment
    if (!segment) return
    const wanted = segment.end - segment.start + CONTEXT_S * 2
    this.viewStart = Math.max(
      0,
      Math.min(segment.start - CONTEXT_S, this.duration - wanted),
    )
    this.viewSpan = Math.min(this.duration - this.viewStart, wanted)
    this.zoomed = false
    this.framed = true
  }

  zoom(factor: number, focus: number): void {
    const span = Math.min(
      this.duration,
      Math.max(MIN_VIEW_S, this.viewSpan * factor),
    )
    const share = (focus - this.viewStart) / this.viewSpan
    this.viewStart = Math.max(0, Math.min(this.duration - span, focus - share * span))
    this.viewSpan = span
    this.zoomed = true
  }

  pan(seconds: number): void {
    this.viewStart = Math.max(0, Math.min(this.duration - this.viewSpan, seconds))
    this.zoomed = true
  }

  // -- lecture ------------------------------------------------------------

  useAudio(element: HTMLAudioElement): void {
    this.audio = element
  }

  seek(seconds: number): void {
    this.playhead = Math.max(0, Math.min(this.duration, seconds))
    if (this.audio) this.audio.currentTime = this.playhead
    // Déplacer la tête soi-même, c'est demander à voir là où l'on va : la vue
    // reprend sa liberté de suivre.
    this.pinned = false
    this.follow()
  }

  /** Déplace la tête de lecture sans toucher au cadrage.

      C'est le clic dans la carte d'édition. Elle montre quinze secondes des
      zones à retirer voisines pour qu'on juge la coupe sur les
      applaudissements ; cliquer dedans pour les écouter passait par `seek`,
      qui suit la tête — la vue sautait donc sur la zone à retirer, et le
      morceau qu'on était en train de régler disparaissait. La loupe reste où
      on l'a mise, le son part d'où on a cliqué, et la vue ne se remet à
      suivre qu'au prochain déplacement volontaire ailleurs. */
  scrub(seconds: number): void {
    this.playhead = Math.max(0, Math.min(this.duration, seconds))
    if (this.audio) this.audio.currentTime = this.playhead
    this.pinned = true
  }

  toggle(): void {
    if (!this.audio) return
    if (this.playing) this.audio.pause()
    else void this.audio.play().catch(() => this.note("La lecture n'a pas démarré."))
  }

  stop(): void {
    this.loop = null
    this.audio?.pause()
  }

  /** Répète sans fin le segment sous le curseur.

      Caler une frontière demande de réentendre le même passage dix fois de
      suite ; le relancer à la main laisse à chaque reprise le temps d'oublier
      ce qu'on venait d'entendre. */
  toggleLoop(): void {
    // Sans phrase dans les deux sens : le bouton « Boucler (B) » s'allume et
    // s'éteint, et c'est le geste qu'on répète le plus en calant une coupe.
    if (this.loop !== null) {
      this.loop = null
      return
    }
    const index = this.segments.findIndex(
      (segment) => segment.start <= this.playhead && this.playhead < segment.end,
    )
    if (index < 0) {
      this.note('Aucun segment sous le curseur.')
      return
    }
    this.loop = index
    this.seek(this.segments[index].start)
    void this.audio?.play()
  }

  /** Rappelé par la balise `<audio>` : c'est elle qui donne l'heure.

      Les bornes de la boucle sont relues à chaque tour : déplacer la frontière
      pendant qu'elle tourne change ce qu'on entend au tour suivant, ce qui est
      précisément ce qu'on cherche à juger. */
  tick(seconds: number): void {
    this.playhead = seconds
    if (!this.pinned) this.follow()
    if (this.loop === null) return
    const segment = this.segments[this.loop]
    if (!segment) {
      this.loop = null
      return
    }
    if (seconds >= segment.end || seconds < segment.start - 0.5) {
      this.seek(segment.start)
    }
  }

  // -- travaux longs ------------------------------------------------------

  private async watch(job: Job): Promise<Job> {
    const done = await follow(job, (tick) => {
      this.job = tick
    })
    this.job = null
    return done
  }

  async run(work: () => Promise<void>): Promise<void> {
    this.problem = ''
    try {
      await work()
    } catch (failure) {
      if (failure instanceof ApiError && typeof failure.extra.missing === 'string') {
        this.problem = failure.message
        this.missingSource = {
          project: String(failure.extra.project ?? ''),
          missing: failure.extra.missing,
        }
        return
      }
      this.problem = message(failure)
    } finally {
      this.job = null
    }
  }

  /** Dit ce que l'écran ne montre pas, et rien d'autre.

      Trois cas seulement : un refus, un échec, et la fin d'un travail long —
      ouverture, analyse, export. Tout ce dont le résultat se voit à l'instant
      où il arrive se passe de phrase ; une bulle qui commente chaque geste
      finit par ne plus rien signaler du tout. */
  note(text: string): void {
    this.message = text
    window.clearTimeout(this.noteTimer)
    this.noteTimer = window.setTimeout(() => {
      this.message = ''
    }, 4200)
  }
}

export function message(failure: unknown): string {
  if (failure instanceof ApiError) return failure.message
  if (failure instanceof Error) return failure.message
  return String(failure)
}

export const session = new Session()
