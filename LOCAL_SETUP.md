# 本机运行状态

工作目录：`D:\竞赛记录\AIC开源赛道\HumanAction-Platform`。依赖、模型和 Blender 放在同级的 `HumanAction-runtime`，不会提交到平台仓库。

## 启动与关闭

在 PowerShell 中执行：

```powershell
cd 'D:\竞赛记录\AIC开源赛道\HumanAction-Platform'
.\start-local.ps1
```

启动后打开 <http://127.0.0.1:5173/>。InterGen API 为 `http://127.0.0.1:8001`，LODGE API 为 `http://127.0.0.1:8002`，MotionLint API 为 `http://127.0.0.1:8003`。关闭这四个本机服务：

```powershell
.\stop-local.ps1
```

日志在 `..\HumanAction-runtime\intergen-api.*.log`、`lodge-api.*.log`、`motionlint-api.*.log` 和 `frontend.*.log`。

## 前端使用

在首页角色选项里选择“开源卡通角色”。文字模式请给人物 A、B 都选它；音乐模式可选“标准人体”或“开源卡通角色”。输入文字可生成 InterGen 双人角色视频；上传音乐可生成 LODGE 单人舞蹈视频。生成完成后点击 **MotionLint** 查看六项质量测试，必要时点击 `Repair All`，也可以选择两个已有任务做回归比较。LODGE 的一个全局窗口是 1024 帧，建议先用至少约 35 秒的音频；角色视频需要等待 Blender 渲染。已生成的示例可直接在 <http://127.0.0.1:5173/local-motion-preview.html> 播放。

## 已验证的功能

- 前端依赖安装完成，`npm run build` 通过；前端和两个 API 的 HTTP 健康检查通过。
- InterGen 使用独立的 Python 3.10 环境、CUDA PyTorch 和公开的 InterGen 检查点，可在本机 RTX 4060 Laptop GPU 上推理。已用英文提示词生成 180 帧、30 FPS 的双人动作，并用 FFmpeg 完整解码所得 6 秒 MP4。
- 原平台的 InterGen SMPL 网格拟合渲染器没有公开提供，因此 InterGen 的 `smpl` 选项目前仍生成**骨架预览**。本地 InterGen 源码中有兼容模块和低内存加载改动；它们位于 `..\HumanAction-runtime\InterGen\InterGen_master`。人体模型已经安装，但单靠模型文件无法把 InterGen 的 22 关节数据转换为 SMPL-X 网格动作。
- Blender 4.2.23、Rokoko 插件、FFmpeg 和 [Kenney CC0 卡通角色](https://kenney.nl/assets/animated-characters-protagonists)已配置。角色 ID 为 `kenney_cc0`；InterGen 的双人动作经 BVH 转换、22 根骨骼映射和 Blender 重定向后，成功导出有动态人物的 1080×1080 MP4。前端选“开源卡通角色”即可使用。
- LODGE 官方的 Global/Local 检查点已放在 `..\HumanAction-runtime\LODGE-main\exp`。Python 3.10、CUDA PyTorch、PyTorch3D 的 BSD 许可变换模块以及推理依赖均已配置。已用本机合成节拍提取 35 维音乐特征，实测两阶段推理生成 1024 帧、139 维舞蹈动作数组。
- LODGE 的音频到角色视频 API 已端到端验证：`infer-from-audio` 任务 `a394daeb-6ca1-44e3-a5e8-970a73aea88c` 成功生成 34.13 秒、1024 帧、1080×1080 H.264/AAC 角色视频，Blender 重定向和原音轨封装均显示成功；FFmpeg 可完整解码，视频可在 <http://127.0.0.1:5173/local-motion-preview.html> 播放。测试音频为 `..\HumanAction-runtime\assets\lodge-test-beat.wav`，由脚本合成，供验证链路使用。
- 两套生成 API 会将任务状态写入任务目录的 `task_manifest.json`；重启服务后会恢复已有任务记录，MotionLint 则直接扫描任务产物，不依赖内存中的任务列表。
- 官方下载的 `smplx_lockedhead_20230207.zip` 含中性、男性、女性 NPZ 模型，已通过 `scripts/install_smplx_model.py` 安装到 `..\HumanAction-runtime\InterGen\InterGen_master\human_models\smplx`。中性模型能由 `smplx` 加载并生成 10,475 顶点的人体网格。`LODGE_api/render_smplx_local.py` 可把 139 维动作渲染成 SMPL-X 视频；LODGE 的 `render-from-npy-upload` 接口任务 `128c634d-b8b1-4876-ad40-87bed690d2dc` 已成功生成 60 帧网格视频，完整的 1024 帧、34.13 秒 H.264/AAC 示例可在上述预览页播放。
- 针对 8 GB 显存，InterGen 在每次任务后释放 GPU，在下次文字生成时自动重新加载。已验证文字任务完成后空闲占用约 136 MiB，两个 API 同时运行时 LODGE 也能用任意文件名 `testbeat` 完成 1024 帧推理。请依次提交文字和音乐生成任务，避免两个模型同时推理。

## 完整功能仍需的资源

1. InterGen 双人的 SMPL-X 网格拟合仍缺少原作者未公开的自定义渲染器；当前双人骨架和 Kenney 角色视频可用。LODGE 单人的 SMPL-X 网格视频已经可用。
2. 平台原有 `X Bot.fbx`、`Aj (1).fbx` 等皮肤仍缺失，选这些皮肤会失败；请选 `kenney_cc0`。
3. LODGE 的配置和推理脚本已在本机上游克隆 `..\HumanAction-runtime\LODGE-main` 中修正了 Linux 路径、CUDA 设备号和 NumPy 兼容性；重新克隆上游后需要保留这些本地修改及检查点。

公开上游的 InterGen 检查点与这里使用的[公开处理版检查点](https://huggingface.co/ZeyuLing/hftrainer-intergen-interhuman)来源不同，当前验证的是可运行性；生成质量是否等同于原作者配置尚未评估。[LODGE 官方仓库](https://github.com/li-ronghui/LODGE)提供了已安装的检查点下载入口。上游 `render.py` 使用硬编码的 Linux 路径；本地 API 在 SMPL-X 模式下调用 `LODGE_api/render_smplx_local.py`。
