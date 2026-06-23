"""API DTOs for the core app."""

import msgspec


class LoginPayload(msgspec.Struct, frozen=True):
    """Credentials for JWT login."""

    username: str
    password: str


class RefreshTokenPayload(msgspec.Struct, frozen=True):
    """Refresh token request body."""

    refresh_token: str


class TokenPairPayload(msgspec.Struct, frozen=True):
    """Access + refresh JWT pair."""

    access_token: str
    refresh_token: str


class UserMePayload(msgspec.Struct, frozen=True):
    """Authenticated user summary."""

    id: int
    username: str
    role: str


class EnumOptionPayload(msgspec.Struct, frozen=True):
    """One option from a TextChoices enum."""

    value: str
    label: str


class EnumsPayload(msgspec.Struct, frozen=True):
    """All API-facing enum registries for frontend forms."""

    enums: dict[str, list[EnumOptionPayload]]
