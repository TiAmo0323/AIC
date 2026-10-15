# MotionLint 开放许可范围

_适用于 0.5.0 正式发布；2026-10-15 根据仓库维护者的明确授权记录制定。_

---

## 📋 MIT 覆盖范围

[MIT 许可](LICENSE) 适用于以下独立 MotionLint 组件中由本项目拥有权利的实现与文档，不是对整仓所有历史平台内容的统一再许可。

| 路径 | 许可及说明 |
| --- | --- |
| `motionlint/` | MotionLint 自研 Python 实现、规则及工作台；第三方内容除外 |
| `docs/MOTIONLINT_*.md` | 本项目编写的 MotionLint 技术文档；引用内容除外 |
| `scripts/prepare_motionlint_public_release.py`、`scripts/publish_motionlint_github.py`、`scripts/motionlint_050_privacy.py` | 打包、校验、脱敏与发布工具 |
| `tests/test_motionlint_public_release.py`、`tests/test_motionlint_portable.py` | 发布验证及独立安装测试 |
| `locks/`、`resources/` 中本项目生成的清单和配置 | 不改变清单所引用的第三方资源许可 |
| `pyproject.toml`、`submission/README.md`、`submission/RELEASE_NOTES_0.5.0.md` | 本项目的包配置和发布说明 |

维护者在本次会话中确认有权将自研部分以 MIT 开放，并另外明确确认 `motionlint/core/legacy_arm_clearance.py`、`motionlint/core/continuity.py`、`motionlint/core/skeleton.py` 所继承的原始实现与骨架常量也可纳入 MIT。保留其来源说明；不把继承代码改称完全独立原创。

这是维护者提供的授权确认记录，不是第三方权利调查报告，也不构成替其他作者签署的声明。后续第三方贡献须由贡献者拥有相应授权。

## 📦 第三方与排除范围

`motionlint/static/` 中打包的 Vue/Axios 及传递依赖保留各自许可，完整文本见 [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt)，清单见 `resources/frontend-license-inventory.json`。依赖通过 pip 安装，适用各自许可。MIT 不覆盖第三方商标、模型、数据和角色形象权利。

未在上表列出的历史 `InterGen_api/`、`LODGE_api/`、`shared/`、`project/` 等集成平台内容不因根目录出现 LICENSE 而自动改为 MIT。原平台的完整许可审核与 MotionLint 独立组件的开放范围分开处理。独立 wheel 不包含这些平台目录。

模型权重、SMPL-X、FBX、原始音乐、InterHuman/FineDance/Bandai 原始动作及未确认授权的角色资产均不随核心发布。第三方来源和使用条件分别见 [第三方说明](THIRD_PARTY_NOTICES.md)、[模型说明](MODEL_LICENSES.md)、[资产说明](ASSET_LICENSES.md)。

## 🔗 历史材料与发布校验

`LICENSE_REVIEW_PENDING.md` 和旧候选包保留历史审阅状态；当前独立组件以本文件及 LICENSE 为准，不追溯修改历史包的许可元数据。新 wheel 包含本文件、MIT 正文和第三方许可文本；发布清单及 SHA256SUMS 绑定本次重新构建的附件。
