import assert from 'node:assert/strict'
import {createTaskBrowser, readActiveTask, saveActiveTask, taskIdentity, taskIsActive} from '../project/src/features/taskBrowser.js'

const row = (id, time) => ({task_id: id, created_at: time, status: 'failed'})
const calls = []
let state
const browser = createTaskBrowser({pageSize: 1, onChange: value => {state = value}, fetchPage: async (source, params) => {
  calls.push({source, ...params})
  if (source === 'lodge') throw new Error('offline')
  return {items: [row(params.offset === 0 ? 'first' : 'second', params.offset === 0 ? '2026-10-09' : '2026-10-08')],
    offset: params.offset, total: 2, has_more: params.offset === 0}
}})
await browser.refresh({status: 'failed', search: 'dance'})
assert.equal(state.items.length, 1)
assert.equal(state.items[0].source, 'intergen')
assert.ok(state.errors.lodge, 'A disconnected backend must not hide the other backend')
assert.equal(state.hasMore, true)
await browser.loadMore()
assert.deepEqual(state.items.map(task => task.task_id), ['first', 'second'])
assert.deepEqual(calls.map(call => [call.source, call.offset]), [['intergen', 0], ['lodge', 0], ['intergen', 1]])
assert.ok(calls.every(call => call.status === 'failed' && call.search === 'dance'))
assert.equal(state.total, 2)
assert.equal(state.hasMore, false)

// A refresh replaces each healthy service's snapshot; failed services keep their
// previous pages and count until a later refresh succeeds.
let offline = false
let version = 1
const snapshots = createTaskBrowser({pageSize: 1, onChange: value => {state = value}, fetchPage: async (source, params) => {
  if (offline) throw Object.assign(new Error('timeout'), source === 'lodge' ? {response: {status: 503}} : {code: 'ECONNABORTED'})
  return {items: [row(`${source}-${version}-${params.offset}`, `2026-10-0${version}`)],
    offset: params.offset, total: 2, has_more: params.offset === 0}
}})
await snapshots.refresh()
await snapshots.loadMore()
assert.equal(state.items.length, 4)
offline = true
await snapshots.refresh()
assert.equal(state.items.length, 4, 'Transient refresh failures retain previously loaded pages')
assert.equal(state.total, 4)
assert.match(state.errors.intergen, /超时.*保留/)
assert.match(state.errors.lodge, /503.*保留/)
offline = false; version = 2
await snapshots.refresh()
assert.deepEqual(state.items.map(task => task.task_id).sort(), ['intergen-2-0', 'lodge-2-0'])
assert.deepEqual(state.errors, {})
await snapshots.loadMore()
assert.ok(state.items.some(task => task.task_id === 'intergen-2-1'), 'Recovered sources resume at the refreshed page offset')
offline = true
await snapshots.refresh({search: 'another query'})
assert.equal(state.items.length, 0, 'A new search must not show cached rows for a different query')
assert.equal(state.total, 0)
assert.ok(!state.errors.lodge.includes('保留'))

const mixed = createTaskBrowser({onChange: value => {state = value}, fetchPage: async source => {
  if (offline && source === 'lodge') throw new Error('offline')
  return {items: [row(`${source}-${version}`, 'now')], offset: 0, total: 1, has_more: false}
}})
offline = false
await mixed.refresh()
offline = true; version = 3
await mixed.refresh()
assert.deepEqual(state.items.map(task => task.task_id).sort(), ['intergen-3', 'lodge-2'])
assert.equal(state.total, 2)

const synchronousFailure = createTaskBrowser({onChange: value => {state = value}, fetchPage: () => {throw new Error('bad configuration')}})
await synchronousFailure.refresh({source: 'intergen'})
assert.equal(state.loading, false, 'A synchronous transport failure must not leave the panel loading forever')
assert.ok(state.errors.intergen)

const pending = []
const racing = createTaskBrowser({onChange: value => {state = value}, fetchPage: (source, params) => new Promise(resolve => pending.push({resolve, params}))})
const older = racing.refresh({source: 'intergen', search: 'old'})
const newer = racing.refresh({source: 'intergen', search: 'new'})
await Promise.resolve()
assert.deepEqual(pending.slice(0, 2).map(request => request.params.search), ['old', 'new'])
pending[1].resolve({items: [row('new', 'now')], total: 1, offset: 0, has_more: false})
await newer
pending[0].resolve({items: [row('old', 'before')], total: 1, offset: 0, has_more: false})
await older
assert.equal(state.items[0].task_id, 'new', 'An earlier search must not overwrite the current search')
let changes = 0
const disposed = createTaskBrowser({onChange: () => {changes++}, fetchPage: () => new Promise(resolve => pending.push({resolve}))})
const late = disposed.refresh({source: 'lodge'})
await Promise.resolve()
disposed.dispose()
pending.at(-1).resolve({items: [], total: 0, offset: 0, has_more: false})
await late
assert.equal(changes, 1, 'Closing the panel discards late responses')

const memory = new Map()
const storage = {getItem: key => memory.get(key), setItem: (key, value) => memory.set(key, value), removeItem: key => memory.delete(key)}
const context = {source: 'intergen', taskId: '11111111-1111-4111-8111-111111111111', baseUrl: 'https://old-service', requestedSkinIds: ['robot'], personSkinIds: ['robot', 'robot']}
saveActiveTask(storage, context)
const restored = readActiveTask(storage)
assert.equal(restored.taskId, context.taskId)
assert.deepEqual(restored.personSkinIds, ['robot', 'robot'])
assert.equal(restored.baseUrl, undefined, 'Use current service configuration after refresh')
saveActiveTask(storage, {source: 'bad', taskId: '../../outside'})
assert.equal(readActiveTask(storage), null)
saveActiveTask(storage, null)
assert.equal(readActiveTask(storage), null)
const unavailableStorage = {setItem: () => {throw new Error('disabled')}, getItem: () => {throw new Error('disabled')}, removeItem: () => {throw new Error('disabled')}}
assert.doesNotThrow(() => saveActiveTask(unavailableStorage, context))
assert.equal(readActiveTask(unavailableStorage), null)
assert.equal(taskIdentity({source: 'lodge', task_id: 'same'}), 'lodge:same')
assert.equal(taskIsActive({status: 'processing'}), true)
assert.equal(taskIsActive({status: 'failed'}), false)
console.log('Task pagination, partial service failure, stale search protection and refresh recovery: PASS')
