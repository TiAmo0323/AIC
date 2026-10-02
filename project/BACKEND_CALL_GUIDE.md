# 后端调用说明（与当前项目代码一致）

本文档基于当前代码实现整理，覆盖前端 `project/src/App.vue` 正在实际调用的后端接口。

## 1. 当前架构

前端通过两个后端服务完成生成：

- InterGen API（默认 `http://127.0.0.1:8001`）
  - 负责文本驱动的人体动作生成。
- LODGE API（默认 `http://127.0.0.1:8002`）
  - 负责音乐/特征驱动推理和渲染。

前端环境变量（Vite）：

- `VITE_INTERGEN_API_BASE`：InterGen 基地址，默认 `http://127.0.0.1:8001`
- `VITE_LODGE_API_BASE`：LODGE 基地址，默认 `http://127.0.0.1:8002`
- `VITE_LODGE_PYTHON_EXECUTABLE`：可选，传给 LODGE 的 `python_executable`

## 2. 前端输入模式与真实行为

- `text`：可用，调用 InterGen。
- `music`：可用，调用 LODGE（上传 `mp3/mp4/wav/npy`）。
- `voice`：UI 可切换，但提交时会提示“语音功能暂未开放”。

说明：

- 前端分辨率选项 `720p/1080p/2k` 目前只用于 UI 展示，未传入后端。
- 文件上传后会强制切到 `music` 流程，避免落在 `voice` 模式导致无法提交。

### 2.1 蒙皮选择

前端启动后会并行读取 `GET /v1/intergen/skins` 和
`GET /v1/lodge/skins`，后端不可用时回退到
`src/config/skinOptions.js` 的内置列表。当前提供：

| 选项 | 输出类型 | 请求行为 |
|---|---|---|
| SMPL | `smpl` | 勾选时生成普通 SMPL / SMPL-X 视频 |
| 机器人 | `retarget` | 勾选时执行 Blender/Rokoko 重定向并生成机器人视频 |

至少选择一项。前端默认使用“单选模式”：默认 SMPL 时点击机器人会直接替换
SMPL，只提交 `skin_ids=robot`。点击蒙皮区域内的模式按钮切换为“多选模式”后，
才允许同时保留 SMPL、机器人或后续新增蒙皮。多选切回单选时保留最近加入的
蒙皮。

选择和模式按钮会在任务提交后锁定：单选只生成对应最终视频，多选才生成多种
最终视频。多选任务完成后可通过结果切换按钮查看不同蒙皮。模式切换仅控制前端
如何组织 `skin_ids`，后端接口字段没有变化。

新增其他蒙皮时，优先在项目级 `config/skin_catalog.json` 增加配置，不要在
`App.vue` 中复制按钮。InterGen 与 LODGE 均已提供
`/download-retarget`，文本和音频任务都可以在线选择并播放机器人结果。

## 3. InterGen API（文本生成）

### 3.1 提交任务

`POST /v1/intergen/tasks/generate`

请求体：

```json
{
  "text": "两个人相遇，握手后并排向前行走。",
  "skin_ids": ["smpl", "robot"],
  "skin_id": "robot",
  "retarget_enabled": true
}
```

`skin_ids` 是当前正式字段；`skin_id` 和 `retarget_enabled` 仅为旧客户端保留。

返回示例：

```json
{
  "task_id": "f8f65cbf-7d1b-4bbd-b2f5-589f09b8e5f7",
  "status": "queued",
  "created_at": "2026-03-27T12:00:00Z",
  "updated_at": "2026-03-27T12:00:00Z",
  "message": "Task queued",
  "output_mp4_path": null,
  "stderr_tail": ""
}
```

### 3.2 查询任务

`GET /v1/intergen/tasks/{task_id}`

状态枚举：

- `queued`
- `running`
- `succeeded`
- `failed`

### 3.3 下载视频

`GET /v1/intergen/tasks/{task_id}/download`

返回 `video/mp4`。

机器人或其他重定向蒙皮：

`GET /v1/intergen/tasks/{task_id}/download-retarget`

### 3.4 其他可用接口

- `GET /health`
- `POST /translate`

## 4. LODGE API（音乐/文件上传）

前端当前实际调用的是上传类接口：

- 音频文件（`mp3/mp4/wav`）：
  - `POST /v1/lodge/tasks/infer-from-audio-upload`
  - 表单字段：
    - `lodge_root`（前端读取 `VITE_LODGE_ROOT`，默认 `D:/HumanAction_Platform/LODGE-main`）
    - `song_id`（文件名去后缀）
    - `audio_file`（上传文件）
    - `python_executable`（可选，来自 `VITE_LODGE_PYTHON_EXECUTABLE`）
    - `mode`（默认 `smplx`）
    - `device`（默认 `0`）
    - `fps`（默认 `30`）
    - `skin_ids`（可重复表单字段，当前值为 `smpl`、`robot`）
    - `skin_id`（兼容旧前端）
    - `retarget_enabled`（兼容旧前端；新逻辑以 `skin_ids` 为准）
- 特征文件（`npy`）：
  - `POST /v1/lodge/tasks/infer-from-feature-npy-upload`
  - 字段与上面类似，文件字段为 `npy_file`

LODGE 任务对象包含 `progress` 字段（0-100），前端会优先使用该字段驱动进度条。
音频上传任务还返回 `audio_mux_status`、`audio_mux_message` 和
`audio_muxed_skin_ids`，以及实际采用的 `audio_mux_advance_seconds`。
所选 SMPL/机器人视频会在完成前加入原始上传音乐；标准 LODGE 启动脚本将
音频提前 `2.0 s`，用于补偿当前基线的动作—音乐相位差；
特征 NPY 输入没有原始音乐，因此保持静音。

### 4.1 查询任务

`GET /v1/lodge/tasks/{task_id}`

### 4.2 下载视频

`GET /v1/lodge/tasks/{task_id}/download`

支持：

- 在线播放（默认 `inline`）
- 下载（`?as_attachment=true`）
- Range 请求（断点/分段播放）

### 4.3 打开本机播放器与输出目录（前端已接入）

- `POST /v1/lodge/tasks/{task_id}/open-output-player`
- `POST /v1/lodge/tasks/{task_id}/open-output-folder`

前端会附带当前实际播放结果的 `skin_id` 查询参数。InterGen 也提供同名
辅助接口。它们会在后端机器上执行系统命令打开所选蒙皮对应的播放器或
文件夹，适合本机部署联调场景。

### 4.4 LODGE 其他可用接口（当前前端未直接调用）

- `POST /v1/lodge/tasks/render-song`
- `POST /v1/lodge/tasks/infer-and-render`
- `POST /v1/lodge/tasks/infer-from-audio`
- `POST /v1/lodge/tasks/render-from-npy-upload`
- `GET /health`

## 5. 前端轮询与进度逻辑

前端提交任务后每 5 秒轮询一次状态接口。

规则如下：

1. 提交后先显示 `10%`。
2. 若状态返回里有数值型 `progress`，直接使用。
3. 若没有 `progress`（如 InterGen 当前返回结构），前端会模拟进度（未完成前每轮 +5，最高到 95）。
4. `status = succeeded` 时置 `100%` 并展示视频。
5. `status = failed` 时归零并提示 `message`。

## 6. 联调顺序建议

1. 启动 InterGen API（默认 8001）。
2. 启动 LODGE API（默认 8002）。
3. 启动前端：`npm run dev`。
4. 文本模式验证 InterGen。
5. 上传 `mp3/mp4/wav/npy` 验证 LODGE。

## 7. 调用示例（可直接用）

### 7.1 InterGen 文本任务

```bash
curl -X POST "http://127.0.0.1:8001/v1/intergen/tasks/generate" \
  -H "Content-Type: application/json" \
  -d "{\"text\":\"两个人相遇，握手后并排向前行走。\"}"
```

```bash
curl "http://127.0.0.1:8001/v1/intergen/tasks/<task_id>"
```

### 7.2 LODGE 音频上传任务

```bash
curl -X POST "http://127.0.0.1:8002/v1/lodge/tasks/infer-from-audio-upload" \
  -F "lodge_root=D:/HumanAction_Platform/LODGE-main" \
  -F "song_id=demo001" \
  -F "mode=smplx" \
  -F "device=0" \
  -F "fps=30" \
  -F "audio_file=@demo001.mp3"
```

### 7.3 LODGE 特征 npy 上传任务

```bash
curl -X POST "http://127.0.0.1:8002/v1/lodge/tasks/infer-from-feature-npy-upload" \
  -F "lodge_root=D:/HumanAction_Platform/LODGE-main" \
  -F "song_id=demo002" \
  -F "mode=smplx" \
  -F "device=0" \
  -F "fps=30" \
  -F "npy_file=@demo002.npy"
```

### 7.4 查询与下载

```bash
curl "http://127.0.0.1:8002/v1/lodge/tasks/<task_id>"
```

```bash
curl -L -o result.mp4 "http://127.0.0.1:8002/v1/lodge/tasks/<task_id>/download?as_attachment=true"
```

## 8. 常见问题

- 任务 404：后端重启后内存任务会丢失，需要重新提交。
- InterGen 无真实进度：当前返回结构无 `progress` 字段，前端会自动走模拟进度。
- 播放器/文件夹打不开：通常是后端进程无桌面权限或非本机部署，改用下载接口即可。
