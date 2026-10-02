# Asset licenses

## Kenney CC0

当前已验证的角色是 `kenney_cc0`，资源来自 [Kenney Animated Characters Protagonists](https://kenney.nl/assets/animated-characters-protagonists)。该资源以 CC0 发布；FBX 和贴图放在 `HumanAction-runtime/assets/kenney-protagonists`，仓库只保留 `config/skin_catalog.json` 中的路径和映射。

## 奶龙（本地新增）

来源：[Sketchfab 奶龙模型](https://sketchfab.com/3d-models/d7a3f20de4e4486182806c40699d26d4)，上传者 `78红米 / dong_meizi`，下载页面标注 **Free Standard**（[Sketchfab 许可说明](https://sketchfab.com/licenses)）。于 2026-10-02 在用户登录并授权下载后取得原始 FBX 包。本地原包、散列与来源信息保存在 `HumanAction-runtime/assets/nailong/source.json` 及 `source/`；整理后的带贴图模型为 `nailong.fbx`，映射为 `mapping.json`。

这项资源不属于 Kenney CC0。原包和整理后的模型只保存在本地运行时目录，不纳入源码或比赛源码包。下载页的许可标签不构成对奶龙角色 IP 的独立授权证明。

## 其他本机 FBX

`robot`、`aj`、`ch09_nonpbr`、`ch46_nonpbr`、`y_bot` 是本机目录中的可选重定向资产。若要把这些角色用于公开比赛视频，需要在发布前补充各资产的来源、许可和再分发范围；缺失资产不应打包进本仓库。

## 运行时工具

Blender、Rokoko 插件和 FFmpeg 由用户本机安装。渲染输出属于任务产物，发布时仍需遵守角色、动作数据和音乐音频各自的许可。
