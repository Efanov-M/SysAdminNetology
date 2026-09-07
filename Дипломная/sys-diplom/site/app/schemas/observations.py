from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BloodPressureCreate(BaseModel):
    patient_id: int
    client_id: str | None = None
    sys: int = Field(ge=40, le=300)
    dia: int = Field(ge=30, le=200)
    pulse: int | None = Field(default=None, ge=20, le=250)


class NumericObservationCreate(BaseModel):
    patient_id: int
    client_id: str | None = None
    type: str
    value: float
    unit: str | None = None
    label: str | None = None


class ObservationRead(BaseModel):
    id: int
    patient_id: int
    type: str
    value: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
