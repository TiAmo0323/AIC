# InterGen 与 LODGE 共用的角色目录解析器。
# 统一处理默认角色、旧参数兼容、skin_ids 去重、公开字段过滤和本地资源路径解析。
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_SKIN_ID = "smpl"
LEGACY_RETARGET_SKIN_ID = "robot"
SUPPORTED_OUTPUT_KINDS = {"smpl", "retarget"}


class SkinCatalogError(ValueError):
    """Raised when a requested skin or the skin catalog is invalid."""


def catalog_path(project_root: Path) -> Path:
    configured = os.getenv("HUMAN_ACTION_SKIN_CATALOG", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (project_root / "config" / "skin_catalog.json").resolve()


def load_skin_catalog(project_root: Path) -> Tuple[Path, Dict[str, Dict[str, object]]]:
    """读取并验证角色目录，拒绝重复 ID、未知输出类型和无效默认角色。"""
    path = catalog_path(project_root)
    if not path.is_file():
        raise SkinCatalogError(f"Skin catalog not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkinCatalogError(f"Failed to read skin catalog {path}: {exc}") from exc

    raw_skins = payload.get("skins")
    if not isinstance(raw_skins, list) or not raw_skins:
        raise SkinCatalogError("Skin catalog must contain a non-empty 'skins' list")

    skins: Dict[str, Dict[str, object]] = {}
    for raw_skin in raw_skins:
        if not isinstance(raw_skin, dict):
            raise SkinCatalogError("Every skin catalog entry must be an object")
        skin_id = str(raw_skin.get("id") or "").strip()
        output_kind = str(raw_skin.get("output_kind") or "").strip()
        if not skin_id:
            raise SkinCatalogError("Every skin catalog entry must have an id")
        if skin_id in skins:
            raise SkinCatalogError(f"Duplicate skin id in catalog: {skin_id}")
        if output_kind not in SUPPORTED_OUTPUT_KINDS:
            raise SkinCatalogError(
                f"Skin '{skin_id}' has unsupported output_kind '{output_kind}'"
            )
        skins[skin_id] = dict(raw_skin)

    default_skin_id = str(payload.get("default_skin_id") or DEFAULT_SKIN_ID).strip()
    if default_skin_id not in skins:
        raise SkinCatalogError(f"Default skin is not defined in catalog: {default_skin_id}")
    return path, skins


def resolve_skin(
    project_root: Path,
    skin_id: Optional[str],
    legacy_retarget_enabled: bool = False,
) -> Dict[str, object]:
    return resolve_skins(
        project_root,
        skin_ids=None,
        skin_id=skin_id,
        legacy_retarget_enabled=legacy_retarget_enabled,
    )[0]


def resolve_skins(
    project_root: Path,
    skin_ids: Optional[List[str]],
    skin_id: Optional[str] = None,
    legacy_retarget_enabled: bool = False,
) -> List[Dict[str, object]]:
    """按新旧请求参数优先级解析角色集合，并保持用户选择顺序。"""
    _, skins = load_skin_catalog(project_root)
    requested_ids = [str(value or "").strip() for value in (skin_ids or [])]
    requested_ids = [value for value in requested_ids if value]
    if not requested_ids:
        legacy_skin_id = (skin_id or "").strip()
        if legacy_skin_id:
            requested_ids = [legacy_skin_id]
        elif legacy_retarget_enabled:
            requested_ids = [DEFAULT_SKIN_ID, LEGACY_RETARGET_SKIN_ID]
        else:
            requested_ids = [DEFAULT_SKIN_ID]

    unique_ids = list(dict.fromkeys(requested_ids))
    profiles: List[Dict[str, object]] = []
    for requested in unique_ids:
        profile = skins.get(requested)
        if profile is None:
            supported = ", ".join(skins)
            raise SkinCatalogError(
                f"Unsupported skin_id '{requested}'. Supported skin ids: {supported}"
            )
        profiles.append(dict(profile))
    return profiles


def public_skin_catalog(project_root: Path) -> Dict[str, object]:
    path, skins = load_skin_catalog(project_root)
    public_fields = {
        "id",
        "label",
        "category",
        "description",
        "output_kind",
        "backend_mode",
    }
    public_skins: List[Dict[str, object]] = [
        {key: value for key, value in profile.items() if key in public_fields}
        for profile in skins.values()
    ]
    return {
        "default_skin_id": DEFAULT_SKIN_ID,
        "skins": public_skins,
        "catalog_file": path.name,
    }


def resolve_skin_resource(
    project_root: Path,
    profile: Dict[str, object],
    field_name: str,
) -> Optional[str]:
    raw = str(profile.get(field_name) or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = catalog_path(project_root).parent / path
    return str(path.resolve())


def skin_requires_retarget(profile: Dict[str, object]) -> bool:
    return str(profile.get("output_kind") or "") == "retarget"
