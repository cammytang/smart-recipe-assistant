import re
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    username: str
    password: SecretStr

    @field_validator('username')
    @classmethod
    def normalize_username(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[a-z0-9_]{3,64}', value):
            raise ValueError('Invalid username')
        return value

    @field_validator('password')
    @classmethod
    def validate_password(cls, value):
        password = value.get_secret_value()
        # Printable ASCII includes spaces and symbols. Do not trim or transform.
        if not 8 <= len(password) <= 128 or not re.fullmatch(r'[\x20-\x7e]+', password):
            raise ValueError('Password must contain 8-128 printable ASCII characters')
        return value


class UserResponse(BaseModel):
    id: UUID
    username: str


class RegisteredUser(UserResponse):
    created_at: datetime


class SessionResponse(BaseModel):
    user: UserResponse
    expires_at: datetime


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
