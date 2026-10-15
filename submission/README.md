# MotionLint 0.5.0 正式提交材料

_本目录为当前评审入口；0.4 历史草稿不再作为提交材料。_

---

## 📦 当前材料

| 材料 | 入口 |
| --- | --- |
| 技术报告 | [MotionLint-050-report.pdf](MotionLint-050-report.pdf) |
| 自动操作演示 | [MotionLint-050-demo.mp4](MotionLint-050-demo.mp4)，186.56 秒 |
| 安装包、独立源码与证据附件 | [v0.5.0 Release](https://github.com/TiAmo0323/AIC/releases/tag/v0.5.0) |
| 发布说明 | [RELEASE_NOTES_0.5.0.md](RELEASE_NOTES_0.5.0.md) |
| 机器结果与逐项索引 | [本轮结果](../docs/MOTIONLINT_050_RESULTS.md)、[结论索引](../evidence/iteration-050-claims.json) |
| 许可范围 | [MIT 正文](../LICENSE)、[明确范围](../LICENSE_SCOPE.md)、[第三方许可](../THIRD_PARTY_LICENSES.txt) |

## 📊 证据边界

本次以冻结输入、已知注入真值、对照/消融、输入哈希、实际导出回读、仓库外安装和自动浏览器操作作为工程证据。不以真人标注、访谈、外部学生安装或语义评价作为本次提交前置条件，也不宣称完成过这些工作。

可控保留集宏 F1 1.00 仅针对解析注入；真实保留输入严格通过 22/36 不是真实检测准确率。六条实际流程均产生文件，只有一条通过跨阶段骨架质量门，该样本仍有网格穿地。失败及限制不因正式发布而删除。

## 🔍 演示来源与历史材料

演示来自 923 个带时间戳的实际浏览器屏幕帧，配中文合成语音，属于自动操作记录，不是人工用户经历或连续实时屏幕录制。角色来源与运行时边界见 [第三方说明](../THIRD_PARTY_NOTICES.md)。原始模型、角色、音乐和受限动作文件不进入安装包。

`report-draft.pdf` 和 `demo-engineering-draft.mp4` 为 0.4 历史草稿，仅为追溯保留；其中“等待真人验证”等旧待办不适用于本次 0.5.0 提交。未发布到 PyPI；GitHub Release 与 PyPI 发布是不同事项。
