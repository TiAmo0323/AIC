import assert from 'node:assert/strict'
import {setImmediate} from 'node:timers/promises'
import {createTaskPoller, errorMessage, mergeSkinCatalogs, optionsForBackend, validPersonSelection} from '../project/src/features/generationWorkflow.js'

const defaults = [{id: 'robot', label: 'Robot', outputKind: 'retarget', thumbnail: 'robot.jpg'}, {id: 'smpl', outputKind: 'smpl'}]
const catalogs = {
  intergen: {skins: [{id: 'robot', output_kind: 'retarget', available: true}, {id: 'smpl', output_kind: 'smpl', available: true}]},
  lodge: {skins: [{id: 'robot', output_kind: 'retarget', available: false, unavailable_reasons: ['Missing model']}]}
}
const merged = mergeSkinCatalogs(defaults, catalogs)
assert.equal(merged[0].thumbnail, 'robot.jpg')
assert.equal(optionsForBackend(merged, 'intergen')[0].available, true)
assert.equal(optionsForBackend(merged, 'lodge')[0].available, false)
assert.equal(optionsForBackend(merged, 'lodge')[1].available, false)
assert.equal(validPersonSelection(['robot', 'robot'], optionsForBackend(merged, 'intergen')), true)
assert.equal(validPersonSelection(['robot', 'smpl'], optionsForBackend(merged, 'intergen')), false)
assert.equal(validPersonSelection(['robot', 'robot'], optionsForBackend(merged, 'lodge')), false)
assert.equal(errorMessage({message: 'Missing resources', checks: []}), 'Missing resources')
assert.equal(errorMessage([{msg: 'Wrong input'}]), 'Wrong input')

const deferred = () => {let resolve; const promise = new Promise(done => {resolve = done}); return {resolve, promise}}
let scheduled = []
let received = []
const old = deferred()
const current = deferred()
const poller = createTaskPoller({
  fetchTask: context => context.id === 'old' ? old.promise : current.promise,
  onTask: async (task, context) => {received.push(context.id); poller.stop()},
  onFailure: () => assert.fail('Unexpected poll failure'),
  schedule: callback => {scheduled.push(callback); return callback}, cancel: () => {}
})
poller.start({id: 'old'})
assert.equal(scheduled.length, 0, 'No second request is scheduled while the first is pending')
poller.start({id: 'current'})
old.resolve({status: 'succeeded'})
await setImmediate()
assert.deepEqual(received, [], 'A stale response must not update the new task')
current.resolve({status: 'succeeded'})
await setImmediate()
assert.deepEqual(received, ['current'])
assert.equal(scheduled.length, 0, 'Terminal task must not keep polling')

let failures = 0
let attempts = 0
const interrupted = createTaskPoller({
  fetchTask: async () => {attempts++; throw new Error('offline')},
  onTask: () => assert.fail('Unexpected task'),
  onFailure: (error, context) => {failures++; assert.equal(context.taskId, 'saved-task')},
  maxFailures: 2, schedule: callback => {scheduled.push(callback); return callback}, cancel: () => {}
})
interrupted.start({taskId: 'saved-task'})
await setImmediate()
assert.equal(failures, 0)
assert.equal(scheduled.length, 1)
await scheduled.shift()()
assert.equal(attempts, 2)
assert.equal(failures, 1)
assert.equal(scheduled.length, 0)

console.log('Per-backend resource availability, pair selection, non-overlapping polling and stale-response protection: PASS')
