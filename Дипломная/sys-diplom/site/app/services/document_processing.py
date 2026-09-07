from app.models import Document


def build_uploaded_document(
    *,
    patient_id: int,
    stored_path: str,
    original_filename: str,
    description: str | None,
    document_type: str = "lab",
    doctor_type: str | None = None,
) -> Document:
    return Document(
        patient_id=patient_id,
        file_path=stored_path,
        original_file_path=stored_path,
        processed_file_path=None,
        extracted_text=None,
        processing_status="uploaded",
        original_filename=original_filename,
        document_type=document_type,
        doctor_type=doctor_type,
        description=description,
    )


def get_document_active_path(document: Document) -> str:
    return document.processed_file_path or document.original_file_path or document.file_path


def cleanup_document_files(document: Document) -> list[str]:
    paths: list[str] = []
    for candidate in [document.original_file_path, document.processed_file_path]:
        if candidate and candidate not in paths:
            paths.append(candidate)
    if document.file_path and document.file_path not in paths:
        paths.append(document.file_path)
    return paths


def queue_document_processing(document: Document) -> dict:
    return {
        "document_id": document.id,
        "status": document.processing_status,
        "next_step": "convert_or_parse",
    }
