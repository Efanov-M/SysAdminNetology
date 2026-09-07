from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Patient, User, UserPatient
from app.repositories.base import Repository


class PatientRepository(Repository[Patient]):
    def visible_to_user_query(self, patient_id: int, user: User) -> Select[tuple[Patient]]:
        query = select(Patient).where(Patient.id == patient_id, Patient.family_id == user.family_id)
        if user.role != "owner":
            query = query.join(UserPatient, UserPatient.patient_id == Patient.id).where(UserPatient.user_id == user.id)
        return query

    def get_visible_to_user(self, patient_id: int, user: User) -> Patient | None:
        return self.db.scalar(self.visible_to_user_query(patient_id, user))


def patients_repository(db: Session) -> PatientRepository:
    return PatientRepository(db)
