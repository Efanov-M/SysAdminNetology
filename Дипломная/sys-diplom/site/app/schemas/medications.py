from datetime import date, time

from pydantic import BaseModel, ConfigDict, Field


class MedicationCreate(BaseModel):
    patient_id: int
    client_id: str | None = None
    name: str = Field(min_length=1, max_length=255)
    dosage: str | None = None
    schedule: str | None = None
    instructions: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool = True
    reminder_enabled: bool = False
    reminder_time: time | None = None
    notes: str | None = None


class MedicationRead(BaseModel):
    id: int
    name: str
    dosage: str | None
    schedule: str | None
    instructions: str | None
    start_date: date | None
    end_date: date | None
    is_active: bool
    reminder_enabled: bool
    reminder_time: time | None
    notes: str | None

    model_config = ConfigDict(from_attributes=True)
