export const taskIdentity = task => `${task.source}:${task.task_id}`
export const taskIsActive = task => ['queued', 'running', 'processing'].includes(task.status)

// Each backend has its own offset. Keep successful pages when the other service
// is offline, and discard responses from a previous search or disposed panel.
export function createTaskBrowser({fetchPage, onChange, pageSize = 10}) {
  let epoch = 0
  let filters = null
  let pages = {}
  let items = []
  let errors = {}
  let loading = false
  const publish = () => onChange({items: [...items], errors: {...errors}, loading,
    total: Object.values(pages).reduce((sum, page) => sum + page.total, 0),
    hasMore: Object.values(pages).some(page => page.hasMore)})
  const load = async (token, replace = false) => {
    loading = true
    publish()
    const sources = Object.keys(pages).filter(source => replace || pages[source].hasMore)
    const results = await Promise.allSettled(sources.map(source => {
      const params = {status: filters.status, search: filters.search, offset: replace ? 0 : pages[source].offset, limit: pageSize}
      return Promise.resolve().then(() => fetchPage(source, params))
    }))
    if (token !== epoch) return
    results.forEach((result, index) => {
      const source = sources[index]
      if (result.status === 'fulfilled') {
        const page = result.value
        pages[source] = {offset: page.offset + page.items.length, total: page.total, hasMore: page.has_more}
        const retained = replace ? items.filter(task => task.source !== source) : items
        const merged = new Map(retained.map(task => [taskIdentity(task), task]))
        page.items.forEach(task => merged.set(taskIdentity({...task, source}), {...task, source}))
        items = [...merged.values()]
        delete errors[source]
      } else {
        const error = result.reason
        const reason = error?.response?.status ? `请求失败（HTTP ${error.response.status}）`
          : ['ECONNABORTED', 'ETIMEDOUT'].includes(error?.code) ? '请求超时' : '无法连接'
        const retained = items.some(task => task.source === source) ? '已保留此前读取的任务。' : ''
        errors[source] = `${source === 'intergen' ? '文字生成服务' : '音乐生成服务'}${reason}，点击刷新后重试。${retained}`
        pages[source].hasMore = false
      }
    })
    items.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '') || taskIdentity(b).localeCompare(taskIdentity(a)))
    loading = false
    publish()
  }
  return {
    refresh(nextFilters = {}) {
      const next = {source: nextFilters.source || '', status: nextFilters.status || '', search: (nextFilters.search || '').trim()}
      const sameFilters = filters && Object.keys(next).every(key => filters[key] === next[key])
      filters = next
      pages = Object.fromEntries((filters.source ? [filters.source] : ['intergen', 'lodge'])
        .map(source => [source, sameFilters ? {...pages[source]} : {offset: 0, total: 0, hasMore: true}]))
      if (!sameFilters) {items = []; errors = {}}
      return load(++epoch, true)
    },
    loadMore() {if (!loading) return load(epoch)},
    dispose() {epoch++}
  }
}

const STORAGE_KEY = 'motionlint-active-task-v1'
export function saveActiveTask(storage, context) {
  try {
    if (!context) storage.removeItem(STORAGE_KEY)
    else storage.setItem(STORAGE_KEY, JSON.stringify({source: context.source, taskId: context.taskId,
      requestedSkinIds: context.requestedSkinIds || [], personSkinIds: context.personSkinIds || []}))
  } catch { /* An unavailable storage must not prevent generation. */ }
}
export function readActiveTask(storage) {
  try {
    const context = JSON.parse(storage.getItem(STORAGE_KEY) || 'null')
    if (!['intergen', 'lodge', 'import'].includes(context?.source) || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(context.taskId)) return null
    return {...context, requestedSkinIds: Array.isArray(context.requestedSkinIds) ? context.requestedSkinIds.filter(id => typeof id === 'string') : [],
      personSkinIds: Array.isArray(context.personSkinIds) ? context.personSkinIds.filter(id => typeof id === 'string') : []}
  } catch {return null}
}
