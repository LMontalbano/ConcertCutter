<script lang="ts">
  import { t } from '../lib/i18n.svelte'
  import { modal } from '../lib/modal'

  let { conflict, onBeside, onReplace, onCancel }: {
    conflict: { target: string; proposed: string; overwritten: number; leftovers: number }
    onBeside: () => void
    onReplace: () => void
    onCancel: () => void
  } = $props()
</script>

<div class="confirm-veil" role="presentation" onclick={(event) => event.target === event.currentTarget && onCancel()}>
  <div class="confirm" role="alertdialog" aria-modal="true"
    aria-labelledby="overwrite-title" tabindex="-1" use:modal={{ onClose: onCancel }}>
    <div class="icon" aria-hidden="true">!</div>
    <div class="copy">
      <h2 id="overwrite-title">{t('ui.this_folder_already_contains_an_export')}</h2>
      <ul>
        {#if conflict.overwritten}<li>{t('export.overwritten', { count: conflict.overwritten })}</li>{/if}
        {#if conflict.leftovers}<li>{t('export.leftovers', { count: conflict.leftovers })}</li>{/if}
      </ul>
    </div>
    <button class="btn quiet close" onclick={onCancel}
      title={t('ui.do_nothing')} aria-label={t('ui.do_nothing')}>&#x2715;</button>
    <footer>
      <button class="btn tonal beside" onclick={onBeside}
        title={t('export.beside', { name: conflict.proposed.split(/[\\/]/).pop() })}>
        <span>{t('export.beside', { name: conflict.proposed.split(/[\\/]/).pop() })}</span>
      </button>
      <button class="btn danger" onclick={onReplace}>{t('ui.replace_the_previous_export')}</button>
    </footer>
  </div>
</div>

<style>
  .confirm-veil {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: grid;
    place-items: center;
    padding: 20px;
    background: color-mix(in srgb, var(--veil) 86%, transparent);
    backdrop-filter: blur(3px);
  }

  .confirm {
    position: relative;
    width: min(560px, 100%);
    max-width: 100%;
    display: grid;
    grid-template-columns: 38px minmax(0, 1fr);
    gap: 12px 14px;
    padding: 20px;
    color: var(--ink);
    background: var(--surface-raised);
    border: 1px solid var(--border);
    border-radius: var(--radius-card);
    box-shadow: var(--shadow-float);
  }

  .icon {
    width: 36px;
    height: 36px;
    display: grid;
    place-items: center;
    color: var(--on-accent);
    background: var(--gap);
    border-radius: 50%;
    font: 700 18px var(--sans);
  }

  h2 {
    margin: 2px 36px 0 0;
    font: 600 15px var(--sans);
  }

  ul {
    margin: 8px 0 0;
    padding-left: 18px;
    color: var(--ink-2);
    font-size: 12px;
  }

  /* « Ne rien faire » est devenu la croix : ce n'est pas un choix au même
     titre que les deux autres, c'est le renoncement — il se range là où le
     reste de l'application le range. Les deux vraies options tiennent alors
     sur une ligne, et le nom du dossier proposé se tronque plutôt que
     d'élargir le panneau, comme il le faisait avec un concert daté. */
  .close {
    position: absolute;
    top: 10px;
    right: 10px;
    width: 30px;
    height: 30px;
    padding: 0;
  }

  footer {
    grid-column: 1 / -1;
    min-width: 0;
    display: flex;
    flex-wrap: nowrap;
    justify-content: flex-end;
    gap: 8px;
    padding-top: 4px;
  }

  .beside {
    min-width: 0;
    flex-shrink: 1;
  }

  .danger {
    flex: none;
  }

  .beside span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .danger {
    color: var(--on-accent);
    background: var(--gap);
    border-color: var(--gap);
  }
</style>
