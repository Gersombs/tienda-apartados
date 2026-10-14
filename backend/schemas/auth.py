from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from core.auth import validate_admin_email


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(StrictSchema):
    email: str
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_admin_email(value)


class PasswordChangeRequest(StrictSchema):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class AdminSessionResponse(BaseModel):
    id: str
    email: EmailStr
    name: str | None = None
    role: str = "admin"
    last_login: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


UserResponse = AdminSessionResponse


class LoginResponse(BaseModel):
    user: AdminSessionResponse
