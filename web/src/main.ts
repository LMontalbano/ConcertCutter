import './tokens.css'
import './fonts.css'
import { mount } from 'svelte'
import App from './App.svelte'
import { api } from './lib/api'
import { applyLanguage, t } from './lib/i18n.svelte'
import { session } from './lib/session.svelte'

async function start() {
  try {
    applyLanguage(await api.preferences())
  } catch {
    applyLanguage({ language: 'auto', effectiveLanguage: 'en' })
    session.note(t('preferences.load_failed'))
  }
  return mount(App, { target: document.getElementById('app')! })
}

export default start()
