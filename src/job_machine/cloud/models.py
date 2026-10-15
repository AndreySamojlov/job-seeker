"""Модели Experience Cloud: позиции, достижения, скиллы + контейнер."""

from pydantic import BaseModel, Field


class CloudPosition(BaseModel):
    pid: str
    company: str
    title: str
    start: str
    end: str
    location: str = ""
    summary: str = ""


class CloudAchievement(BaseModel):
    aid: str
    pid: str
    text: str
    metric: str = ""
    status: str = ""
    claims: str = ""
    safe_use: str = ""


class CloudSkill(BaseModel):
    name: str
    category: str
    framing: str = ""
    evidence: str = ""
    safe_use: str = ""


class ExperienceCloud(BaseModel):
    positions: list[CloudPosition] = Field(default_factory=list)
    achievements: list[CloudAchievement] = Field(default_factory=list)
    skills: list[CloudSkill] = Field(default_factory=list)
