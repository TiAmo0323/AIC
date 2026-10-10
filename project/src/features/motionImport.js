export function validateMotionFiles(files) {
  if (!files.length || files.length > 2) return '请选择一个动作文件，或两个同步的关节 NPY / BVH 文件。'
  const extensions = files.map(file => file.name.split('.').at(-1).toLowerCase())
  if (extensions.some(extension => !['npy', 'bvh'].includes(extension)) || new Set(extensions).size !== 1) return '只支持 NPY 或 BVH，双人文件需要使用同一种格式。'
  if (files.some(file => file.size === 0)) return '动作文件为空，请重新选择。'
  if (files.reduce((total, file) => total + file.size, 0) > 32 * 1024 * 1024) return '动作文件合计不能超过 32 MB。'
  return ''
}

export function buildImportForm(files, {fps = 30, unitScale = 1, upAxis = 1, jointMapping = '{}'} = {}) {
  const error = validateMotionFiles(files)
  if (error) throw new Error(error)
  const form = new FormData()
  files.forEach(file => form.append('files', file))
  const bvh = files[0].name.toLowerCase().endsWith('.bvh')
  if (!bvh && (!Number.isFinite(Number(fps)) || Number(fps) <= 0 || Number(fps) > 240)) throw new Error('帧率需要在 0 到 240 FPS 之间。')
  let mapping = {}
  if (bvh) {
    try {mapping = JSON.parse(jointMapping || '{}')} catch {throw new Error('关节映射需要是有效的 JSON 名称对应表。')}
    if (!mapping || Array.isArray(mapping) || typeof mapping !== 'object' || Object.values(mapping).some(value => typeof value !== 'string' || !value)) throw new Error('映射格式应为 {"原关节名": "标准关节名"}。')
  }
  form.append('fps', bvh ? '30' : String(fps))
  form.append('unit_scale', bvh ? String(unitScale) : '1')
  form.append('up_axis', bvh ? String(upAxis) : '1')
  form.append('joint_mapping', JSON.stringify(mapping))
  return form
}

export const previewFrame = (seconds, fps, frameCount) => Math.max(0, Math.min(frameCount - 1, Math.round(seconds * fps)))

export function skeletonProjection(point, bounds, upAxis, yaw = .35) {
  const horizontal = [0, 1, 2].filter(axis => axis !== upAxis)
  const centered = point.map((value, axis) => value - (bounds[0][axis] + bounds[1][axis]) / 2)
  const x = centered[horizontal[0]], z = centered[horizontal[1]]
  return [x * Math.cos(yaw) + z * Math.sin(yaw), centered[upAxis] - (z * Math.cos(yaw) - x * Math.sin(yaw)) * .16]
}

export function createPreviewLoader(fetchFrames, blockSize = 120) {
  let generation = 0, key
  const cache = new Map(), pending = new Map()
  return {
    reset(nextKey) {generation++; key = nextKey; cache.clear(); pending.clear()},
    async load(frame) {
      const start = Math.floor(frame / blockSize) * blockSize
      if (cache.has(start)) return cache.get(start)
      if (pending.has(start)) return pending.get(start)
      const token = generation
      const request = (async () => {
        try {
          const block = await fetchFrames(key, start, blockSize)
          if (token !== generation) return null
          cache.set(start, block)
          if (cache.size > 8) cache.delete(cache.keys().next().value)
          return block
        } finally {if (token === generation) pending.delete(start)}
      })()
      pending.set(start, request)
      return request
    }
  }
}
