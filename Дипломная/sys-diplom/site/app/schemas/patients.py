from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class PatientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    patient_type: str = Field(default="elderly", max_length=32)
    date_of_birth: date | None = None
    notes: str | None = None
    weight: float = 0.0
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class PatientRead(BaseModel):
    id: int
    name: str
    family_id: int
    patient_type: str
    date_of_birth: date | None
    notes: str | None
    weight: float
    emergency_contact_name: str | None
    emergency_contact_phone: str | None

    model_config = ConfigDict(from_attributes=True)
