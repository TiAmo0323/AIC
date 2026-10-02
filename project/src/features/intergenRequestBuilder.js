// 将旧版生成模式表单整理为 InterGen API 请求；仅影视模式附带重定向参数。
export function buildIntergenTextPayload(options) {
  const {
    text,
    numSamples,
    mode,
    retargetFeatureEnabled,
    targetCharacterId,
    mappingProfile,
    engine,
    strict
  } = options

  const payload = {
    text,
    num_samples: numSamples
  }

  const shouldRetarget = mode === 'cinematic' && Boolean(retargetFeatureEnabled)
  payload.retarget_enabled = shouldRetarget

  if (shouldRetarget) {
    payload.target_character_id = targetCharacterId
    payload.retarget_mapping_profile = mappingProfile
    payload.retarget_engine = engine
    payload.retarget_strict = strict
  }

  return payload
}
