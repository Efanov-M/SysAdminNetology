from __future__ import annotations

from datetime import UTC, date, datetime, time

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Family(Base):
    __tablename__ = "families"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    users: Mapped[list["User"]] = relationship(
        back_populates="family",
        foreign_keys="User.family_id",
    )
    patients: Mapped[list["Patient"]] = relationship(back_populates="family", cascade="all, delete-orphan")
    invites: Mapped[list["Invite"]] = relationship(back_populates="family", cascade="all, delete-orphan")
    owner: Mapped["User | None"] = relationship(
        foreign_keys=[owner_id],
        post_update=True,
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    login: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member", index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    notification_channels: Mapped[list] = mapped_column(JSON, default=lambda: ["log"])
    matrix_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matrix_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    matrix_notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    family: Mapped["Family"] = relationship(back_populates="users", foreign_keys=[family_id])
    created_patients: Mapped[list["Patient"]] = relationship(
        back_populates="created_by_user",
        foreign_keys="Patient.created_by_user_id",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    patient_links: Mapped[list["UserPatient"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    patient_comments: Mapped[list["PatientComment"]] = relationship(
        back_populates="author", cascade="all, delete-orphan"
    )
    patient_checkins: Mapped[list["PatientCheckin"]] = relationship(
        back_populates="author", cascade="all, delete-orphan", foreign_keys="PatientCheckin.user_id"
    )
    invites: Mapped[list["Invite"]] = relationship(
        back_populates="invited_user",
        foreign_keys="Invite.used_by_user_id",
    )
    matrix_link_tokens: Mapped[list["MatrixLinkToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    matrix_profile: Mapped["MatrixProfile | None"] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    alert_settings: Mapped[list["AlertSettings"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def account_name(self) -> str:
        return self.login

    @property
    def canonical_matrix_user_id(self) -> str | None:
        return (self.matrix_user_id or self.matrix_id or "").strip() or None


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    patient_type: Mapped[str] = mapped_column(String(32), default="elderly", index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(default=0.0)
    blood_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    chronic_diseases: Mapped[str | None] = mapped_column(Text, nullable=True)
    permanent_medications: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contacts: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    family: Mapped["Family"] = relationship(back_populates="patients")
    created_by_user: Mapped["User | None"] = relationship(
        back_populates="created_patients",
        foreign_keys=[created_by_user_id],
    )
    observations: Mapped[list["Observation"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    lab_results: Mapped[list["LabResult"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    medications: Mapped[list["Medication"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    emergency_info: Mapped["EmergencyInfo | None"] = relationship(
        back_populates="patient", cascade="all, delete-orphan", uselist=False
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    shares: Mapped[list["PatientShare"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    comments: Mapped[list["PatientComment"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    reminders: Mapped[list["PatientReminder"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    care_events: Mapped[list["CareEvent"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    checkins: Mapped[list["PatientCheckin"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    growth_records: Mapped[list["GrowthRecord"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    vaccine_records: Mapped[list["VaccineRecord"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    health_events: Mapped[list["HealthEvent"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    child_medications: Mapped[list["ChildMedication"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )
    user_links: Mapped[list["UserPatient"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    alert_settings: Mapped[list["AlertSettings"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    emergency_events: Mapped[list["EmergencyEvent"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    alert_rules: Mapped[list["AlertRule"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    alert_events: Mapped[list["AlertEvent"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    planner_reminders: Mapped[list["Reminder"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    reminder_events: Mapped[list["ReminderEvent"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    inbox_events: Mapped[list["InboxEvent"]] = relationship(
        back_populates="patient",
        cascade="all, delete-orphan",
    )


class UserPatient(Base):
    __tablename__ = "user_patients"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    user: Mapped["User"] = relationship(back_populates="patient_links")
    patient: Mapped["Patient"] = relationship(back_populates="user_links")


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    login: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    family_id: Mapped[int] = mapped_column(ForeignKey("families.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    used_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    family: Mapped["Family"] = relationship(back_populates="invites")
    patient: Mapped["Patient | None"] = relationship()
    invited_user: Mapped["User | None"] = relationship(back_populates="invites", foreign_keys=[used_by_user_id])

    @property
    def account_name(self) -> str:
        return self.login


class MatrixLinkToken(Base):
    __tablename__ = "matrix_link_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    user: Mapped["User"] = relationship(back_populates="matrix_link_tokens")


class MatrixProfile(Base):
    __tablename__ = "matrix_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    matrix_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    matrix_room_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active_patient_id: Mapped[int | None] = mapped_column(ForeignKey("patients.id", ondelete="SET NULL"), nullable=True, index=True)
    link_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_linked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    user: Mapped["User"] = relationship(back_populates="matrix_profile")

    @property
    def linked(self) -> bool:
        return bool(self.is_linked)


class AlertSettings(Base):
    __tablename__ = "alert_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    matrix_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    matrix_room_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extra_recipients: Mapped[list] = mapped_column(JSON, default=list)
    blood_pressure_sys_threshold: Mapped[int | None] = mapped_column(nullable=True)
    blood_pressure_dia_threshold: Mapped[int | None] = mapped_column(nullable=True)
    blood_sugar_threshold: Mapped[float | None] = mapped_column(nullable=True)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    user: Mapped["User"] = relationship(back_populates="alert_settings")
    patient: Mapped["Patient"] = relationship(back_populates="alert_settings")


class PatientShare(Base):
    __tablename__ = "patient_shares"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    viewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="read_only")
    receive_reminders: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    patient: Mapped["Patient"] = relationship(back_populates="shares")
    viewer: Mapped["User"] = relationship()


class PatientComment(Base):
    __tablename__ = "patient_comments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(50), default="note", index=True)
    text: Mapped[str] = mapped_column(Text)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship(back_populates="patient_comments")


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    type: Mapped[str] = mapped_column(String(50), index=True)
    value: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="observations")


class Medication(Base):
    __tablename__ = "medications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    dosage: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schedule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reminder_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    patient: Mapped["Patient"] = relationship(back_populates="medications")


class EmergencyInfo(Base):
    __tablename__ = "emergency_info"

    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True)
    blood_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    diagnoses: Mapped[str | None] = mapped_column(Text, nullable=True)
    emergency_contacts: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    patient: Mapped["Patient"] = relationship(back_populates="emergency_info")


class PatientReminder(Base):
    __tablename__ = "patient_reminders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    reminder_type: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(String(255))
    time_of_day: Mapped[time] = mapped_column(Time, index=True)
    repeat_mode: Mapped[str] = mapped_column(String(20), default="daily")
    one_time_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    weekdays: Mapped[list] = mapped_column(JSON, default=list)
    recipient_mode: Mapped[str] = mapped_column(String(20), default="family")
    recipient_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    patient: Mapped["Patient"] = relationship(back_populates="reminders")
    recipient_user: Mapped["User | None"] = relationship()


class CareEvent(Base):
    __tablename__ = "care_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="Визит к врачу")
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    doctor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    place: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    remind_day_before: Mapped[bool] = mapped_column(Boolean, default=True)
    remind_hours_before: Mapped[int | None] = mapped_column(nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive)

    patient: Mapped["Patient"] = relationship(back_populates="care_events")


class PatientCheckin(Base):
    __tablename__ = "patient_checkins"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    acknowledged_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    checkin_type: Mapped[str] = mapped_column(String(50), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    acknowledgment_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="checkins")
    author: Mapped["User | None"] = relationship(back_populates="patient_checkins", foreign_keys=[user_id])


class GrowthRecord(Base):
    __tablename__ = "growth_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    height: Mapped[float | None] = mapped_column(nullable=True)
    weight: Mapped[float | None] = mapped_column(nullable=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="growth_records")


class VaccineRecord(Base):
    __tablename__ = "vaccine_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="vaccine_records")


class HealthEvent(Base):
    __tablename__ = "health_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    temperature: Mapped[float | None] = mapped_column(nullable=True)
    symptoms: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="health_events")


class ChildMedication(Base):
    __tablename__ = "child_medications"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    dosage: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="child_medications")


class LabResult(Base):
    __tablename__ = "lab_results"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    panel_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    test_name: Mapped[str] = mapped_column(String(255), index=True)
    value: Mapped[float] = mapped_column()
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_low: Mapped[float | None] = mapped_column(nullable=True)
    reference_high: Mapped[float | None] = mapped_column(nullable=True)
    reference_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="lab_results")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str] = mapped_column(String(500))
    original_file_path: Mapped[str] = mapped_column(String(500))
    processed_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[str] = mapped_column(String(20), default="lab", index=True)
    doctor_type: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="documents")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    user: Mapped[User | None] = relationship(back_populates="audit_logs")


class MedicationInfoCache(Base):
    __tablename__ = "medication_info_cache"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    query: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    payload: Mapped[list] = mapped_column(JSON, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)


class DrugCache(Base):
    __tablename__ = "drug_cache"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    raw_name: Mapped[str] = mapped_column(String(255), index=True)
    dosage_forms: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, index=True)


class EmergencyEvent(Base):
    __tablename__ = "emergency_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20), default="manual", index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    patient: Mapped["Patient"] = relationship(back_populates="emergency_events")


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    systolic_max: Mapped[int | None] = mapped_column(nullable=True)
    diastolic_max: Mapped[int | None] = mapped_column(nullable=True)
    glucose_max: Mapped[float | None] = mapped_column(nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, nullable=True)
    escalation_targets: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="alert_rules")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True, index=True)
    value: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="alert_events")
    rule: Mapped["AlertRule | None"] = relationship()


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32), index=True)
    time: Mapped[time] = mapped_column(Time, index=True)
    repeat_type: Mapped[str] = mapped_column(String(20), default="daily")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="planner_reminders")
    events: Mapped[list["ReminderEvent"]] = relationship(back_populates="reminder", cascade="all, delete-orphan")

    @property
    def reminder_type(self) -> str:
        return self.type

    @property
    def time_of_day(self) -> time:
        return self.time

    @property
    def repeat_mode(self) -> str:
        return self.repeat_type


class ReminderEvent(Base):
    __tablename__ = "reminder_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    reminder_id: Mapped[int] = mapped_column(ForeignKey("reminders.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    reminder: Mapped["Reminder"] = relationship(back_populates="events")
    patient: Mapped["Patient"] = relationship(back_populates="reminder_events")


class InboxEvent(Base):
    __tablename__ = "inbox_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(20), index=True)
    source_id: Mapped[int] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow_naive, index=True)

    patient: Mapped["Patient"] = relationship(back_populates="inbox_events")
