<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  import { session } from '../lib/session.svelte'

  const visible = $derived(Boolean(session.updateError) || Boolean(
    session.update && !session.updateDismissed,
  ))
</script>

{#if visible}
  <aside class="update-banner" role={session.updateError ? 'alert' : 'status'}>
    <button
      class="close"
      onclick={() => session.dismissUpdate()}
      aria-label={t('update.dismiss')}
      title={t('update.dismiss')}
    >✕</button>
    {#if session.updateError}
      <div class="copy">
        <strong>{t('update.failed')}</strong>
        <span>{session.updateError}</span>
      </div>
      <div class="actions">
        <button class="btn quiet" onclick={() => session.checkUpdate(true)}>{t('update.retry')}</button>
        <button class="btn strong" onclick={() => session.openUpdateSite()}>{t('update.open_site')}</button>
      </div>
    {:else if session.update}
      <div class="copy">
        <strong>{t('update.available', { version: session.update.latestVersion })}</strong>
      </div>
      <div class="actions">
        <button class="btn strong" onclick={() => session.installUpdate()}>
          {session.update.canAutoUpdate ? t('update.install') : t('update.open_site')}
        </button>
      </div>
    {/if}
  </aside>
{/if}

<style>
  .update-banner {
    position: fixed;
    right: 18px;
    bottom: 18px;
    z-index: 35;
    width: min(440px, calc(100vw - 36px));
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 16px 46px 16px 18px;
    border: 1px solid var(--border);
    border-left: 3px solid var(--accent);
    border-radius: var(--radius-card);
    background: var(--surface);
    box-shadow: var(--shadow-float);
  }

  .copy {
    min-width: 0;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 13px;
    line-height: 1.4;
  }

  .copy strong { color: var(--ink); }
  .copy span { color: var(--ink-2); overflow-wrap: anywhere; }

  .actions {
    display: flex;
    flex: none;
    gap: 8px;
  }

  .close {
    position: absolute;
    top: 8px;
    right: 8px;
    width: 28px;
    height: 28px;
    padding: 0;
    border: 0;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--ink-3);
    cursor: pointer;
  }

  .close:hover { background: var(--hover); color: var(--ink); }

  @media (max-width: 560px) {
    .update-banner { align-items: stretch; flex-direction: column; }
    .actions { justify-content: flex-end; }
  }
</style>
