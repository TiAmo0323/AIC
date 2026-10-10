"""Strict BVH reader: validate structure and limits before allocating motion arrays.

PyMotion's tolerant file loader pads missing frames and leaves its file open on
some parse errors. Populate its documented data contract here, then use its
quaternion conversion and forward kinematics in the adapter.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np


def read_bvh(path, *, max_frames=None, max_joints=None):
    path = Path(path)
    with path.open(encoding="utf-8-sig") as handle:
        header = []
        for line in handle:
            if line.strip() == "MOTION":
                break
            header.extend(re.findall(r"[{}]|[^\s{}]+", line))
        else:
            raise ValueError("BVH 缺少 MOTION 数据段。")
        tokens = iter(header)

        def take(expected=None):
            try:
                value = next(tokens)
            except StopIteration as exc:
                raise ValueError("BVH 层级数据不完整。") from exc
            if expected is not None and value != expected:
                raise ValueError(f"BVH 层级应包含 {expected}，实际为 {value}。")
            return value

        def vector():
            values = [float(take()) for _ in range(3)]
            if not np.isfinite(values).all():
                raise ValueError("BVH OFFSET 包含非有限数值。")
            return values

        names, parents, offsets, channels, orders = [], [], [], [], []
        end_sites, end_parents = [], []

        def joint(parent):
            name = take()
            if name in names:
                raise ValueError("BVH 关节名称不能重复。")
            index = len(names)
            if max_joints is not None and index >= max_joints:
                raise ValueError(f"BVH 最多支持 {max_joints} 个关节。")
            if index >= 512:
                raise ValueError("BVH 层级过大，最多支持 512 个关节。")
            names.append(name); parents.append(parent)
            take("{"); take("OFFSET"); offsets.append(vector())
            take("CHANNELS")
            count = int(take())
            if count not in (3, 6):
                raise ValueError("BVH 只支持 3 个旋转通道，或根关节的 6 个位移与旋转通道。")
            if index != 0 and count == 6:
                raise ValueError("暂不支持非根关节的平移通道，请导出仅根关节平移的 BVH。")
            labels = [take() for _ in range(count)]
            rotations = labels[-3:]
            if set(rotations) != {"Xrotation", "Yrotation", "Zrotation"}:
                raise ValueError("BVH 旋转通道必须包含互不重复的 X / Y / Zrotation。")
            if count == 6 and set(labels[:3]) != {"Xposition", "Yposition", "Zposition"}:
                raise ValueError("BVH 根关节位移通道必须包含 X / Y / Zposition。")
            channels.append(labels)
            orders.append([label[0].lower() for label in rotations])
            while True:
                token = take()
                if token == "}":
                    return
                if token == "JOINT":
                    joint(index)
                elif token == "End":
                    take("Site"); take("{"); take("OFFSET")
                    end_sites.append(vector()); end_parents.append(index)
                    take("}")
                else:
                    raise ValueError(f"BVH 层级包含无法识别的内容：{token}。")

        take("HIERARCHY"); take("ROOT"); joint(0)
        if next(tokens, None) is not None:
            raise ValueError("BVH 只支持一棵完整的根关节层级。")

        def next_line():
            for line in handle:
                if line.strip():
                    return line.strip()
            raise ValueError("BVH 动作数据不完整。")

        match = re.fullmatch(r"Frames:\s*(\d+)", next_line())
        if not match:
            raise ValueError("BVH 缺少有效的 Frames 声明。")
        frames = int(match.group(1))
        if frames < 1 or (max_frames is not None and frames > max_frames):
            raise ValueError(f"BVH 帧数必须在 1 到 {max_frames or '允许范围'} 之间。")
        match = re.fullmatch(r"Frame\s+Time:\s*(\S+)", next_line())
        if not match:
            raise ValueError("BVH 缺少有效的 Frame Time 声明。")
        frame_time = float(match.group(1))
        if not np.isfinite(frame_time) or frame_time <= 0:
            raise ValueError("BVH Frame Time 必须为正的有限数值。")
        # No allocations based on an unchecked Frames declaration.
        positions = np.broadcast_to(offsets, (frames, len(names), 3)).copy()
        rotations = np.zeros((frames, len(names), 3))
        width = sum(map(len, channels))
        actual = 0
        for line in handle:
            if not line.strip():
                continue
            if actual >= frames:
                raise ValueError("BVH 实际帧数超过 Frames 声明。")
            words = line.split()
            if len(words) != width:
                raise ValueError(f"BVH 第 {actual + 1} 帧需要 {width} 个通道数值，实际为 {len(words)}。")
            values = np.asarray([float(word) for word in words])
            if not np.isfinite(values).all():
                raise ValueError("BVH 动作数据包含 NaN 或 Inf。")
            cursor = 0
            for index, labels in enumerate(channels):
                count = len(labels)
                if count == 6:
                    for offset, label in enumerate(labels[:3]):
                        positions[actual, index, "XYZ".index(label[0])] = values[cursor + offset]
                rotations[actual, index] = values[cursor + count - 3:cursor + count]
                cursor += count
            actual += 1
        if actual != frames:
            raise ValueError(f"BVH 声明 {frames} 帧，实际只有 {actual} 帧。")
    return {"filename": str(path), "names": np.asarray(names), "offsets": np.asarray(offsets),
        "parents": np.asarray(parents), "end_sites": np.asarray(end_sites).reshape(-1, 3),
        "end_sites_parents": np.asarray(end_parents, dtype=int), "rot_order": np.asarray(orders),
        "channels": np.asarray([len(labels) for labels in channels]), "positions": positions,
        "rotations": rotations, "frame_time": frame_time}
