from datetime import time

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6)


class UserRead(BaseModel):
    id: int
    login: str
    email: str
    family_id: int
    role: str
    timezone: str
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    notification_channels: list[str]
    matrix_id: str | None
    matrix_user_id: str | None
    matrix_notifications_enabled: bool

    model_config = ConfigDict(from_attributes=True)


class UserPreferencesUpdate(BaseModel):
    timezone: str = Field(default="Europe/Moscow", max_length=64)
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    notification_channels: list[str] = Field(default_factory=lambda: ["log"])
    matrix_id: str | None = Field(default=None, max_length=255)
    matrix_user_id: str | None = Field(default=None, max_length=255)
    matrix_notifications_enabled: bool = False
