// 角色单选/多选的纯函数规则，供组件和 Node 回归测试共同复用。
export const SINGLE_SKIN_SELECTION = 'single'
export const MULTI_SKIN_SELECTION = 'multi'

const uniqueSkinIds = (skinIds) => [...new Set((skinIds || []).filter(Boolean))]

export function toggleSkinSelection(currentSkinIds, skinId, selectionMode) {
  const current = uniqueSkinIds(currentSkinIds)
  if (!skinId) return current

  if (selectionMode !== MULTI_SKIN_SELECTION) {
    return [skinId]
  }

  if (!current.includes(skinId)) {
    return [...current, skinId]
  }

  if (current.length === 1) {
    return current
  }

  return current.filter((value) => value !== skinId)
}

export function normalizeSkinSelection(currentSkinIds, selectionMode) {
  const current = uniqueSkinIds(currentSkinIds)
  if (selectionMode === MULTI_SKIN_SELECTION || current.length <= 1) {
    return current
  }

  // New selections are appended in multi-select mode, so the last item best
  // represents the user's latest intent when returning to single-select mode.
  return [current[current.length - 1]]
}
