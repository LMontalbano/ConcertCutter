<script lang="ts">
  import { tick } from 'svelte'
  import { api, type ExportChoice } from '../lib/api'
  import Hint from './Hint.svelte'

  let { choice, enabled }: { choice: ExportChoice; enabled: boolean } = $props()

  const HELP = {
    onePerTrack:
      'Le morceau 1 reçoit la première image, le 2 la deuxième, et ainsi de ' +
      "suite ; le cycle recommence s'il y a moins d'images que de morceaux. " +
      'Dans la vidéo du concert entier, le fond change donc au morceau ; dans ' +
      'les vidéos de morceaux, chacune garde la sienne. Décochée, les images ' +
      'défilent au chronomètre, ici comme là.',
    slideOnly:
      'Durée du fondu entre deux images. Avec une image par morceau, il joue ' +
      'aux frontières de morceaux, dans la vidéo du concert entier ; une vidéo ' +
      "de morceau n'a qu'une image, donc rien à fondre.",
    slideshow:
      "Les images se relaient dans l'ordre ci-dessus, une toutes les huit " +
      'secondes, et le cycle recommence aussi longtemps que dure le son. ' +
      'Chacune garde ses proportions et se centre sur du noir.',
    stills:
      'Photos du concert, pochette, affiche. Le titre du morceau est incrusté ' +
      'par-dessus.',
  }

  let dragged = $state<number | null>(null)
  let over = $state<{ index: number; after: boolean } | null>(null)
  let tiles: HTMLElement[] = []

  async function add(): Promise<void> {
    const found = await api.pick('images')
    if (found.paths?.length) choice.images = [...choice.images, ...found.paths]
  }

  function grab(index: number, event: DragEvent): void {
    dragged = index
    if (!event.dataTransfer) return
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', String(index))
  }

  function hover(index: number, event: DragEvent): void {
    if (dragged === null) return
    event.preventDefault()
    const box = (event.currentTarget as HTMLElement).getBoundingClientRect()
    over = { index, after: event.clientX > box.left + box.width / 2 }
  }

  function drop(): void {
    if (dragged === null || over === null) return
    const from = dragged
    let to = over.index + (over.after ? 1 : 0)
    if (from < to) to -= 1
    const next = [...choice.images]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    choice.images = next
    release()
  }

  function leave(event: DragEvent): void {
    const towards = event.relatedTarget as Node | null
    if (towards && (event.currentTarget as HTMLElement).contains(towards)) return
    over = null
  }

  function release(): void {
    dragged = null
    over = null
  }

  async function nudge(index: number, by: number): Promise<void> {
    const target = index + by
    if (target < 0 || target >= choice.images.length) return
    const next = [...choice.images]
    ;[next[index], next[target]] = [next[target], next[index]]
    choice.images = next
    await tick()
    tiles[target]?.focus()
  }
</script>

<div class="images" class:off={!enabled}>
  <div class="images-head">
    <span class="label">Fonds</span>
    <button class="btn tonal" onclick={add}>Ajouter des images…</button>
  </div>
  {#if choice.images.length}
    <ul ondragover={(event) => event.preventDefault()} ondragleave={leave}>
      {#each choice.images as image, index (image + index)}
        <li>
          <div
            class="tile"
            class:dragged={dragged === index}
            class:before={over?.index === index && !over.after}
            class:after={over?.index === index && over.after}
          >
            <button
              class="move"
              bind:this={tiles[index]}
              draggable="true"
              title="Glisser pour changer l'ordre"
              aria-label="Fond {index + 1} sur {choice.images.length}. Flèches gauche et droite pour déplacer."
              ondragstart={(event) => grab(index, event)}
              ondragover={(event) => hover(index, event)}
              ondrop={drop}
              ondragend={release}
              onkeydown={(event) => {
                if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
                event.preventDefault()
                nudge(index, event.key === 'ArrowLeft' ? -1 : 1)
              }}
            >
              <img
                src={api.imageUrl(image)}
                alt={image.split(/[\\/]/).pop()}
                draggable="false"
              />
              <span class="mono rank">{index + 1}</span>
              <span class="caption" title={image}>{image.split(/[\\/]/).pop()}</span>
            </button>
            <div class="handles">
              <button
                class="drop"
                onclick={() =>
                  (choice.images = choice.images.filter((_, rank) => rank !== index))}
                aria-label="Retirer cette image"
                title="Retirer"
              >×</button>
            </div>
          </div>
        </li>
      {/each}
    </ul>

    <div class="line tight">
      <label>
        <input type="checkbox" bind:checked={choice.one_per_track} />
        <b>Une seule image par morceau</b>
      </label>
      <Hint text={HELP.onePerTrack} />
    </div>

    <div class="knob" class:off={choice.one_per_track && !choice.video_full}>
      <label for="slide">
        Fondu entre images<Hint
          text={choice.one_per_track ? HELP.slideOnly : HELP.slideshow}
        />
      </label>
      <input
        id="slide"
        class="mono"
        type="number"
        min="0"
        max="60"
        step="0.5"
        bind:value={choice.slide_fade}
      />
      <span class="unit">s</span>
    </div>
  {:else}
    <em>Photos du concert, pochette, affiche.<Hint text={HELP.stills} /></em>
  {/if}
</div>

<style>
  .images {
    margin: 10px 0 0 26px;
    padding: 12px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  .off {
    opacity: 0.45;
    pointer-events: none;
  }

  .images-head {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
  }

  .images-head .btn {
    margin-left: auto;
    height: 26px;
    font-size: 11.5px;
  }

  ul {
    list-style: none;
    margin: 0 0 10px;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(86px, 1fr));
    gap: 8px;
  }

  .tile {
    position: relative;
    display: block;
    border-radius: 7px;
    overflow: hidden;
    background: var(--rule);
    border: 1px solid var(--border);
    cursor: grab;
  }

  .tile:focus-within {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }

  .move {
    display: block;
    width: 100%;
    padding: 0;
    text-align: left;
    color: inherit;
  }

  .tile.dragged {
    opacity: 0.35;
    cursor: grabbing;
  }

  .tile.before::after,
  .tile.after::after {
    content: '';
    position: absolute;
    top: 0;
    bottom: 0;
    width: 3px;
    background: var(--accent);
  }

  .tile.before::after { left: 0; }
  .tile.after::after { right: 0; }

  img {
    display: block;
    width: 100%;
    aspect-ratio: 16 / 9;
    object-fit: cover;
  }

  .rank {
    position: absolute;
    top: 4px;
    left: 4px;
    padding: 1px 5px;
    border-radius: 4px;
    background: var(--ink);
    color: var(--on-ink);
    font-size: 10px;
    font-weight: 500;
  }

  .handles {
    position: absolute;
    inset: 0 0 auto auto;
    display: flex;
    padding: 3px;
    opacity: 0;
    transition: opacity 0.12s;
  }

  .tile:hover .handles,
  .tile:focus-within .handles { opacity: 1; }

  .handles button {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    background: var(--surface);
    color: var(--ink-2);
    font-size: 12px;
    line-height: 1;
  }

  .handles button:hover {
    background: var(--gap);
    color: var(--on-ink);
  }

  .caption {
    display: block;
    padding: 4px 6px;
    font-size: 10.5px;
    color: var(--ink-3);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .line {
    display: flex;
    align-items: center;
  }

  .line.tight { padding: 12px 0 2px; }

  .line label {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }

  .line b { font: 500 13px var(--sans); }

  .knob {
    display: grid;
    grid-template-columns: auto 78px auto;
    align-items: center;
    gap: 8px;
    padding: 10px 0 6px;
  }

  .knob label {
    font-size: 12.5px;
    font-weight: 500;
    white-space: nowrap;
  }

  .knob input {
    height: 30px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    outline: none;
    text-align: right;
  }

  .knob input:focus { border-color: var(--accent); }

  .unit,
  em {
    font-size: 12px;
    color: var(--ink-3);
  }

  em {
    display: block;
    margin-top: 2px;
    font-style: normal;
    line-height: 1.5;
  }
</style>
