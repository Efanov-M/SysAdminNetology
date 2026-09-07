from pydantic import BaseModel, ConfigDict, Field


class EmergencyInfoUpdate(BaseModel):
    blood_type: str | None = Field(default=None, max_length=32)
    allergies: str | None = None
    diagnoses: str | None = None
    permanent_medications: str | None = None
    emergency_contacts: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None


class EmergencyInfoRead(BaseModel):
    patient_id: int
    blood_type: str | None
    allergies: str | None
    diagnoses: str | None
    permanent_medications: str | None
    emergency_contacts: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None

    model_config = ConfigDict()
