"""【实验功能，未应用于实际生产逻辑链路】InterGen 结构化动作规划原型。

本模块定义可审计的规划 schema，将计划压缩为面向 CLIP 的短提示词，并可选调用
OpenAI-compatible API。当前生产前端不发送规划字段，默认请求不会调用本模块；
它也不参与生产结果的物理选优，仅供显式 API 实验和离线对照使用。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, root_validator, validator


class MotionPlannerError(RuntimeError):
    """Raised when a required motion-planning request cannot be completed."""


def _clean_text(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.strip(" \t\r\n\"'“”‘’")


class MotionPhase(BaseModel):
    phase: str = Field(..., min_length=1, max_length=48)
    time: Tuple[float, float]
    motion: str = Field(..., min_length=3, max_length=240)
    body_parts: List[str] = Field(default_factory=list, max_items=8)

    @validator("phase", "motion")
    def clean_required_text(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("motion phase text cannot be empty")
        return cleaned

    @validator("body_parts", each_item=True)
    def clean_body_part(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("body part cannot be empty")
        return cleaned

    @validator("time")
    def validate_time_range(cls, value: Tuple[float, float]) -> Tuple[float, float]:
        start, end = float(value[0]), float(value[1])
        if not 0.0 <= start < end <= 1.0:
            raise ValueError("phase time must satisfy 0 <= start < end <= 1")
        return round(start, 6), round(end, 6)


class InteractionPlan(BaseModel):
    facing: Optional[bool] = None
    physical_contact: Optional[bool] = None
    relative_distance: str = Field(default="medium", max_length=24)
    relation: str = Field(default="", max_length=160)

    @validator("relative_distance")
    def validate_distance(cls, value: str) -> str:
        cleaned = _clean_text(value).lower() or "medium"
        allowed = {"close", "medium", "far", "changing"}
        if cleaned not in allowed:
            raise ValueError(f"relative_distance must be one of {sorted(allowed)}")
        return cleaned

    @validator("relation")
    def clean_relation(cls, value: str) -> str:
        return _clean_text(value)


class MotionPlan(BaseModel):
    action: str = Field(..., min_length=2, max_length=120)
    duration_seconds: float = Field(default=6.0, ge=1.0, le=12.0)
    actor_a: List[MotionPhase] = Field(..., min_items=1, max_items=5)
    actor_b: List[MotionPhase] = Field(..., min_items=1, max_items=5)
    interaction: InteractionPlan = Field(default_factory=InteractionPlan)

    @validator("action")
    def clean_action(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("action cannot be empty")
        return cleaned

    @root_validator
    def validate_phase_order(cls, values: Dict[str, object]) -> Dict[str, object]:
        for actor_key in ("actor_a", "actor_b"):
            phases = list(values.get(actor_key) or [])
            starts = [phase.time[0] for phase in phases]
            if starts != sorted(starts):
                raise ValueError(f"{actor_key} phases must be ordered by start time")
        return values


@dataclass(frozen=True)
class PlannerSettings:
    provider: str
    model: str
    base_url: str
    api_key: str
    timeout_seconds: float
    max_prompt_words: int

    @classmethod
    def from_env(cls, model_override: Optional[str] = None) -> "PlannerSettings":
        provider = os.getenv("INTERGEN_MOTION_PLANNER_PROVIDER", "dashscope").strip().lower()
        if provider not in {"dashscope", "deepseek", "openai-compatible"}:
            raise MotionPlannerError(
                "INTERGEN_MOTION_PLANNER_PROVIDER must be dashscope, deepseek, or openai-compatible"
            )

        if provider == "dashscope":
            default_base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            fallback_key = os.getenv("DASHSCOPE_API_KEY", "")
            default_model = "qwen-plus"
        elif provider == "deepseek":
            default_base_url = "https://api.deepseek.com"
            fallback_key = os.getenv("DEEPSEEK_API_KEY", "")
            default_model = "deepseek-v4-flash"
        else:
            default_base_url = ""
            fallback_key = ""
            default_model = ""

        model = (model_override or os.getenv("INTERGEN_MOTION_PLANNER_MODEL", default_model)).strip()
        base_url = os.getenv("INTERGEN_MOTION_PLANNER_BASE_URL", default_base_url).strip()
        api_key = os.getenv("INTERGEN_MOTION_PLANNER_API_KEY", fallback_key).strip()
        try:
            timeout_seconds = max(
                5.0,
                min(float(os.getenv("INTERGEN_MOTION_PLANNER_TIMEOUT_SEC", "90")), 300.0),
            )
            max_prompt_words = max(
                24,
                min(int(os.getenv("INTERGEN_MOTION_PLANNER_MAX_PROMPT_WORDS", "48")), 64),
            )
        except ValueError as exc:
            raise MotionPlannerError(
                "Motion planner timeout and max prompt words must be numeric"
            ) from exc

        if not model:
            raise MotionPlannerError("Motion planner model is not configured")
        if not base_url:
            raise MotionPlannerError("Motion planner base URL is not configured")
        if not api_key:
            raise MotionPlannerError("Motion planner API key is not configured")

        return cls(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_prompt_words=max_prompt_words,
        )


def _strip_json_fence(content: str) -> str:
    text = str(content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_motion_plan(content: str) -> MotionPlan:
    try:
        payload = json.loads(_strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise MotionPlannerError(f"Motion planner returned invalid JSON: {exc}") from exc
    try:
        return MotionPlan.parse_obj(payload)
    except Exception as exc:
        raise MotionPlannerError(f"Motion planner JSON failed schema validation: {exc}") from exc


_CLIP_BODY_TOKEN_LIMIT = 75
_MIN_PHASE_MOTION_WORDS = 3
_INCOMPLETE_TAIL_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "from",
    "of",
    "the",
    "to",
    "toward",
    "with",
}


@dataclass
class _PhaseCaption:
    label: str
    motion_words: List[str]
    word_count: int
    expansion_blocked: bool = False


@lru_cache(maxsize=1)
def _openai_clip_tokenizer():
    """Return the same OpenAI CLIP BPE tokenizer used by InterGen."""

    try:
        from clip.clip import _tokenizer
    except Exception as exc:
        raise MotionPlannerError(f"OpenAI CLIP tokenizer is unavailable: {exc}") from exc
    return _tokenizer


@lru_cache(maxsize=1024)
def _clip_body_token_count(text: str) -> int:
    return len(_openai_clip_tokenizer().encode(str(text or "")))


def _motion_fragment(words: List[str], word_count: int) -> str:
    kept = list(words[: max(1, word_count)])
    while len(kept) > 1 and kept[-1].lower().rstrip(",.;:") in _INCOMPLETE_TAIL_WORDS:
        kept.pop()
    return " ".join(kept).rstrip(",.;:")


def _phase_captions(phases: List[MotionPhase]) -> List[_PhaseCaption]:
    captions: List[_PhaseCaption] = []
    for phase in phases:
        motion_words = _clean_text(phase.motion).rstrip(".").split()
        if not motion_words:
            continue
        captions.append(
            _PhaseCaption(
                label=_clean_text(phase.phase).rstrip(".：:"),
                motion_words=motion_words,
                word_count=min(_MIN_PHASE_MOTION_WORDS, len(motion_words)),
            )
        )
    return captions


def _render_actor(captions: List[_PhaseCaption]) -> str:
    return "; then ".join(
        f"{caption.label}: {_motion_fragment(caption.motion_words, caption.word_count)}"
        for caption in captions
    )


def _render_intergen_prompt(
    prefix: str,
    actor_a: List[_PhaseCaption],
    actor_b: List[_PhaseCaption],
    relation: str = "",
) -> str:
    interaction = prefix
    if relation:
        interaction += f" {_clean_text(relation).rstrip('.')}."
    prompt = f"{interaction} Person A {_render_actor(actor_a)}. Person B {_render_actor(actor_b)}."
    return re.sub(r"\s+", " ", prompt).strip()


def compile_intergen_prompt(plan: MotionPlan, max_words: int = 48) -> str:
    """Compile every phase into a caption within CLIP's 75-token text budget."""

    max_words = max(24, min(int(max_words), 64))
    interaction = plan.interaction
    relation_bits: List[str] = []
    if interaction.facing is True:
        relation_bits.append("face each other")
    elif interaction.facing is False:
        relation_bits.append("do not face each other")
    distance_phrases = {
        "close": "within arm's reach",
        "medium": "about one step apart",
        "far": "two meters apart and maintain spacing",
        "changing": "with small controlled changes in distance",
    }
    relation_bits.append(distance_phrases[interaction.relative_distance])
    if interaction.physical_contact is True:
        relation_bits.append("with physical contact")
    elif interaction.physical_contact is False:
        relation_bits.append("without physical contact")

    prefix = "Two people " + " ".join(relation_bits) + "."
    actor_a = _phase_captions(plan.actor_a)
    actor_b = _phase_captions(plan.actor_b)
    all_phases = actor_a + actor_b
    prompt = _render_intergen_prompt(prefix, actor_a, actor_b)

    # Every phase receives a short motion fragment first. If even that initial
    # coverage is too large, shorten the longest fragments evenly, never by
    # deleting an entire phase.
    while _clip_body_token_count(prompt) > _CLIP_BODY_TOKEN_LIMIT:
        reducible = [phase for phase in all_phases if phase.word_count > 1]
        if not reducible:
            raise MotionPlannerError(
                "All motion phases cannot fit within CLIP's 75 body-token limit"
            )
        max(reducible, key=lambda phase: phase.word_count).word_count -= 1
        prompt = _render_intergen_prompt(prefix, actor_a, actor_b)

    # The free-form relation is optional and is admitted only after every
    # phase has representation and only when it fits the real CLIP budget.
    relation = _clean_text(plan.interaction.relation).rstrip(".")
    if relation:
        candidate = _render_intergen_prompt(prefix, actor_a, actor_b, relation)
        if _clip_body_token_count(candidate) <= _CLIP_BODY_TOKEN_LIMIT:
            prompt = candidate
        else:
            relation = ""

    # max_words remains a compatible soft target for detail expansion. Phase
    # coverage may exceed it, but no expansion may exceed either that target
    # or CLIP's hard body-token limit.
    expansion_word_limit = max(max_words, len(prompt.split()))
    while True:
        expanded = False
        for phase in all_phases:
            if phase.expansion_blocked or phase.word_count >= len(phase.motion_words):
                continue
            previous_count = phase.word_count
            phase.word_count += 1
            candidate = _render_intergen_prompt(prefix, actor_a, actor_b, relation)
            if (
                len(candidate.split()) <= expansion_word_limit
                and _clip_body_token_count(candidate) <= _CLIP_BODY_TOKEN_LIMIT
            ):
                prompt = candidate
                expanded = True
            else:
                phase.word_count = previous_count
                phase.expansion_blocked = True
        if not expanded:
            break

    if _clip_body_token_count(prompt) > _CLIP_BODY_TOKEN_LIMIT:
        raise MotionPlannerError("Compiled motion prompt exceeds CLIP's 75 body-token limit")
    return prompt


def planner_messages(original_text: str, translated_text: str) -> List[Dict[str, str]]:
    schema = MotionPlan.schema_json(indent=2)
    system = (
        "You are a two-person 3D human motion planner. Return one JSON object only. "
        "Decompose the requested motion into short, executable body-motion phases for actor A and actor B. "
        "Use normalized time ranges between 0 and 1, preserve role ordering, describe human body proxies for "
        "props, and never claim that a racket, ball, or other prop will be generated. JSON must match this schema:\n"
        f"{schema}"
    )
    user = (
        f"Original description: {_clean_text(original_text)}\n"
        f"English translation: {_clean_text(translated_text)}\n"
        "Create the most concise physically executable two-person motion plan."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def request_motion_plan(
    original_text: str,
    translated_text: str,
    settings: PlannerSettings,
) -> MotionPlan:
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.timeout_seconds,
        )
        completion = client.chat.completions.create(
            model=settings.model,
            messages=planner_messages(original_text, translated_text),
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content
        if not content:
            raise MotionPlannerError("Motion planner returned empty content")
        return parse_motion_plan(content)
    except MotionPlannerError:
        raise
    except Exception as exc:
        raise MotionPlannerError(f"Motion planner API request failed: {exc}") from exc
