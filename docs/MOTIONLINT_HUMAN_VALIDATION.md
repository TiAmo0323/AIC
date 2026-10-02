# 两位同学的独立标注与使用验证

## A. 标注

1. 分别打开标注包的 `index.html`，加载 `clips.json`，填写不同代号 A / B。不要查看检测报告或讨论答案。
2. 每条原始动作完整看两遍，正面/侧面联合判断，必要时逐帧定位。
3. 标注连续性、骨架变化、支撑脚滑动、地面接触异常、骨架近距风险、抖动的起止帧、人物和关节。统一使用闭区间、从第 0 帧编号。
4. 正常摆脚不算支撑脚滑动；腾空不自动算悬浮；近距不等于网格穿透。预期握手/击掌独立勾选。无法判断勾选不确定，不能当作正常。
5. 每条判断提示词语义，确认完整看过。没有异常也必须确认。导出 JSON，保留原文件。
6. 两人交给复核者后再讨论分歧。复核者记录裁决和理由，生成 `adjudicated.json`，真实准确率只在裁决完成后计算。

标注可以分次完成：离开页面前导出 JSON，下次先加载 `clips.json`，再用“继续自己的标注”导入自己的文件。每人分别保存，不互相导入。

复核者生成待裁决表：

```powershell
python scripts/prepare_motionlint_adjudication.py annotations-A.json annotations-B.json --output adjudicated.json
```

该命令不会创建真值。逐条核查 `review.annotator_a_events` 和 `review.annotator_b_events`，填写最终 `events`、`semantic_alignment`、`review.decision` 与 `review.reason`；核查完成才把该动作 `status` 改为 `complete`、`review.status` 改为 `reviewed`。所有动作完成后填写真实 `reviewed_by`，把顶层 `status` 改为 `adjudicated`。原始两份标注保持不变。

开发集标注可先用于修正规则；冻结后才能执行独立盲测。如在本次冻结后继续修改核心代码，不能沿用冻结文件宣称独立盲测，需要建立新协议。

```powershell
python scripts/evaluate_motionlint_annotations.py --annotator-a annotations-A.json --annotator-b annotations-B.json --annotations adjudicated.json --split holdout
```

骨架视图的局限：不能标注蒙皮表面真实穿透；只有骨架可见风险。地面基准未知或难以区分正常快速动作与抖动时标为不确定。源文件/规则/代码冻结后才执行盲测，未达目标保留原结果。

## B. 用户任务

每人使用同一批开发动作完成：① 找出问题帧；② 判断修复是否退步。先人工观看，再使用工具，采用不同且难度匹配的动作分组并交换顺序，降低记忆影响。记录实际用时、遗漏、误判和任务结束状态。记录模板见 `experiments/human_validation_templates.json`。

## C. 外部安装

A 在自己的电脑建立 Python 3.10/3.11 新环境，按照 Quickstart 安装候选 wheel，完成 clean 检测、脚滑修复、回归比较。

B 导入一条自有/可使用的新文件（BVH 必须说明单位、轴和映射），定位问题并导出报告。

记录操作系统、Python、包哈希、执行命令、退出码、报错、是否需要开发者协助。开发者在本机的新环境测试不替代这个记录。所有模板默认 `pending`，不能填写未发生的用户反馈。
