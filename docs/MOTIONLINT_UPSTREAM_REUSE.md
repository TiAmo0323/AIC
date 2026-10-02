# MotionLint 上游复用调查（2026-09-29）

本记录用于决定哪些现成组件可以接入当前 `HumanAction-Platform`。MotionLint 的统一表示、问题定位、质量门、修复前后评估和回归测试仍需与本项目的 InterGen / LODGE 输出契约对接。

| 仓库 | 可复用能力 | 许可和接入结论 |
| --- | --- | --- |
| [UPC-ViRVIG/pymotion](https://github.com/UPC-ViRVIG/pymotion) | NumPy 四元数、6D 旋转、BVH 读取、骨架正向运动学 | MIT；选用 `upc-pymotion==0.3.4` 作为 MotionLint 的动作几何和 BVH 读取依赖。只安装到独立 `motionlint` 环境，先用于新模块，不替换现有生成后处理。 |
| [RoMoDataset/motion-toolbox](https://github.com/RoMoDataset/motion-toolbox) | Foot skating、ground penetration、floating、jerk 质检与报告 | [项目元数据](https://github.com/RoMoDataset/motion-toolbox/blob/main/pyproject.toml)写明 CC-BY-NC-4.0、Python >=3.11，且依赖较多；当前两个模型环境为 Python 3.10。可对照指标定义，不将其代码或包直接接入当前开源作品。 |
| [nv-tlabs/kimodo](https://github.com/nv-tlabs/kimodo) | [后处理代码](https://github.com/nv-tlabs/kimodo/blob/main/kimodo/postprocess.py)包含脚部接触修正 | 代码 Apache-2.0，但修正流程依赖其骨架、约束与额外 `MotionCorrection` 模块。当前 22 关节位置轨迹和 LODGE 139D 数据需要额外适配；暂不引入整套模型栈。 |
| [lzhyu/PoseShield](https://github.com/lzhyu/PoseShield) | SMPL-H 自碰撞修复及评价 | MIT，但需要专用模型权重和人体模型；当前首版的骨架级碰撞检测直接复用本项目已有 `InterGen_api/intergen_joints2bvh.py` 更合适。 |
| [InterDigitalInc/UnderPressure](https://github.com/InterDigitalInc/UnderPressure) | 脚部接触估计 | [专用许可证](https://github.com/InterDigitalInc/UnderPressure/blob/master/LICENCE.txt)限制用途和修改；不接入。 |

## 已完成的本地验证

- 在 `D:\竞赛记录\AIC开源赛道\HumanAction-runtime\envs\motionlint` 创建独立 Python 3.10 环境，安装 `upc-pymotion==0.3.4` 和 NumPy。InterGen、LODGE 两个已有环境未改动。
- `pymotion.io.bvh.BVH` 已读入现有 LODGE 1024 帧、22 关节 BVH；`pymotion.ops.skeleton.fk` 输出 `(1024, 22, 3)`，坐标均为有限值。
- 同一读取和 FK 路径也通过了现有 InterGen 双人各自的 180 帧、22 关节 BVH。
- PyMotion 的 6D 接口形状为 `(..., 3, 2)`，用矩阵的前两**列**；当前 `shared/motion_continuity.py` 的 6D 数据由前两**行**组成。使用 `rot6d.reshape(..., 2, 3).swapaxes(-1, -2)` 传入 PyMotion，再将其输出矩阵转置；对 100 个随机旋转输入，和现有实现的最大绝对差为 `0.0`。接入时必须保留这一步约定转换。

## 接入边界

1. 已添加 `motionlint/adapters/bvh_adapter.py`，使用 PyMotion 读取关节名、父子关系、帧率、局部旋转和全局关节位置，转换为统一的 `MotionSequence`。现有生成链路无需导入这个新包。
2. LODGE 的 139D 原始数据保留 contact 4 通道、root translation 3 通道与 22×6 旋转；通过已核对的 6D 约定转换计算骨架位置。不能把 BVH 当成 contact 真值，因为 BVH 不含原始 contact 通道。
3. InterGen 的 `(T, 22, 3)` 原始位置不需要先经过 BVH 才能做质检；直接保留原始数据。
4. Foot sliding、ground contact、双人碰撞阈值和修复策略需针对本项目的坐标轴、关节映射与帧率校准。保留现有 `shared/motion_continuity.py` 和 `InterGen_api/intergen_joints2bvh.py` 的已验证处理函数，通过 wrapper 逐步接入。

安装命令（不在两个模型环境里执行）：

```powershell
uv venv D:\竞赛记录\AIC开源赛道\HumanAction-runtime\envs\motionlint --python D:\竞赛记录\AIC开源赛道\HumanAction-runtime\envs\lodge\Scripts\python.exe
uv pip install --python D:\竞赛记录\AIC开源赛道\HumanAction-runtime\envs\motionlint\Scripts\python.exe upc-pymotion==0.3.4
```

验证：独立环境中的 `python -m pytest tests/test_motionlint_core.py -q` 为 `4 passed`；新适配器还直接读取了本次新生成的 InterGen 180 帧 BVH 和现有 LODGE 1024 帧 BVH。
