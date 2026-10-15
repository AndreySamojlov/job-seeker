from pydantic import BaseModel


class ApprovalRecord(BaseModel):
    approval_id: str
    application_id: str
    payload_hash: str
    approval_status: str        # 'pending' | 'approved' | 'rejected'
    approval_token: str | None = None
    approved_at: str | None = None   # ISO datetime
    expires_at: str | None = None    # ISO datetime
