<script lang="ts">
  import { t, locale, applyLanguage, type LanguageChoice } from '../lib/i18n.svelte'
  /* Les réglages, sortis de l'écran principal. */
  import { api, type Settings } from '../lib/api'
  import { session, message } from '../lib/session.svelte'
  import NumberInput from './NumberInput.svelte'

  let { onClose }: { onClose: () => void } = $props()

  let draft = $state<Settings>({ ...(session.state?.settings as Settings) })
  let saving = $state(false)
  let language = $state<LanguageChoice>(locale.language)
  let panel: HTMLElement

  const fields: Array<{
    key: keyof Settings
    family: 'detection' | 'montage'
    label: string
    unit: string
    help: string
    max: number
    step?: number
  }> = $derived([
    {
      key: 'min_gap',
      family: 'detection',
      label: t('ui.minimum_silence'),
      unit: 's',
      help: t('ui.shorter_silences_are_treated_as_pauses_within_a'),
      max: 3600,
    },
    {
      key: 'min_song',
      family: 'detection',
      label: t('ui.minimum_track'),
      unit: 's',
      help: t('ui.shorter_passages_are_not_counted_as_tracks_seventy'),
      max: 7200,
    },
    {
      key: 'expected',
      family: 'detection',
      label: t('ui.expected_tracks'),
      unit: '',
      help: t('ui.if_you_know_how_many_tracks_the_concert'),
      max: 10000,
      step: 1,
    },
    {
      key: 'pad_start',
      family: 'montage',
      label: t('ui.lead_in'),
      unit: 's',
      help: t('ui.audio_kept_before_the_track_starts_it_extends'),
      max: 60,
    },
    {
      key: 'pad_end',
      family: 'montage',
      label: t('ui.tail'),
      unit: 's',
      help: t('ui.audio_kept_after_the_track_ends_the_lingering'),
      max: 60,
    },
    {
      key: 'fade_ms',
      family: 'montage',
      label: t('ui.anti_click_fades'),
      unit: 'ms',
      help: t('ui.very_short_inaudible_fades_prevent_clicks_caused_by'),
      max: 10000,
    },
  ])

  async function apply(): Promise<void> {
    if (![...panel.querySelectorAll('input')].every(input => input.reportValidity())) return
    saving = true
    try {
      await api.settings(draft)
      const preferences = await api.setLanguage(language)
      applyLanguage(preferences)
      await session.refresh()
      session.note(t('ui.settings_saved'))
      onClose()
    } catch (failure) {
      session.note(message(failure))
    } finally {
      saving = false
    }
  }
</script>

<main bind:this={panel}>
  <div class="sheet">
    <header>
      <div class="title-wrap">
        <h1>{t('ui.options_settings')}</h1>
        <p class="subtitle">{t('ui.audio_analysis_and_export_settings')}</p>
      </div>
      <button class="btn quiet" disabled={saving} onclick={onClose} aria-label={t('ui.close_options')}>
        ✕
      </button>
    </header>

    <section class="language-section">
      <label for="language">{t('preferences.language')}</label>
      <select id="language" bind:value={language} disabled={saving} aria-describedby="language-help">
        <option value="auto">{t('preferences.automatic')}</option>
        <option value="fr" lang="fr">Français</option>
        <option value="en" lang="en">English</option>
      </select>
      <p class="help" id="language-help">{t('preferences.help')}</p>
    </section>

    {#each ['detection', 'montage'] as family (family)}
      <section>
        <div class="section-badge">
          <!-- Les deux titres portent le même accent : ils numérotent une
               même page de réglages. La pastille grise du second le faisait
               passer pour une note en marge de la première. -->
          <span class="badge accent">
            {family === 'detection' ? t('ui.1_detection_ai') : t('ui.2_editing_rendering')}
          </span>
        </div>
        <p class="why">
          {family === 'detection'
            ? t('ui.rules_used_when_analyzing_the_concert_run_analysis')
            : t('ui.trimming_and_fade_rules_applied_when_generating_export')}
        </p>
        <div class="fields-list">
          {#each fields.filter((field) => field.family === family) as field (field.key)}
            <div class="field">
              <label for={field.key}>{field.label}</label>
              <div class="entry">
                <NumberInput
                  id={field.key}
                  disabled={saving}
                  step={field.step ?? 0.1}
                  min={field.key === 'min_gap' ? 0.1 : field.key === 'min_song' ? 1 : 0}
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
      <button class="btn quiet" disabled={saving} onclick={onClose}>{t('ui.cancel')}</button>
      <button class="btn strong" disabled={saving} onclick={apply}>
        {saving ? t('ui.saving') : t('ui.save_options')}
      </button>
    </footer>
  </div>
</main>

<style>
  .language-section {
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: 12px 16px;
    align-items: center;
  }
  .language-section .help { grid-column: 1 / -1; }
  select {
    width: 100%;
    padding: 8px;
    background: var(--surface);
    color: var(--ink);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font: inherit;
  }
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

  .entry :global(input) {
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

  .entry :global(input:focus) {
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

