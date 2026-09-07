from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LabObservationCreate(BaseModel):
    patient_id: int
    test_name: str = Field(min_length=1, max_length=255)
    value: float
    unit: str | None = None
    panel_name: str | None = None
    reference_low: float | None = None
    reference_high: float | None = None
    reference_text: str | None = None


class LabResultRead(BaseModel):
    id: int
    patient_id: int
    panel_name: str | None
    test_name: str
    value: float
    unit: str | None
    reference_low: float | None
    reference_high: float | None
    reference_text: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
