export function errorMessage(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(item => item.msg || String(item)).join('；')
  return detail?.message || detail?.detail || '请求失败，请稍后重试。'
}

export function mergeSkinCatalogs(defaults, catalogs) {
  const options = new Map(defaults.map(option => [option.id, {...option, backendAvailability: {}}]))
  for (const [backend, catalog] of Object.entries(catalogs)) {
    for (const skin of catalog?.skins || []) {
      const option = options.get(skin.id) || {id: skin.id, thumbnail: ''}
      Object.assign(option, {label: skin.label || skin.id, category: skin.category || '角色蒙皮',
        description: skin.description || '', outputKind: skin.output_kind, backendMode: skin.backend_mode || 'smplx'})
      option.backendAvailability ||= {}
      option.backendAvailability[backend] = {available: skin.available === true, reasons: skin.unavailable_reasons || []}
      options.set(skin.id, option)
    }
  }
  return [...options.values()]
}

export function optionsForBackend(options, backend) {
  return options.map(option => ({...option,
    available: option.backendAvailability?.[backend]?.available === true,
    unavailableReason: option.backendAvailability?.[backend]?.reasons?.join('；') || '服务未连接或资源尚未就绪。'
  }))
}

export function validPersonSelection(ids, options) {
  const selected = ids.map(id => options.find(option => option.id === id))
  return ids.length === 2 && selected.every(option => option && option.available !== false)
    && new Set(selected.map(option => option.outputKind)).size === 1
}

// Schedule only after a request and its handler finish; late responses from an
// older task must never overwrite the current task or restart its timer.
export function createTaskPoller({fetchTask, onTask, onFailure, interval = 5000,
  maxFailures = 3, schedule = setTimeout, cancel = clearTimeout}) {
  let generation = 0
  let timer = null
  let current = null
  let failures = 0
  const stop = () => {generation++; if (timer !== null) cancel(timer); timer = null; current = null}
  const poll = async token => {
    const context = current
    try {
      const task = await fetchTask(context)
      if (token !== generation) return
      failures = 0
      await onTask(task, context)
    } catch (error) {
      if (token !== generation) return
      failures++
      if (error?.response?.status === 404 || failures >= maxFailures) {
        stop()
        onFailure(error, context)
        return
      }
    }
    if (token === generation) timer = schedule(() => poll(token), interval)
  }
  return {stop, start(context) {stop(); current = context; failures = 0; poll(generation)}}
}
