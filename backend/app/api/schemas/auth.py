import re
from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from app.api.schemas.deck import CamelModel

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(CamelModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)
    invite_code: str = Field(min_length=8, max_length=40)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        if not _EMAIL.match(value):
            raise ValueError("邮箱格式不正确")
        return value.lower()

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("密码需同时包含字母与数字")
        return value


class LoginRequest(CamelModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return value.strip().lower()


class UserProfile(CamelModel):
    id: UUID
    email: str
    display_name: str | None = None
    status: str
    created_at: datetime


class AuthResponse(CamelModel):
    user: UserProfile
    expires_at: datetime