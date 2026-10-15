from pydantic import BaseModel


class Contact(BaseModel):
    """Контакты кандидата из answer-vault. Все поля Optional (§3: отсутствующее не заявляем)."""
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None


class SelectedBullet(BaseModel):
    aid: str
    source_text: str        # cloud_achievement.text — verbatim
    source_metric: str = ""  # cloud_achievement.metric — canonical numbers live here
    safe_use: str = ""


class SelectedPosition(BaseModel):
    pid: str
    company: str
    title: str
    start: str = ""
    end: str = ""
    location: str = ""
    bullets: list[SelectedBullet] = []


class SkillGroup(BaseModel):
    category: str            # skill|certification|education|language
    items: list[str] = []    # rendered verbatim from cloud_skill (name [— framing])


class ResumeSelection(BaseModel):
    application_id: str
    headline: str
    candidate_name: str = ""
    contact: Contact | None = None
    summary: str = ""
    positions: list[SelectedPosition] = []
    skill_groups: list[SkillGroup] = []


class PhrasingRequest(BaseModel):
    """Returned by /resume/pull. n8n rephrases each bullet's source_text strictly from source."""
    application_id: str
    headline: str
    jd_summary: str = ""       # детерминированная JD-выжимка для контекстного фразинга (§4.1)
    bullets: list[dict] = []   # [{aid, source_text, source_metric}]


class PhrasedBullet(BaseModel):
    aid: str
    phrased_text: str


class ResumePhrasing(BaseModel):
    """Posted to /resume/apply (n8n structured output, or verbatim echo for the floor)."""
    application_id: str
    bullets: list[PhrasedBullet] = []
