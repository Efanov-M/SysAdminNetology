from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    id: int
    patient_id: int
    file_path: str
    original_file_path: str
    processed_file_path: str | None
    extracted_text: str | None
    text_content: str | None
    processing_status: str
    original_filename: str
    document_type: str
    doctor_type: str | None
    description: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
