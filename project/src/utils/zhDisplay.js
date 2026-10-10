// Display-only translations. API keys, status values and downloaded reports stay unchanged.
export const qualityTestLabels = {
  temporal_continuity: '动作连续性', skeleton_integrity: '骨架完整性',
  foot_sliding: '脚部滑动', ground_contact: '地面接触',
  collision: '骨架近距风险', motion_jerk: '运动平滑度（加加速度）'
}

const statuses = {
  PASS: '通过', FAIL: '未通过', WARN: '需关注',
  REGRESSION: '出现退步', 'REGRESSION DETECTED': '检测到质量退步',
  IMPROVED: '有所改善', UNCHANGED: '无变化',
  INCOMPARABLE: '无法比较', 'COMPARISON INCOMPLETE': '比较信息不足',
  queued: '排队中', running: '处理中', processing: '处理中', ready: '已就绪', succeeded: '已完成',
  failed: '失败', unavailable: '暂无结果', unchanged: '无变化',
  accepted: '已接受', rejected: '已拒绝', unsupported: '暂不支持修复',
  no_op: '无需修复', skipped: '已跳过', pending: '等待中',
  stale: '动作已更新，请重新导出', critical: '严重', high: '高', medium: '中', low: '低'
}
export const statusLabel = value => statuses[value] || (value ? `未知状态（${value}）` : '尚未评估')
const repairs = {
  foot_lock: '脚部接触锁定', seam_repair: '片段衔接修复',
  bone_length_projection: '骨骼长度校正', inter_actor_separation: '人物间距调整',
  collision_repair: '近距风险修复'
}
export const repairLabel = value => repairs[value] || `修复步骤（${value}）`

const parameters = {
  root_step_m: '根节点单帧位移（米）', root_acceleration_m_s2: '根节点加速度（米/秒²）',
  angular_step_deg: '单帧旋转角度（度）', chunk_frames: '片段长度（帧）',
  bone_length_variation_ratio: '骨长变化比例', joint_collapse_m: '关节塌缩距离（米）',
  use_explicit_floor: '使用指定地面高度', contact_height_m: '接触高度（米）',
  horizontal_speed_m_s: '水平速度（米/秒）', vertical_speed_m_s: '竖直速度（米/秒）',
  min_contact_frames: '最短接触时长（帧）', flag_unconfirmed_airborne: '标记未确认的腾空状态',
  penetration_m: '地面穿透阈值（米）', floating_m: '悬空高度阈值（米）',
  extended_inter_actor_checks: '扩展人物间近距检查', wrist_head_clearance_m: '手腕与头部安全距离（米）',
  forearm_head_clearance_m: '前臂与头部安全距离（米）', head_head_clearance_m: '头部间安全距离（米）',
  torso_torso_clearance_m: '躯干间安全距离（米）', joint_jerk_m_s3: '关节加加速度（米/秒³）',
  angular_acceleration_deg_s2: '角加速度（度/秒²）',
  nonfinite_position: '无效关节坐标', ground_penetration_m: '地面穿透深度（米）',
  floating_height_m: '脚部悬空高度（米）', wrist_head_distance_m: '手腕与头部距离（米）',
  forearm_head_distance_m: '前臂与头部距离（米）', head_head_distance_m: '头部间距离（米）',
  torso_torso_distance_m: '躯干间距离（米）', hand_head_distance_m: '手与头部距离（米）',
  hand_torso_distance_m: '手与躯干距离（米）'
}
export const parameterLabel = value => parameters[value] || `参数（${value}）`
export const parameterValue = value => typeof value === 'boolean' ? (value ? '开启' : '关闭') : value

const messages = {
  'Root trajectory jump': '根节点运动轨迹突跳', 'Joint rotation jump': '关节旋转突跳',
  'Bone length changed': '骨骼长度发生变化', 'Joint is collapsed onto its parent': '关节与父关节重合或距离过近',
  'Joint has NaN or Inf': '关节坐标包含无效数值（NaN 或 Inf）',
  'Foot slides during contact': '脚部接触地面时发生滑动',
  'Foot penetrates the fitted floor': '脚部穿入估算地面',
  'Contact foot floats above the fitted floor': '应接触地面的脚部悬空',
  'Joint position jerk': '关节位置的加加速度过大', 'Joint rotation acceleration spike': '关节旋转加速度突增',
  "Other actor's hand is near head": '另一人物的手与头部距离过近',
  "Hand is near the other actor's torso segment": '手与另一人物的躯干距离过近',
  'No global joints': '缺少全局关节位置', 'No global joint positions': '缺少全局关节位置',
  'No foot joint mapping': '缺少脚部关节映射',
  'No compatible skeleton parent mapping': '缺少匹配的骨架父子关系',
  'No root or rotation data': '缺少根节点或旋转数据', 'Need at least two frames': '至少需要两帧动作',
  'Need at least two frames with global positions': '至少需要两帧全局关节位置',
  'Need four position frames or three rotation frames': '至少需要四帧位置或三帧旋转数据',
  'Need at least three rotations or four position frames': '至少需要三帧旋转或四帧位置数据',
  'No credible support intervals; foot sliding could not be evaluated': '未找到可信的脚部支撑区间，无法评估脚滑',
  'Missing canonical head/arm mapping; collision coverage unavailable': '缺少标准头部或手臂映射，无法评估近距风险',
  'No supported repairable issue': '未发现支持自动修复的问题',
  'Cumulative foot movement exceeds bound': '脚部累计移动超过允许范围',
  'Total movement from original input exceeds configured bound': '相对原始动作的总位移超过配置上限',
  'Fixed-length projection exceeds movement bound': '骨长校正所需位移超过允许范围',
  'Candidate did not improve within the movement, bone, regression and support constraints': '候选修复未能在位移、骨长、回归和支撑约束内取得改善',
  'Task queued': '任务已排队', 'Task is running': '任务处理中', 'Task completed': '任务已完成',
  'Translating prompt...': '正在翻译动作描述…', 'Generating motion...': '正在生成动作…',
  'Preparing audio features': '正在准备音频特征', 'Extracting audio features to npy': '正在提取音频特征',
  'Preparing feature npy': '正在准备特征数据', 'Running infer_lodge.py': '正在生成舞蹈动作（LODGE）',
  'Inference done, rendering mp4': '动作生成完成，正在渲染视频',
  'Rendering uploaded npy': '正在渲染上传的动作', 'Exporting BVH from generated npy': '正在导出动作骨架（BVH）',
  'Running Blender/Rokoko retarget': '正在重定向角色并渲染（Blender/Rokoko）',
  'Requested retarget skin completed': '所选角色视频已完成', 'Rokoko retarget completed': '角色重定向已完成',
  'Feature extraction failed': '音频特征提取失败', 'Waiting for rendered video': '正在等待渲染视频',
  'Render attempt failed, retrying with fallback settings': '渲染未成功，正在使用备用配置重试',
  'Mesh rendering failed after all attempts': '所有重试均未成功，人体网格渲染失败',
  'Retrying retarget from existing joints...': '正在使用已有动作重新进行角色重定向…',
  'Retarget retry queued': '重定向重试已排队', 'Retarget retry completed': '重定向重试已完成',
  'Retarget retry failed': '重定向重试失败', 'Retarget disabled': '未启用角色重定向',
  'Blender/Rokoko retarget failed': '角色重定向或渲染失败（Blender/Rokoko）',
  'Retarget skipped, no raw joints files were generated': '未生成原始关节数据，已跳过角色重定向',
  'Network Error': '无法连接服务，请检查本地服务是否启动',
  'Failed to fetch': '无法连接服务，请检查本地服务是否启动',
  'Task output folder not found': '未找到该任务的输出目录',
  'InterGen two-person joints22 NPY files not found': '未找到双人动作的关节数据文件',
  'LODGE motion NPY not found': '未找到舞蹈动作数据文件'
}
const jointNames = {Head: '头部', Hips: '髋部', LeftHand: '左手', RightHand: '右手'}

export function localizeMessage(value) {
  if (value == null || value === '') return ''
  if (Array.isArray(value)) return value.map(item => localizeMessage(item?.msg || item)).join('；')
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  if (messages[text]) return messages[text]
  let match
  if ((match = text.match(/^(Left|Right) (hand|forearm) is near head$/))) {
    return `${match[1] === 'Left' ? '左' : '右'}${match[2] === 'hand' ? '手' : '前臂'}与头部距离过近`
  }
  if ((match = text.match(/^Actor (\d+) (\w+) intersects actor (\d+) (\w+)$/))) {
    return `人物 ${Number(match[1]) + 1} 的${jointNames[match[2]] || match[2]}与人物 ${Number(match[3]) + 1} 的${jointNames[match[4]] || match[4]}存在骨架近距风险`
  }
  if ((match = text.match(/^Overall score ([\d.]+) is below ([\d.]+)$/))) return `综合评分 ${match[1]} 低于要求 ${match[2]}`
  if ((match = text.match(/^Critical issues (\d+) exceed (\d+)$/))) return `严重问题 ${match[1]} 个，超过允许数量 ${match[2]} 个`
  if ((match = text.match(/^Missing comparison test: (\w+)$/))) return `缺少用于比较的检测项：${qualityTestLabels[match[1]] || match[1]}`
  if ((match = text.match(/^(\w+) unavailable in candidate$/))) return `候选动作的${qualityTestLabels[match[1]] || match[1]}无法评估`
  if ((match = text.match(/^(\w+) unavailable in baseline$/))) return `基线动作的${qualityTestLabels[match[1]] || match[1]}无法评估，不能据此判断改善或退步`
  if ((match = text.match(/^(\w+) newly failed$/))) return `${qualityTestLabels[match[1]] || match[1]}新增未通过项`
  if ((match = text.match(/^(\w+) has new critical issues$/))) return `${qualityTestLabels[match[1]] || match[1]}新增严重问题`
  if ((match = text.match(/^(\w+) decreased by ([\d.]+) points$/))) return `${qualityTestLabels[match[1]] || match[1]}评分下降 ${match[2]} 分`
  if ((match = text.match(/^Overall score decreased by ([\d.]+) points$/))) return `综合评分下降 ${match[1]} 分`
  if ((match = text.match(/^(\w+) score ([\d.]+) is below ([\d.]+)$/))) return `${qualityTestLabels[match[1]] || match[1]}评分 ${match[2]} 低于要求 ${match[3]}`
  if ((match = text.match(/^(\w+) has high-severity issues$/))) return `${qualityTestLabels[match[1]] || match[1]}存在高严重度问题`
  if ((match = text.match(/^(Configured|Required) test (\w+) is missing$/))) return `缺少${match[1] === 'Required' ? '必需的' : '已配置的'}检测项：${qualityTestLabels[match[2]] || match[2]}`
  if ((match = text.match(/^(\w+) could not run: (.+)$/))) return `${qualityTestLabels[match[1]] || match[1]}未能执行：${localizeMessage(match[2])}`
  if ((match = text.match(/^(.+) \((\d+)s elapsed\)$/))) return `${localizeMessage(match[1])}（已用时 ${match[2]} 秒）`
  if ((match = text.match(/^Rendering mp4 \(attempt (\d+)\/(\d+), mode=(\w+), fps=(\d+)\)$/))) return `正在渲染视频（第 ${match[1]}/${match[2]} 次尝试，人体模型 ${match[3].toUpperCase()}，每秒 ${match[4]} 帧）`
  if ((match = text.match(/^Retarget skipped, missing required path\(s\): (.+)$/))) return `缺少必需的资源路径，已跳过角色重定向：${match[1]}`
  if ((match = text.match(/^infer_lodge.py failed with return code (\d+)(?:: (.+))?$/))) return `舞蹈生成失败（退出码 ${match[1]}）${match[2] ? '，原始信息：' + match[2] : ''}`
  if ((match = text.match(/^Exporting InterGen person([12]) joints to BVH$/))) return `正在导出人物 ${match[1]} 的动作骨架（BVH）`
  if ((match = text.match(/^Request failed with status code (\d+)$/))) return `服务请求失败（HTTP ${match[1]}）`
  if ((match = text.match(/^timeout of (\d+)ms exceeded$/))) return `请求超时（${Number(match[1]) / 1000} 秒）`
  // Keep unknown diagnostics intact instead of inventing an explanation.
  return /[\u3400-\u9fff]/.test(text) ? text : `原始信息：${text}`
}
