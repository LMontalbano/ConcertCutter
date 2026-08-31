<script lang="ts">
  /* Les réglages, sortis de l'écran principal. */
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
    max: number
    step?: number
  }> = [
    {
      key: 'min_gap',
      family: 'detection',
      label: 'Silence minimum',
      unit: 's',
      help: "En dessous, un silence n'est pas compté comme une zone à retirer : c'est une respiration au milieu d'un morceau.",
      max: 3600,
    },
    {
      key: 'min_song',
      family: 'detection',
      label: 'Morceau minimum',
      unit: 's',
      help: "En dessous, un passage n'est pas compté comme un morceau. Soixante-quinze secondes écartent les annonces sans écarter les rappels courts.",
      max: 7200,
    },
    {
      key: 'expected',
      family: 'detection',
      label: 'Morceaux attendus',
      unit: '',
      help: 'Si vous savez combien le concert en compte, la détection s\'y tient. Zéro la laisse décider.',
      max: 10000,
      step: 1,
    },
    {
      key: 'pad_start',
      family: 'montage',
      label: 'Amorce avant',
      unit: 's',
      help: "Conservée avant l'entrée du morceau. Elle mord sur la fin de la zone retirée qui précède, donc elle rattrape le retard de la détection sans coûter d'applaudissements.",
      max: 60,
    },
    {
      key: 'pad_end',
      family: 'montage',
      label: 'Queue après',
      unit: 's',
      help: 'Conservée après la fin du morceau : la note qui traîne, et le début des applaudissements.',
      max: 60,
    },
    {
      key: 'fade_ms',
      family: 'montage',
      label: 'Fondus anti-clic',
      unit: 'ms',
      help: 'Très courts et inaudibles : ils suppriment le clic que produirait une coupe franche au milieu d\'une onde.',
      max: 10000,
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
      <div class="title-wrap">
        <h1>Options & Réglages</h1>
        <p class="subtitle">Paramètres d'analyse acoustique et d'export</p>
      </div>
      <button class="btn quiet" onclick={onClose} aria-label="Fermer les options">
        ✕
      </button>
    </header>

    {#each ['detection', 'montage'] as family (family)}
      <section>
        <div class="section-badge">
          <!-- Les deux titres portent le même accent : ils numérotent une
               même page de réglages. La pastille grise du second le faisait
               passer pour une note en marge de la première. -->
          <span class="badge accent">
            {family === 'detection' ? '1. Détection & IA' : '2. Montage & Rendu'}
          </span>
        </div>
        <p class="why">
          {family === 'detection'
            ? "Règles appliquées lors de l'analyse du concert. Modifier ces valeurs demande de relancer l'analyse."
            : "Règles de coupe et fondus appliquées lors de la génération des fichiers à l'export."}
        </p>
        <div class="fields-list">
          {#each fields.filter((field) => field.family === family) as field (field.key)}
            <div class="field">
              <label for={field.key}>{field.label}</label>
              <div class="entry">
                <input
                  id={field.key}
                  class="mono"
                  type="number"
                  step={field.step ?? 0.1}
                  min="0"
                  max={field.max}
                  bind:value={draft[field.key]}
                />
                <span class="unit">{field.unit}</span>
              </div>
              <p class="help">{field.help}</p>
            </div>
          {/each}
        </div>
      </section>
    {/each}

    <footer>
      <button class="btn quiet" onclick={onClose}>Annuler</button>
      <button class="btn strong" disabled={saving} onclick={apply}>
        {saving ? 'Enregistrement…' : 'Enregistrer les options'}
      </button>
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
    width: min(760px, 100%);
    margin: 0 auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-float);
    padding: 30px 34px 24px;
  }

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }

  .title-wrap {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  h1 {
    margin: 0;
    font: 700 20px/1.2 var(--sans);
    letter-spacing: -0.01em;
    color: var(--ink);
  }

  .subtitle {
    margin: 0;
    font-size: 13px;
    color: var(--ink-3);
  }

  section {
    padding: 18px 0;
    border-bottom: 1px solid var(--rule);
  }

  .section-badge {
    margin-bottom: 6px;
  }

  .why {
    margin: 0 0 16px;
    font-size: 13px;
    color: var(--ink-2);
    line-height: 1.45;
  }

  .fields-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .field {
    display: grid;
    grid-template-columns: 180px 130px 1fr;
    align-items: center;
    gap: 16px;
    padding: 10px 12px;
    border-radius: var(--radius);
    background: var(--surface-raised);
    border: 1px solid var(--border-subtle);
  }

  label {
    font-weight: 600;
    font-size: 13px;
    color: var(--ink);
  }

  .entry {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .entry input {
    width: 80px;
    height: 32px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface);
    color: var(--ink);
    font: 600 13px var(--mono);
    outline: none;
    text-align: right;
  }

  .entry input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-soft);
  }

  .unit {
    font: 600 12px var(--mono);
    color: var(--ink-3);
  }

  .help {
    margin: 0;
    font-size: 12px;
    line-height: 1.45;
    color: var(--ink-3);
  }

  footer {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    padding-top: 24px;
  }
</style>

