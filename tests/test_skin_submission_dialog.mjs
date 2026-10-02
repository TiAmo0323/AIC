// 前端提交契约回归：验证人物 A/B 载荷、同类输出约束和选择弹窗静态结构。
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { skinOptions } from '../project/src/config/skinOptions.js'
import { buildIntergenSkinPayload } from '../project/src/features/skinSubmission.js'

const distinctPair = buildIntergenSkinPayload(
  'Two people dance.',
  ['aj', 'ch09_nonpbr'],
  skinOptions
)
assert.equal(distinctPair.person_a_skin_id, 'aj')
assert.equal(distinctPair.person_b_skin_id, 'ch09_nonpbr')
assert.deepEqual(distinctPair.skin_ids, ['aj', 'ch09_nonpbr'])
assert.equal(distinctPair.retarget_enabled, true)

const samePair = buildIntergenSkinPayload(
  'Two people dance.',
  ['robot', 'robot'],
  skinOptions
)
assert.deepEqual(samePair.skin_ids, ['robot'])
const smplPair = buildIntergenSkinPayload(
  'Two people dance.',
  ['smpl', 'smpl'],
  skinOptions
)
assert.equal(smplPair.person_a_skin_id, 'smpl')
assert.equal(smplPair.person_b_skin_id, 'smpl')
assert.deepEqual(smplPair.skin_ids, ['smpl'])
assert.equal(smplPair.retarget_enabled, false)
assert.throws(
  () => buildIntergenSkinPayload('Two people dance.', ['smpl', 'robot'], skinOptions),
  /cannot mix SMPL and FBX/
)

const appSource = readFileSync(new URL('../project/src/App.vue', import.meta.url), 'utf8')
const catalogSource = readFileSync(new URL('../project/src/components/SkinCatalogBar.vue', import.meta.url), 'utf8')
const dialogSource = readFileSync(new URL('../project/src/components/SkinSelectionDialog.vue', import.meta.url), 'utf8')
assert.match(appSource, /<SkinCatalogBar :options="skinOptions"/)
assert.doesNotMatch(appSource, /<SkinSelector/)
assert.match(appSource, /person_a_skin_id|buildIntergenSkinPayload/)
assert.match(dialogSource, /人物 A/)
assert.match(dialogSource, /人物 B/)
assert.match(dialogSource, /MULTI_SKIN_SELECTION/)
assert.match(dialogSource, /v-for="option in textOptions"/)
assert.match(dialogSource, /标准人体可以用于文本任务/)
assert.match(dialogSource, /!textSelectionValid/)
assert.match(dialogSource, /window\.alert\('标准人体暂不能与其他角色混合渲染/)
assert.match(catalogSource, /支持的角色类型/)
assert.match(catalogSource, /animation: catalog-scroll/)
assert.match(catalogSource, /\.skin-catalog-marquee:hover \.skin-catalog-track/)
assert.match(catalogSource, /openPreview\(option, \$event\)/)
assert.match(catalogSource, /再次点击返回主界面/)

console.log(JSON.stringify({
  static_catalog_without_selection: true,
  text_dialog_person_a_skin_id: distinctPair.person_a_skin_id,
  text_dialog_person_b_skin_id: distinctPair.person_b_skin_id,
  duplicate_pair_deduplicates_legacy_skin_ids: samePair.skin_ids,
  smpl_pair_skin_ids: smplPair.skin_ids,
  smpl_pair_retarget_enabled: smplPair.retarget_enabled,
  mixed_smpl_fbx_blocked: true,
  mixed_smpl_fbx_alert_present: true,
  audio_dialog_keeps_single_multi_logic: true,
  smpl_included_in_text_person_options: true,
  character_catalog_auto_scroll: true,
  character_preview_click_toggle: true
}, null, 2))
