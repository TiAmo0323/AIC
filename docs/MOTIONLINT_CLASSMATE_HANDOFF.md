# 两位同学的本地交接说明

这是待审阅的 0.4.0 候选，不需要 Docker、GPU、Blender、权重或 SMPL-X。安装测试使用程序生成的动作。独立标注另用本地标注包；不要先看工具告警再填写真值。

## A：在自己的电脑独立安装

解压 `motionlint-classmate-install.zip`，使用 Python 3.10 或 3.11。在 PowerShell 进入解压目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\motionlint-0.4.0-py3-none-any.whl
.\.venv\Scripts\python.exe .\run_motionlint_installation.py --participant A --wheel .\motionlint-0.4.0-py3-none-any.whl
```

Linux 如果可用：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install ./motionlint-0.4.0-py3-none-any.whl
.venv/bin/python ./run_motionlint_installation.py --participant A --wheel ./motionlint-0.4.0-py3-none-any.whl
```

脚本执行自制样例的通过、质量失败、有限修复、回归失败和输入错误。实际退出码 1 是质量结果，不是安装失败；脚本汇总返回 0 才表示上述预期行为全部符合。所有原始样例哈希在执行前后核对。

结束后保留 `installation-records/run-...` 全目录。打开 `installation.json`，据实填写 `human_feedback`：是否完成、有无开发者协助、遇到的问题和感受。不要修改自动记录的命令、退出码和时间。没有完成就记录失败和停在哪一步。

## B：导入自己的新动作

先按上述步骤安装，代号换为 B，再导入你有权使用的文件：

```powershell
.\.venv\Scripts\python.exe .\run_motionlint_installation.py --participant B --wheel .\motionlint-0.4.0-py3-none-any.whl --input "D:\你的文件夹\新动作.npy"
```

NPY 约定为米、Y-up、22 个关节的 `(T,22,3)`，也支持原 LODGE 数组格式。双人 joints22 文件可加 `--actor2`。BVH 文件可以显式设置厘米单位、Z-up 和关节映射：

```powershell
.\.venv\Scripts\python.exe .\run_motionlint_installation.py --participant B --input "D:\你的文件夹\新动作.bvh" --unit-scale 0.01 --up-axis 2 --joint-map .\map.json
```

映射文件是原名称到 MotionLint 名称的 JSON，例如 `{"mixamorig:LeftFoot":"LeftFoot"}`；应包含文件实际存在的所有必要关节。缺失映射会明确未评估，质量门不能作为通过。

查看本次 `reports/own-input/issues.json` 和 `motionlint_report.json`，记录你定位到的类型、人物、关节、帧区间、数值和阈值。报告已自动导出；骨架近距只是风险，不等于网格穿透。B 的新文件需要自己确认可使用，不随公开包上传。

## 两人各自独立标注

另外解压 `motionlint-annotation-local-only.zip`，打开 `index.html`，加载 `clips.json`，分别使用 A / B。按 `INSTRUCTIONS.md` 完整标注全部 30 条，不查看检测结果、不互相导入答案。离开前导出；下次可以恢复自己的 JSON。

两项任务不同：安装验证可以查看自制示例输出；真实动作独立标注必须先完成，之后才参加真实动作的工具辅助任务。

## 交回哪些文件

- 各自的 `annotations-A.json` / `annotations-B.json`。
- 各自完整的 `installation-records/run-...` 目录及据实填写的反馈。
- 用户任务记录：使用方法和顺序、实际用时、遗漏、误判、完成状态；使用 `human_validation_templates.json` 字段。
- B 的新输入来源和许可说明。不要发送密码、账户、学校或指导教师信息。

自动执行记录不能自行证明外部独立性。团队复核记录来源、实际操作及协助情况后，才能写入正式材料。当前模板没有完成经历。
