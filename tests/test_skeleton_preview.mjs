// Exercise the actual Vue component with a canvas host and stubbed frame API.
import assert from 'node:assert/strict'
import {readFileSync, writeFileSync, unlinkSync} from 'node:fs'
import {createRequire} from 'node:module'
import {pathToFileURL, fileURLToPath} from 'node:url'
import path from 'node:path'
import {randomUUID} from 'node:crypto'
import {setImmediate} from 'node:timers/promises'

const project = fileURLToPath(new URL('../project/', import.meta.url))
const require = createRequire(path.join(project, 'package.json'))
const {parse, compileScript, compileTemplate} = require('@vue/compiler-sfc')
const {createRenderer, defineComponent, h, ref, nextTick} = require('vue')
const axios = (await import(pathToFileURL(path.join(project, 'node_modules/axios/index.js')))).default
const sourcePath = path.join(project, 'src/components/SkeletonPreview.vue')
const {descriptor} = parse(readFileSync(sourcePath, 'utf8'))
const script = compileScript(descriptor, {id: 'preview-test'})
const template = compileTemplate({source: descriptor.template.content, id: 'preview-test', compilerOptions: {bindingMetadata: script.bindings}})
assert.equal(template.errors.length, 0)
const compiled = script.content.replace(/from (['"])(\.[^'"]+)\1/g, (_, quote, relative) => `from ${JSON.stringify(pathToFileURL(path.resolve(path.dirname(sourcePath), relative)).href)}`)
  .replace('export default', 'const Component =') + '\n' + template.code.replace('export function render', 'function render') + '\nComponent.render = render; export default Component;\n'
const temporary = path.join(project, `.preview-test-${randomUUID()}.mjs`)
let app
const requests = [], times = [], draws = []
const nodes = []
const originalGet = axios.get
let oldResolve
const makeBlock = (start, count, shift = 0) => ({start, positions: Array.from({length: Math.min(count, 241 - start)}, (_, index) =>
  [[[shift + (start + index) / 1000, 0, 0], [shift + (start + index) / 1000, 1, 0]]]),
  parents: [-1, 0], bounds: [[0, 0, 0], [1, 1, 1]], up_axis: 1})
axios.get = async (url, {params}) => {
  requests.push({url, ...params})
  if (url.includes('/first/') && params.start === 240) return new Promise(resolve => {oldResolve = resolve})
  return {data: makeBlock(params.start, params.count, url.includes('/second/') ? 1 : 0)}
}
const scheduled = new Map()
let animationId = 0
globalThis.requestAnimationFrame = callback => {scheduled.set(++animationId, callback); return animationId}
globalThis.cancelAnimationFrame = id => scheduled.delete(id)
globalThis.document = {activeElement: null}
const context = {fillRect() {draws.length = 0}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, fill() {}, arc(x, y) {draws.push([x, y])}}
const node = tag => {const value = {tag, tagName: tag.toUpperCase(), children: [], props: {}, parent: null, getContext: () => context,
  addEventListener() {}, removeEventListener() {}, getAttribute(key) {return this.props[key]}}; nodes.push(value); return value}
const renderer = createRenderer({
  createElement: node, createText: text => ({text}), createComment: text => ({text}),
  setText: (element, text) => {element.text = text}, setElementText: (element, text) => {element.text = text; element.children = []},
  patchProp: (element, key, previous, next) => {element.props[key] = next; if (key === 'type' || key === 'value') element[key] = next},
  insert(element, parent, anchor) {
    if (element.parent) element.parent.children.splice(element.parent.children.indexOf(element), 1)
    element.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(element); else parent.children.splice(index, 0, element)
  },
  remove(element) {if (element.parent) element.parent.children.splice(element.parent.children.indexOf(element), 1)},
  parentNode: element => element.parent, nextSibling: element => element.parent?.children[element.parent.children.indexOf(element) + 1]
})
try {
  writeFileSync(temporary, compiled)
  const Component = (await import(pathToFileURL(temporary))).default
  const asset = ref({task_id: 'first', fps: 24, frame_count: 241})
  const preview = ref()
  app = renderer.createApp(defineComponent({setup: () => () => h(Component, {ref: preview, asset: asset.value,
    apiBase: 'http://localhost:8003', playback: {speed: 1}, onTimeupdate: value => times.push(value)})}))
  app.mount(node('root'))
  await setImmediate()
  assert.equal(draws.length, 2, 'Mounted component draws the imported joints')
  const originalPoint = [...draws[0]]
  await preview.value.seek(7 / 24)
  assert.equal(times.at(-1), 7 / 24)
  assert.notDeepEqual(draws[0], originalPoint, 'Seeking changes the drawn pose')
  assert.equal(requests.length, 1, 'The component reuses its first frame block')
  await preview.value.seek(121 / 24)
  assert.equal(times.at(-1), 121 / 24)
  assert.equal(requests[1].start, 120)
  const oldSeek = preview.value.seek(240 / 24)
  await nextTick()
  asset.value = {task_id: 'second', fps: 24, frame_count: 241}
  await nextTick()
  await setImmediate()
  assert.equal(times.at(-1), 0)
  oldResolve({data: makeBlock(240, 1)})
  await oldSeek
  assert.equal(times.at(-1), 0, 'A late response cannot seek the newly selected motion')
  app.unmount(); app = null
  assert.equal(scheduled.size, 0, 'Closing the preview cancels its animation')
  console.log('Vue skeleton preview mounting, pose drawing, exact seeking and stale-response protection: PASS')
} finally {
  app?.unmount()
  axios.get = originalGet
  unlinkSync(temporary)
}
