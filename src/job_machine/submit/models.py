from pydantic import BaseModel


class SubmitRunSummary(BaseModel):
    pulled: int = 0
    submitted: int = 0
    blocked: int = 0
    errors: int = 0
