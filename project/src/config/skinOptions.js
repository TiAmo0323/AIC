// 前端角色目录的离线回退值；正常运行时以后端 /skins 返回的目录为准。
// outputKind 决定请求走 SMPL 预览还是 Blender/Rokoko 重定向链路。
export const DEFAULT_SKIN_ID = 'smpl'

export const skinOptions = Object.freeze([
  Object.freeze({
    id: 'smpl',
    label: '标准人体',
    category: '基础人体模型',
    description: '查看标准 SMPL / SMPL-X 人体网格动画',
    outputKind: 'smpl',
    backendMode: 'smplx',
    thumbnail: '/skin-thumbnails/smpl.jpg'
  }),
  Object.freeze({
    id: 'kenney_cc0',
    label: '开源卡通角色',
    category: '角色蒙皮',
    description: 'Kenney CC0 角色，可直接渲染，不依赖 SMPL-X 模型',
    outputKind: 'retarget',
    backendMode: 'smplx',
    thumbnail: '/local-intergen-kenney.png'
  }),
  Object.freeze({
    id: 'nailong',
    label: '奶龙',
    category: '角色蒙皮',
    description: '奶龙卡通角色，已验证单人舞蹈重定向',
    outputKind: 'retarget',
    backendMode: 'smplx',
    thumbnail: '/skin-thumbnails/local-character.svg'
  }),
  Object.freeze({
    id: 'robot',
    label: '粉色机器人',
    category: '角色蒙皮',
    description: '查看经过 Blender / Rokoko 重定向的机器人动画',
    outputKind: 'retarget',
    backendMode: 'smplx',
    thumbnail: '/skin-thumbnails/robot.jpg'
  }),
  Object.freeze({
    id: 'aj',
    label: '街头少年',
    category: '角色蒙皮',
    description: '查看经过 Blender / Rokoko 重定向的 AJ 卡通人物动画',
    outputKind: 'retarget',
    backendMode: 'smplx',
    thumbnail: '/skin-thumbnails/aj.jpg'
  }),
  Object.freeze({
    id: 'ch09_nonpbr',
    label: '绿衣少年',
    category: '角色蒙皮',
    description: '查看经过 Blender / Rokoko 重定向的 Ch09 角色动画',
    outputKind: 'retarget',
    backendMode: 'smplx',
    thumbnail: '/skin-thumbnails/ch09_nonpbr.jpg'
  }),
  Object.freeze({
    id: 'ch46_nonpbr',
    label: '动漫少女',
    category: '角色蒙皮',
    description: '查看经过 Blender / Rokoko 重定向的 Ch46 角色动画',
    outputKind: 'retarget',
    backendMode: 'smplx',
    thumbnail: '/skin-thumbnails/ch46_nonpbr.jpg'
  }),
  Object.freeze({
    id: 'y_bot',
    label: '蓝色机器人',
    category: '角色蒙皮',
    description: '查看经过 Blender / Rokoko 重定向的 Y Bot 机器人动画',
    outputKind: 'retarget',
    backendMode: 'smplx',
    thumbnail: '/skin-thumbnails/y_bot.jpg'
  })
])

export function getSkinOption(skinId, options = skinOptions) {
  return options.find((option) => option.id === skinId) || options[0] || skinOptions[0]
}
