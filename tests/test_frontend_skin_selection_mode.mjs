// 前端角色选择纯函数回归：验证默认单选、显式多选和注册角色不发生退化。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  MULTI_SKIN_SELECTION,
  SINGLE_SKIN_SELECTION,
  normalizeSkinSelection,
  toggleSkinSelection
} from '../project/src/config/skinSelection.js'
import { skinOptions } from '../project/src/config/skinOptions.js'

const expectedSkinIds = [
  'smpl',
  'kenney_cc0',
  'nailong',
  'robot',
  'aj',
  'ch09_nonpbr',
  'ch46_nonpbr',
  'y_bot'
]

const expectedSkinLabels = [
  '标准人体',
  '开源卡通角色',
  '奶龙',
  '粉色机器人',
  '街头少年',
  '绿衣少年',
  '动漫少女',
  '蓝色机器人'
]

const backendSkinCatalog = JSON.parse(
  readFileSync(new URL('../config/skin_catalog.json', import.meta.url), 'utf8')
)

assert.deepEqual(
  skinOptions.map((skin) => skin.id),
  expectedSkinIds,
  'frontend fallback catalog must stay aligned with the backend skin catalog'
)

assert.deepEqual(
  skinOptions.map((skin) => skin.thumbnail),
  expectedSkinIds.map((skinId) => (
    skinId === 'kenney_cc0' ? '/local-intergen-kenney.png' : skinId === 'nailong' ? '/skin-thumbnails/local-character.svg' : `/skin-thumbnails/${skinId}.jpg`
  )),
  'every registered skin must have a stable dropdown thumbnail URL'
)

assert.deepEqual(
  skinOptions.map((skin) => skin.label),
  expectedSkinLabels,
  'registered skins must expose user-friendly labels instead of asset filenames'
)

assert.deepEqual(
  backendSkinCatalog.skins.map(({ id, label }) => ({ id, label })),
  skinOptions.map(({ id, label }) => ({ id, label })),
  'backend and frontend skin catalogs must expose the same user-facing labels'
)

assert.deepEqual(
  toggleSkinSelection(['smpl'], 'robot', SINGLE_SKIN_SELECTION),
  ['robot'],
  'single-select must replace the default SMPL selection'
)
assert.deepEqual(
  toggleSkinSelection(['robot'], 'robot', SINGLE_SKIN_SELECTION),
  ['robot'],
  'single-select must never clear the only selected skin'
)
assert.deepEqual(
  toggleSkinSelection(['smpl'], 'robot', MULTI_SKIN_SELECTION),
  ['smpl', 'robot'],
  'multi-select must append a newly selected skin'
)
assert.deepEqual(
  toggleSkinSelection(['smpl', 'robot'], 'smpl', MULTI_SKIN_SELECTION),
  ['robot'],
  'multi-select must allow removing one of multiple skins'
)
assert.deepEqual(
  toggleSkinSelection(['robot'], 'robot', MULTI_SKIN_SELECTION),
  ['robot'],
  'multi-select must retain at least one skin'
)
assert.deepEqual(
  normalizeSkinSelection(['smpl', 'robot'], SINGLE_SKIN_SELECTION),
  ['robot'],
  'returning to single-select must retain the most recently added skin'
)
assert.deepEqual(
  normalizeSkinSelection(['smpl', 'robot'], MULTI_SKIN_SELECTION),
  ['smpl', 'robot'],
  'switching to multi-select must preserve the current selection'
)
assert.deepEqual(
  toggleSkinSelection(['robot'], 'future-skin', MULTI_SKIN_SELECTION),
  ['robot', 'future-skin'],
  'selection logic must remain data-driven for future skins'
)

console.log(JSON.stringify({
  default_mode: SINGLE_SKIN_SELECTION,
  single_robot_click: ['robot'],
  multi_robot_click: ['smpl', 'robot'],
  multi_to_single_keeps_latest: ['robot'],
  future_skin_supported: true,
  registered_skin_ids: expectedSkinIds,
  registered_skin_labels: expectedSkinLabels
}, null, 2))
