"""Bounded uploads staged outside the task registry until validation succeeds."""
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
from uuid import uuid4

import numpy as np
from fastapi import HTTPException

AUDIO_UPLOAD_LIMIT = 128 * 1024 * 1024
NPY_UPLOAD_LIMIT = 32 * 1024 * 1024
AUDIO_SUFFIXES = {".wav", ".mp3", ".mp4", ".m4a", ".aac", ".flac", ".ogg"}


@asynccontextmanager
async def stage_upload(root, upload, *, filename, limit):
    root = Path(root).resolve()
    folder = root / str(uuid4())
    path = folder / "input" / filename
    path.parent.mkdir(parents=True)
    try:
        size = 0
        with path.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"上传文件不能超过 {limit // (1024 * 1024)} MB。")
                output.write(chunk)
        if not size:
            raise HTTPException(422, "上传文件为空，请重新选择。")
        yield folder.name, path
    except BaseException:
        checked = folder.resolve()
        if checked.parent == root and checked.name == folder.name:
            shutil.rmtree(checked)
        raise
    finally:
        await upload.close()


def validate_npy(path, *, motion=False):
    array = None
    try:
        array = np.load(path, mmap_mode="r", allow_pickle=False)
        if not isinstance(array, np.ndarray):
            raise ValueError("请选择 NPY 数组文件，不能使用 NPZ 压缩包。")
        if array.ndim != 2 or not array.shape[0] or not array.shape[1]:
            raise ValueError("NPY 必须是非空的二维数组。")
        if motion and array.shape[1] not in {135, 139, 315, 319}:
            raise ValueError("LODGE 动作 NPY 需要 135 / 139 / 315 / 319 维。")
        if not motion and array.shape[1] != 35:
            raise ValueError("LODGE 音乐特征 NPY 需要 35 维；动作 NPY 请使用动作导入入口。")
        if not np.issubdtype(array.dtype, np.number) or np.iscomplexobj(array) or not np.isfinite(array).all():
            raise ValueError("NPY 必须包含有限的实数数值。")
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(422, f"无法读取上传的 NPY：{exc}") from exc
    finally:
        mapping = getattr(array, "_mmap", None)
        if mapping is not None:
            mapping.close()
        if isinstance(array, np.lib.npyio.NpzFile):
            array.close()
