from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InviteCreate(BaseModel):
    login: str = Field(min_length=3, max_length=255)
    patient_id: int | None = None


class InviteRead(BaseModel):
    id: int
    login: str
    email: str
    family_id: int
    role: str
    patient_id: int | None
    token: str
    expires_at: datetime
    used: bool

    model_config = ConfigDict(from_attributes=True)


class ShareReminderSettingsUpdate(BaseModel):
    receive_reminders: bool = False
