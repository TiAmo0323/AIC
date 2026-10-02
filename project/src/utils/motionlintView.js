export function timelineSegments(issues = []) {
  const groups = new Map()
  for (const issue of issues) {
    const key = `${issue.test_name}:${issue.severity}:${issue.actor_id ?? 'none'}:${issue.other_actor_id ?? 'none'}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(issue)
  }
  const result = []
  for (const [key, values] of groups) {
    let merged
    for (const issue of [...values].sort((a, b) => a.start_frame - b.start_frame || a.end_frame - b.end_frame)) {
      if (merged && issue.start_frame <= merged.end_frame + 1) {
        merged.end_frame = Math.max(merged.end_frame, issue.end_frame)
        merged.count += 1
      } else {
        merged = { key: `${key}:${issue.start_frame}`, test_name: issue.test_name, severity: issue.severity,
          start_frame: issue.start_frame, end_frame: issue.end_frame, count: 1, issue }
        result.push(merged)
      }
    }
  }
  return result.sort((a, b) => a.start_frame - b.start_frame)
}

export function filterIssues(issues, test = '', severity = '') {
  return issues.filter(issue => (!test || issue.test_name === test) && (!severity || issue.severity === severity))
}
