# 本地奶龙角色

## 已接入的内容

- 角色 ID：`nailong`，界面名称：**奶龙**。
- 使用现有 LODGE → BVH → Blender/Rokoko → MP4 链路。
- 模型具有 25 根骨骼、6 个网格。人体动作映射使用其中 14 根骨骼。
- 已修复原始 FBX 的网格与骨骼坐标轴不一致、眼睛和牙齿缺失权重、缺失材质贴图链接及尺寸问题。
- 整理后的角色高约 1.2 米。所有网格顶点均有绑定权重，身体和眼睛贴图嵌入 FBX。
- 已用现有 LODGE 任务 `a394daeb-6ca1-44e3-a5e8-970a73aea88c` 的单人动作试渲染 180 帧，并导出完整 1024 帧视频。

## 使用

打开本地前端，在音乐生成舞蹈流程中选择 **奶龙**。LODGE 输出单人舞蹈；文本生成的 InterGen 仍属于双人流程，选择奶龙不会把它改成单人。

后端与前端角色目录已同步。模型位于同级运行时目录：

```text
HumanAction-runtime/assets/nailong/
  source.json
  source/sketchfab-original.zip
  source/model/original/U_LMSHK_Suit_21 (3).fbx
  nailong.fbx
  mapping.json
```

## 重新整理模型

在项目根目录执行 PowerShell：

```powershell
& '../HumanAction-runtime/blender-4.2.23-windows-x64/blender.exe' -b --disable-autoexec --python-exit-code 1 --python scripts/prepare_nailong_asset.py -- --input '../HumanAction-runtime/assets/nailong/source/model/original/U_LMSHK_Suit_21 (3).fbx' --output '../HumanAction-runtime/assets/nailong/nailong.fbx' --mapping '../HumanAction-runtime/assets/nailong/mapping.json' --report reports/nailong/preparation.json
```

整理脚本针对这份下载模型，保留原始文件。`Mod_LMSHK_Suit_21.fbx` 是另一个不带骨骼的文件，不能用它替代带骨骼版本。

`scripts/inspect_character_asset.py` 可检查其他候选 FBX 的骨骼、权重和贴图；检查通过只证明资源具备基础结构，仍需实际渲染检查变形。

## 渲染与检查

### 视觉修订版

用户指出初版外观和动作不自然后，新增 `LODGE_api/nailong_character_profile.py`。单人 `nailong.fbx` 的重定向默认应用该配置：

- 改用 Standard 色彩变换与偏卡通的贴图材质，降低高光造成的泛白。
- 放大虹膜网格 1.28 倍，保持原来的眼白和头部网格。
- 调整头部和四肢的旋转幅度；原动作中小腿最大局部旋转约 138°，修订后限制到 35°。
- 根据每帧实际足部网格调整整个角色的根节点高度，最低足部点约距地面 8 毫米。
- 添加地面和投影，并用固定正交相机覆盖完整动作范围。

这属于卡通展示适配。根节点高度校正可能压低原动作中的跳跃，并不包含双脚独立锁定或完整接触求解。设置 `nailong_profile_enabled: false` 可在渲染清单中关闭该配置。该配置目前只用于单人奶龙，其他角色和双人场景不应用。

旧版视频继续保留用于对比。修订场景是 `reports/nailong/nailong_dance_v2.blend`，适配报告是 `reports/nailong/profile_v2.json`。

修订视频：`output/video/nailong_single_dance_v2_20261002.mp4`。本机 EEVEE 在新版场景连续渲染约 75 帧后也出现过内存分配失败，因此该版本使用每段 40 帧的独立进程渲染：

```powershell
& '../HumanAction-runtime/envs/motionlint/Scripts/python.exe' scripts/render_character_chunks.py --scene reports/nailong/nailong_dance_v2.blend --output output/video/nailong_single_dance_v2_20261002.mp4 --frames 1024 --chunk-frames 40 --work-dir reports/nailong/chunks_v2_40
```

修订版完整渲染已完成：720 × 720、30 fps、34.13 秒、26 段。FFmpeg 完整解码核对 1024 帧通过；报告为 `reports/nailong/chunks_v2_40/render_report.json`。抽查开头、约第 15、25、33 秒画面，角色保持入镜。前端缩略图已经更新为修订后的实际渲染图，角色选择检查与前端构建通过。

还从原始准备好的 FBX 与 BVH 重新运行了一次既有 `blender_rokoko_retarget.py` 入口，渲染 20 帧成功，并确认报告包含自动应用的奶龙配置；没有依赖手工修改好的场景才能得到新版效果。入口验证报告是 `reports/nailong/pipeline_v2_report.json`。这次没有重新执行音频生成模型推理。

以下为初版的验证记录。

试片：`output/video/nailong_single_dance.mp4`，540 × 540、30 fps、6 秒，无声。

完整视频：`output/video/nailong_single_dance_full_20261002.mp4`，720 × 720、30 fps、34.13 秒，无声。9 段渲染合并后，FFmpeg 完整解码通过，核对得到 1024 帧；报告为 `reports/nailong/chunks/render_report.json`。抽查第 1、3、5、15、25、33 秒画面，角色完整入镜，眼睛和牙齿没有明显脱离。

前端角色选择回归、前端生产构建以及 `tests/test_skin_output_selection.py` 的前后端输出契约检查通过。运行中的 LODGE `/v1/lodge/skins` 已返回 `nailong`；浏览器已检查到奶龙角色卡片。上述检查证明接入和这份已有动作的渲染可用；本次没有重新执行一次完整的音频推理任务。

试片的清单、结构报告、渲染报告与可编辑 Blender 场景位于 `reports/nailong/`。完整动作仍保留在 `nailong_dance.blend` 中。

本机连续渲染长视频时遇到一次内存分配失败；可对已保存场景使用分段渲染脚本。每段使用独立 Blender 进程释放内存，最后合并并完整解码核对帧数：

```powershell
& '../HumanAction-runtime/envs/motionlint/Scripts/python.exe' scripts/render_character_chunks.py --scene reports/nailong/nailong_dance.blend --output output/video/nailong_single_dance_full_20261002.mp4 --frames 1024 --chunk-frames 120 --work-dir reports/nailong/chunks
```

## 当前边界

- 模型没有独立的足部、脚趾或手指变形骨骼。支持四肢和躯干动作；现有人形足部 IK 修复不适合直接用于这个角色。初版跑通不代表观感自然，修订版仍受原始简化网格和静态表情限制。
- 本次验证的是已有舞蹈动作换成奶龙后能够渲染；没有重新训练生成模型，也不代表动作通过 MotionLint 严格质量门。
- 原包没有表情动画。眼睛、牙齿和舌头随头部移动，但未接入口型、眨眼或表情控制。
- 来源和许可记录见 `ASSET_LICENSES.md`。本地模型资源不放入 Git。
