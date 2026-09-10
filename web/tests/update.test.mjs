import assert from 'node:assert/strict'
import { afterEach, beforeEach, test } from 'node:test'

globalThis.document = { querySelector: () => null, documentElement: { dataset: {} } }
globalThis.localStorage = { getItem: () => null, setItem: () => {} }
globalThis.window = {
  clearTimeout,
  setTimeout,
}

const { api, ApiError } = await import('../src/lib/api.ts')
const { session } = await import('../src/lib/session.svelte.ts')

const originals = {}

beforeEach(() => {
  for (const name of ['checkUpdate', 'downloadUpdate', 'restartForUpdate', 'openUpdateSite']) {
    originals[name] = api[name]
  }
  session.update = null
  session.updateError = ''
  session.updateDismissed = false
  session.job = null
})

afterEach(() => {
  Object.assign(api, originals)
})

test('an automatic check stays silent offline while a manual check reports the error', async () => {
  api.checkUpdate = async () => { throw new ApiError('offline', 500) }
  await session.checkUpdate(false)
  assert.equal(session.updateError, '')
  await session.checkUpdate(true)
  assert.equal(session.updateError, 'offline')
})

test('an available update remains visible until dismissed for this launch', async () => {
  api.checkUpdate = async () => ({
    status: 'available', currentVersion: '3.3.0', latestVersion: 'v3.3.1',
    size: 42, canAutoUpdate: true,
  })
  await session.checkUpdate(false)
  assert.equal(session.update.latestVersion, 'v3.3.1')
  assert.equal(session.updateDismissed, false)
  session.dismissUpdate()
  assert.equal(session.updateDismissed, true)
})

test('installing follows the verified download then requests the restart', async () => {
  const calls = []
  session.update = {
    status: 'available', currentVersion: '3.3.0', latestVersion: 'v3.3.1',
    size: 42, canAutoUpdate: true,
  }
  api.downloadUpdate = async () => ({
    id: 'update', kind: 'update', phase: 'done', done: 42, total: 42,
    state: 'done', result: { ready: true }, error: '',
  })
  api.restartForUpdate = async () => (calls.push('restart'), { restarting: true })
  await session.installUpdate()
  assert.deepEqual(calls, ['restart'])
  assert.equal(session.updateError, '')
})

test('an installation failure keeps the banner and offers the manual website', async () => {
  const calls = []
  session.update = {
    status: 'available', currentVersion: '3.3.0', latestVersion: 'v3.3.1',
    size: 42, canAutoUpdate: true,
  }
  api.downloadUpdate = async () => { throw new ApiError('invalid checksum', 500) }
  api.openUpdateSite = async () => (calls.push('site'), { opened: true })
  await session.installUpdate()
  assert.equal(session.updateError, 'invalid checksum')
  await session.openUpdateSite()
  assert.deepEqual(calls, ['site'])
})
