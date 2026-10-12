// Execute the actual App setup and render-status handlers with a minimal Vue host.
import assert from 'node:assert/strict'
import {readFileSync, writeFileSync, unlinkSync} from 'node:fs'
import {randomUUID} from 'node:crypto'
import {fileURLToPath} from 'node:url'
import {parse, compileScript} from '../project/node_modules/@vue/compiler-sfc/dist/compiler-sfc.esm-browser.js'
import {createRenderer, nextTick} from '../project/node_modules/vue/dist/vue.runtime.esm-bundler.js'
import axios from '../project/node_modules/axios/index.js'

const appUrl = new URL('../project/src/App.vue', import.meta.url)
const scriptFile = new URL(`../project/.app-test-${randomUUID()}.mjs`, import.meta.url)
const {descriptor} = parse(readFileSync(appUrl, 'utf8'))
let compiled = compileScript(descriptor, {id: 'app-render-test'}).content
compiled = compiled.replace(/import (\w+) from ['"][^'"]+\.vue['"]/g, 'const $1 = {}')
compiled = compiled.replace(/from (['"])(\.\/[^'"]+)\1/g, (_, quote, path) => {
  const url = new URL(path.endsWith('.js') ? path : `${path}.js`, appUrl)
  return `from ${JSON.stringify(url.href)}`
}).replaceAll('import.meta.env', '({})')
writeFileSync(scriptFile, compiled)

const timers = new Map(), cancelled = []
let timerId = 0
const originalWindow = globalThis.window
globalThis.window = {location: {hostname: 'localhost', protocol: 'http:'},
  localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
  setTimeout: callback => {const id = ++timerId; timers.set(id, callback); return id},
  clearTimeout: id => {cancelled.push(id); timers.delete(id)}}
const requests = []
const originalGet = axios.get
const originalPost = axios.post
const comparisons = []
axios.post = (url, body, config) => new Promise((resolve, reject) => comparisons.push({url, body, config, resolve, reject}))
axios.get = url => {
  if (url.endsWith('/skins')) return Promise.resolve({data: {skins: []}})
  return new Promise((resolve, reject) => requests.push({url, resolve, reject}))
}
const renderer = createRenderer({
  createElement: () => ({}), createText: text => ({text}), createComment: () => ({}),
  insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
  parentNode: () => null, nextSibling: () => null
})
let app
try {
  const component = (await import(scriptFile.href)).default
  app = renderer.createApp({...component, render: () => null})
  app.mount({})
  const view = app._instance.setupState
  await nextTick()
  view.generatedTaskId = 'task-a'
  view.generatedTaskBaseUrl = 'http://localhost:8001/v1/intergen/tasks'
  view.qualityStage = 'repaired'

  const pending = view.refreshComparisonRender()
  requests.shift().resolve({data: {status: 'ready', version: 'new-render'}})
  await pending
  assert.equal(view.comparisonRenderStatus, 'ready')
  assert.ok(view.generatedVideoUrl.endsWith('/repaired?v=new-render'))

  const old = view.refreshComparisonRender()
  const request = requests.shift()
  view.clearTaskView()
  view.generatedTaskId = 'task-b'
  request.reject(new Error('old task disconnected'))
  await old
  assert.equal(view.comparisonRenderStatus, 'unavailable')
  assert.equal(view.comparisonRenderError, '')

  const queued = view.refreshComparisonRender()
  requests.shift().resolve({data: {status: 'queued'}})
  await queued
  assert.equal(timers.size, 1)
  const staleCallback = [...timers.values()][0]
  view.clearTaskView()
  assert.equal(timers.size, 0)
  await staleCallback()
  assert.equal(requests.length, 0)
  assert.ok(cancelled.length > 0)

  view.generatedVideoUrl = 'old video'
  view.qualityStage = 'repaired'
  const expired = view.refreshComparisonRender()
  requests.shift().resolve({data: {status: 'failed', error: 'motion changed'}})
  await expired
  assert.equal(view.generatedVideoUrl, '')
  assert.equal(view.comparisonRepairedUrl, '')
  assert.equal(view.comparisonRenderError, 'motion changed')

  view.baselineTaskKey = 'intergen:baseline'
  view.candidateTaskKey = 'intergen:first'
  const first = view.compareMotionLint()
  const oldComparison = comparisons.shift()
  assert.equal(oldComparison.config.timeout, 120000)
  assert.equal(view.regressionLoading, true)
  await view.compareMotionLint()
  assert.equal(comparisons.length, 0, 'Repeated clicks do not dispatch duplicate comparisons')
  view.candidateTaskKey = 'intergen:second'
  assert.equal(oldComparison.config.signal.aborted, true)
  assert.equal(view.regressionLoading, false)
  const second = view.compareMotionLint()
  const newComparison = comparisons.shift()
  oldComparison.resolve({data: {status: 'PASS', overall_change: 99}})
  await first
  assert.equal(view.regressionResult, null, 'An older selection cannot populate the current result')
  assert.equal(view.regressionLoading, true, 'An older completion cannot clear the newer request busy state')
  newComparison.resolve({data: {status: 'PASS', overall_change: 5}})
  await second
  assert.equal(view.regressionResult.overall_change, 5)
  view.baselineTaskKey = 'intergen:another'
  assert.equal(view.regressionResult, null, 'Changing either selection immediately clears its previous result')

  const clearing = view.compareMotionLint()
  const clearRequest = comparisons.shift()
  view.clearTaskView()
  clearRequest.reject(new Error('old failure'))
  await clearing
  assert.equal(view.regressionError, '')
  assert.equal(view.regressionResult, null)
  assert.equal(clearRequest.config.signal.aborted, true)
  const failed = view.compareMotionLint()
  comparisons.shift().reject({response: {data: {detail: '骨架不匹配'}}})
  await failed
  assert.match(view.regressionError, /骨架不匹配/)
  assert.equal(view.regressionLoading, false)

  const switching = view.compareMotionLint()
  const switchRequest = comparisons.shift()
  view.generatedTaskId = 'task-c'
  switchRequest.resolve({data: {status: 'PASS', overall_change: 9}})
  await switching
  assert.equal(view.regressionResult, null, 'Switching the visible task invalidates any comparison in flight')
  assert.equal(switchRequest.config.signal.aborted, true)
  assert.equal(view.regressionError, '')
  view.clearTaskView()
  view.generatedTaskId = 'import-task'
  view.importedAsset = {task_id: 'import-task', source: 'import', fps: 24, frame_count: 20}
  view.qualityReport = {tests: []}
  assert.ok(view.visibleStudioTabs.some(tab => tab.id === 'Repair'), 'Imports offer the repair workspace')
  const repairing = view.repairCurrentMotion()
  const repairRequest = comparisons.shift()
  assert.equal(repairRequest.body.source, 'import')
  assert.ok(repairRequest.url.endsWith('/repair'))
  repairRequest.resolve({data: {after: {tests: [], overall_score: 97}, gate: {status: 'FAIL'}, repair: {steps: []},
    render_status: 'skeleton_ready', artifacts: {run_id: 'first-run'}, preview: {task_id: 'import-task', source: 'import', run_id: 'first-run', fps: 24, frame_count: 20}}})
  await repairing
  assert.equal(view.qualityStage, 'repaired')
  assert.equal(view.activeSkeletonAsset.run_id, 'first-run')
  assert.equal(view.repairArtifacts.run_id, 'first-run')
  const pendingCharacter = view.refreshCharacterExport()
  const oldCharacter = requests.shift()
  view.generatedTaskId = 'different-task'
  oldCharacter.resolve({data: {status: 'ready', video_url: '/old-video'}})
  await pendingCharacter
  assert.equal(view.characterExportState.status, 'unavailable', 'A previous export cannot populate a new task')
  assert.equal(view.repairArtifacts, null)
  console.log('Actual App render recovery and comparison cancellation, stale response protection and inline failures: PASS')
} finally {
  app?.unmount()
  axios.get = originalGet
  axios.post = originalPost
  globalThis.window = originalWindow
  unlinkSync(fileURLToPath(scriptFile))
}
