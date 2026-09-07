from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PatientCommentCreate(BaseModel):
    category: str = Field(default="note", max_length=50)
    text: str = Field(min_length=1, max_length=5000)


class PatientCommentRead(BaseModel):
    id: int
    patient_id: int
    user_id: int
    category: str
    text: str
    pinned: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
