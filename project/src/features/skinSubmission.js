// 根据人物 A/B 的角色选择构造生产文本请求，并在前端阻止 SMPL/FBX 混合渲染。
export function buildIntergenSkinPayload(text, personSkinIds, options) {
  const [personASkinId, personBSkinId] = personSkinIds
  const optionById = new Map(options.map((option) => [option.id, option]))
  const personOptions = [optionById.get(personASkinId), optionById.get(personBSkinId)]

  if (!String(text || '').trim()) throw new Error('Text prompt is required')
  if (personOptions.some((option) => !option)) {
    throw new Error('Both InterGen persons must use registered skins')
  }
  const outputKinds = new Set(personOptions.map((option) => option.outputKind))
  if (outputKinds.size !== 1) {
    throw new Error('InterGen cannot mix SMPL and FBX person skins in one video')
  }

  const skinIds = [...new Set([personASkinId, personBSkinId])]
  const retargetEnabled = personOptions[0].outputKind === 'retarget'
  return {
    text,
    person_a_skin_id: personASkinId,
    person_b_skin_id: personBSkinId,
    skin_ids: skinIds,
    skin_id: personASkinId,
    retarget_enabled: retargetEnabled
  }
}
