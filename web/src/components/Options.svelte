<script lang="ts">
  /* Les réglages, sortis de l'écran principal.

     Ils y occupaient un bandeau permanent alors qu'on les touche une fois par
     séance — et le plus souvent jamais. Les mettre à part n'est pas les
     cacher : chacun est ici accompagné de ce qu'il change, ce qu'un champ de
     six caractères sur une barre d'outils ne pouvait pas dire.

     Deux familles, et la frontière compte : la détection agit sur ce que
     l'analyse trouve, donc la changer demande de réanalyser ; le montage agit
     sur ce que l'export écrit, donc il se change jusqu'au dernier moment. */
  import { api, type Settings } from '../lib/api'
  import { session, message } from '../lib/session.svelte'

  let { onClose }: { onClose: () => void } = $props()

  let draft = $state<Settings>({ ...(session.state?.settings as Settings) })
  let saving = $state(false)

  const fields: Array<{
    key: keyof Settings
    family: 'detection' | 'montage'
    label: string
    unit: string
    help: string
  }> = [
    {
      key: 'min_gap',
      family: 'detection',
      label: 'Blanc minimum',
      unit: 's',
      help: "En dessous, un silence n'est pas compté comme une coupure : c'est une respiration au milieu d'un morceau.",
    },
    {
      key: 'min_song',
      family: 'detection',
      label: 'Morceau minimum',
      unit: 's',
      help: "En dessous, un passage n'est pas compté comme un morceau. Soixante-quinze secondes écartent les annonces sans écarter les rappels courts.",
    },
    {
      key: 'expected',
      family: 'detection',
      label: 'Morceaux attendus',
      unit: '',
      help: 'Si vous savez combien le concert en compte, la détection s\'y tient. Zéro la laisse décider.',
    },
    {
      key: 'pad_start',
      family: 'montage',
      label: 'Amorce avant',
      unit: 's',
      help: "Conservée avant l'entrée du morceau. Elle mord sur la fin du blanc précédent, donc elle rattrape le retard de la détection sans coûter d'applaudissements.",
    },
    {
      key: 'pad_end',
      family: 'montage',
      label: 'Queue après',
      unit: 's',
      help: 'Conservée après la fin du morceau : la note qui traîne, et le début des applaudissements.',
    },
    {
      key: 'fade_ms',
      family: 'montage',
      label: 'Fondus',
      unit: 'ms',
      help: 'Très courts, et inaudibles : ils suppriment le clic que produirait une coupe franche au milieu d\'une onde.',
    },
  ]

  async function apply(): Promise<void> {
    saving = true
    try {
      await api.settings(draft)
      await session.refresh()
      session.note('Réglages enregistrés.')
      onClose()
    } catch (failure) {
      session.note(message(failure))
    } finally {
      saving = false
    }
  }
</script>

<main>
  <div class="sheet">
    <header>
      <h1>Options</h1>
      <button class="btn quiet" onclick={onClose}>Fermer</button>
    </header>

    {#each ['detection', 'montage'] as family (family)}
      <section>
        <span class="label">
          {family === 'detection' ? 'Détection' : 'Montage'}
        </span>
        <p class="why">
          {family === 'detection'
            ? "Ce que l'analyse cherche. Modifier ces valeurs demande de relancer l'analyse."
            : "Ce que l'export écrit autour de chaque morceau. Modifiable jusqu'au dernier moment."}
        </p>
        {#each fields.filter((field) => field.family === family) as field (field.key)}
          <div class="field">
            <label for={field.key}>{field.label}</label>
            <div class="entry">
              <input
                id={field.key}
                class="mono"
                type="number"
                step="0.1"
                min="0"
                bind:value={draft[field.key]}
              />
              <span class="unit">{field.unit}</span>
            </div>
            <p class="help">{field.help}</p>
          </div>
        {/each}
      </section>
    {/each}

    <footer>
      <button class="btn quiet" onclick={onClose}>Annuler</button>
      <button class="btn strong" disabled={saving} onclick={apply}>Enregistrer</button>
    </footer>
  </div>
</main>

<style>
  main {
    flex: 1;
    overflow-y: auto;
    padding: 32px;
    min-height: 0;
  }

  .sheet {
    width: min(720px, 100%);
    margin: 0 auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow);
    padding: 26px 30px 22px;
  }

  header {
    display: flex;
    align-items: center;
    margin-bottom: 24px;
  }

  h1 {
    margin: 0;
    font: 600 20px var(--sans);
    letter-spacing: -0.01em;
  }

  header .btn {
    margin-left: auto;
  }

  section {
    padding-top: 18px;
    border-top: 1px solid var(--rule);
    margin-bottom: 8px;
  }

  .why {
    margin: 8px 0 18px;
    font-size: 12.5px;
    color: var(--ink-2);
    max-width: 54ch;
  }

  .field {
    display: grid;
    grid-template-columns: 180px 140px 1fr;
    align-items: baseline;
    gap: 14px;
    padding: 10px 0;
  }

  label {
    font-weight: 500;
    font-size: 13px;
  }

  .entry {
    display: flex;
    align-items: center;
    gap: 7px;
  }

  .entry input {
    width: 84px;
    height: 32px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    outline: none;
    text-align: right;
  }

  .entry input:focus {
    border-color: var(--accent);
  }

  .unit {
    font-size: 12px;
    color: var(--ink-3);
  }

  .help {
    margin: 0;
    font-size: 12px;
    line-height: 1.5;
    color: var(--ink-3);
  }

  footer {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding-top: 20px;
    border-top: 1px solid var(--rule);
  }
</style>
