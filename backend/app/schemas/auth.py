import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

# Upper bound on password length: Argon2 cost grows with input size, so an unbounded
# field would let one request tie up a worker thread.
_MAX_PASSWORD_LENGTH = 128
_MIN_PASSWORD_LENGTH = 12

Password = Annotated[
    str, StringConstraints(min_length=_MIN_PASSWORD_LENGTH, max_length=_MAX_PASSWORD_LENGTH)
]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: Password


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    # No minimum here: the policy applies when choosing a password, and an old shorter
    # password must still be able to fail with the normal "incorrect" message.
    password: str = Field(max_length=_MAX_PASSWORD_LENGTH)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth2 scheme name, not a credential
    expires_in: int = Field(description="Access token lifetime in seconds.")
