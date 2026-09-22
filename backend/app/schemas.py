"""请求 / 响应 Pydantic 模型。"""
from pydantic import BaseModel, Field, field_validator


class EventCreate(BaseModel):
    name: str = Field(default="秘密赠礼", max_length=200)
    participants: list[str] = Field(default_factory=list)
    # 每项为两个参与者名字 [a, b]，表示 a、b 互不能抽中对方
    forbidden_pairs: list[list[str]] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("活动名称不能为空")
        return v

    @field_validator("participants")
    @classmethod
    def _strip_participants(cls, v: list[str]) -> list[str]:
        cleaned = [name.strip() for name in v]
        if any(not name for name in cleaned):
            raise ValueError("参与者名字不能为空")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("参与者名字不能重复")
        return cleaned

    @field_validator("forbidden_pairs")
    @classmethod
    def _check_pairs(cls, v: list[list[str]]) -> list[list[str]]:
        for pair in v:
            if len(pair) != 2 or not pair[0].strip() or not pair[1].strip():
                raise ValueError("每个禁配关系必须是两个不同的参与者名字")
            if pair[0].strip() == pair[1].strip():
                raise ValueError("禁配关系必须是两个不同的参与者")
        return v


class ParticipantCreate(BaseModel):
    name: str = Field(max_length=100)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("参与者名字不能为空")
        return v


class PairsCreate(BaseModel):
    # 批量设置禁配关系，整体覆盖；每项 [a, b] 为两个参与者名字
    pairs: list[list[str]] = Field(default_factory=list)

    @field_validator("pairs")
    @classmethod
    def _check_pairs(cls, v: list[list[str]]) -> list[list[str]]:
        for pair in v:
            if len(pair) != 2 or not pair[0].strip() or not pair[1].strip():
                raise ValueError("每个禁配关系必须是两个不同的参与者名字")
            if pair[0].strip() == pair[1].strip():
                raise ValueError("禁配关系必须是两个不同的参与者")
        return v
