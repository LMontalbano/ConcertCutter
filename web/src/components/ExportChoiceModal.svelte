<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  import { modal } from '../lib/modal'

  let {
    onChooseAudio,
    onChooseVideo,
    onClose,
  }: {
    onChooseAudio: () => void
    onChooseVideo: () => void
    onClose: () => void
  } = $props()

</script>

<div class="veil" role="presentation"
  onclick={(event) => event.target === event.currentTarget && onClose()}>
  <div
    class="dialog"
    use:modal={{ onClose, autofocus: '.choice-card' }}
    role="dialog"
    aria-modal="true"
    aria-label={t('export.choice_title')}
    tabindex="-1"
  >
    <header class="dialog-header">
      <div class="title-wrap">
        <h2>{t('export.choice_title')}</h2>
        <p class="subtitle">{t('export.choice_subtitle')}</p>
      </div>
      <button class="btn quiet icon close-btn" onclick={onClose} aria-label={t('ui.cancel')} title={t('ui.cancel')}>
        ✕
      </button>
    </header>

    <div class="choices-grid">
      <!-- Option 1 : Export Audio -->
      <div
        class="choice-card audio-card"
        role="button"
        tabindex="0"
        onclick={onChooseAudio}
        onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && onChooseAudio()}
      >
        <div class="card-icon">
          <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 18V5l12-2v13" />
            <circle cx="6" cy="18" r="3" />
            <circle cx="18" cy="16" r="3" />
          </svg>
        </div>
        <div class="card-content">
          <div class="card-top">
            <h3 class="card-title">{t('export.audio_title')}</h3>
            <span class="badge">{t('export.audio_tag')}</span>
          </div>
          <p class="card-desc">{t('export.audio_desc')}</p>
        </div>
        <div class="card-arrow">
          <span>→</span>
        </div>
      </div>

      <!-- Option 2 : Export Vidéo -->
      <div
        class="choice-card video-card"
        role="button"
        tabindex="0"
        onclick={onChooseVideo}
        onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && onChooseVideo()}
      >
        <div class="card-icon video">
          <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="23 7 16 12 23 17 23 7" />
            <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
          </svg>
        </div>
        <div class="card-content">
          <div class="card-top">
            <h3 class="card-title">{t('export.video_title')}</h3>
            <span class="badge accent">{t('export.video_tag')}</span>
          </div>
          <p class="card-desc">{t('export.video_desc')}</p>
        </div>
        <div class="card-arrow">
          <span>→</span>
        </div>
      </div>
    </div>

    <footer class="dialog-footer">
      <button class="btn quiet" onclick={onClose}>{t('ui.cancel')}</button>
    </footer>
  </div>
</div>

<style>
  .veil {
    position: fixed;
    inset: 0;
    background: var(--veil);
    display: grid;
    place-items: center;
    padding: 20px;
    z-index: 60;
    backdrop-filter: blur(4px);
  }

  .dialog {
    width: 100%;
    max-width: 580px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-float);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    color: var(--ink);
  }

  .dialog-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 20px 24px 16px;
    border-bottom: 1px solid var(--border);
  }

  .title-wrap h2 {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
    color: var(--ink);
  }

  .subtitle {
    margin: 4px 0 0;
    font-size: 14px;
    color: var(--ink-3);
  }

  .close-btn {
    margin: -4px -4px 0 0;
  }

  .choices-grid {
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  .choice-card {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px 18px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    background: var(--surface-raised);
    cursor: pointer;
    transition: all 0.18s ease;
    user-select: none;
    outline: none;
  }

  .choice-card:hover,
  .choice-card:focus-visible {
    background: var(--hover);
    border-color: var(--accent);
    transform: translateY(-1px);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
  }

  .card-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 52px;
    border-radius: var(--radius);
    background: var(--surface-raised);
    color: var(--accent);
    flex-shrink: 0;
    transition: transform 0.18s ease;
  }

  .card-icon.video {
    color: var(--gap);
  }

  .choice-card:hover .card-icon {
    transform: scale(1.05);
  }

  .card-content {
    flex: 1;
    min-width: 0;
  }

  .card-top {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    margin-bottom: 4px;
  }

  .card-title {
    margin: 0;
    font-size: 17px;
    font-weight: 600;
    color: var(--ink);
  }

  .card-desc {
    margin: 0;
    font-size: 13px;
    color: var(--ink-3);
    line-height: 1.4;
  }

  .card-arrow {
    font-size: 20px;
    color: var(--ink-3);
    transition: transform 0.18s ease, color 0.18s ease;
    padding-right: 4px;
  }

  .choice-card:hover .card-arrow {
    transform: translateX(4px);
    color: var(--accent);
  }

  .dialog-footer {
    display: flex;
    justify-content: flex-end;
    padding: 14px 24px;
    border-top: 1px solid var(--border);
    background: var(--app);
  }
</style>
