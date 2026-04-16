"""
wancontrol/auth.py
~~~~~~~~~~~~~~~~~~
Authentication and authorisation layer for WANControl v2.

Provides user management, bcrypt password hashing, JWT access tokens,
and SHA-256-hashed API tokens.  No Flask dependency — this is pure logic
that the Flask layer (Phase 6) will call.

Usage::

    from wancontrol.auth import Auth, AuthError
    auth = Auth(db=db, server_cfg=cfg.server)
    auth.ensure_admin_exists()            # first-run setup
    pair = auth.authenticate(user, pwd)   # returns TokenPair
    principal = auth.verify_token(pair.access_token)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass

import bcrypt
import jwt as pyjwt

from wancontrol.config import ServerConfig
from wancontrol.database import ApiTokenRow, Database, UserRow

logger = logging.getLogger(__name__)

# ── Module-level constants ─────────────────────────────────────────────────────

BCRYPT_ROUNDS: int = 12
JWT_ALGORITHM: str = "HS256"

# Pre-computed dummy hash used in authenticate() to prevent timing attacks.
# Must use the same cost factor as real password hashes.
_DUMMY_HASH: bytes = bcrypt.hashpw(b"wancontrol-dummy", bcrypt.gensalt(rounds=BCRYPT_ROUNDS))

# ── Exceptions ────────────────────────────────────────────────────────────────


class AuthError(Exception):
    """
    Raised on authentication / authorisation failures.

    Always carries a user-safe message (no internal detail) and a
    machine-readable code.

    Valid codes::

        invalid_credentials  wrong username or password
        token_expired        JWT or API token past its expiry
        token_invalid        malformed token or bad signature
        token_revoked        API token explicitly revoked
        insufficient_role    caller's role is too low
        user_inactive        account has been deactivated
        user_not_found       user_id does not exist
        username_taken       username already registered
        weak_password        password shorter than minimum length
    """

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UserPrincipal:
    """Represents an authenticated identity — from JWT, session, or API token."""

    user_id: int
    username: str
    role: str    # "admin" | "operator" | "viewer"
    source: str  # "jwt" | "session" | "api_token"


@dataclass(frozen=True)
class TokenPair:
    """Returned on successful login."""

    access_token: str  # signed JWT
    token_type: str    # always "bearer"
    expires_in: int    # seconds until expiry


# ── Auth class ────────────────────────────────────────────────────────────────


class Auth:
    """
    Authentication and authorisation logic for WANControl v2.

    Receives a :class:`~wancontrol.database.Database` and a
    :class:`~wancontrol.config.ServerConfig` at construction.
    Thread-safe: all persistent state goes through the ``Database`` layer.
    """

    ROLE_HIERARCHY: dict[str, int] = {
        "viewer": 1,
        "operator": 2,
        "admin": 3,
    }
    _VALID_ROLES: frozenset[str] = frozenset(ROLE_HIERARCHY)
    _MIN_PASSWORD_LEN: int = 12

    def __init__(self, db: Database, server_cfg: ServerConfig) -> None:
        self._db = db
        self._server_cfg = server_cfg

    # ── Internal helpers ───────────────────────────────────────────────────

    def _hash_password(self, password: str) -> str:
        """Hash *password* with bcrypt; returns the hash as a UTF-8 string."""
        return bcrypt.hashpw(
            password.encode(),
            bcrypt.gensalt(rounds=BCRYPT_ROUNDS),
        ).decode()

    def _check_password(self, password: str, hashed: str) -> bool:
        """Return ``True`` if *password* matches the stored bcrypt *hashed* value."""
        return bcrypt.checkpw(password.encode(), hashed.encode())

    # ── User management ────────────────────────────────────────────────────

    def create_user(
        self,
        username: str,
        password: str,
        role: str,
        created_by_user_id: int | None = None,
    ) -> int:
        """
        Hash *password* with bcrypt and create a new user in the database.

        Raises :class:`AuthError` ``("username_taken")`` if the username
        already exists.
        Raises :class:`AuthError` ``("weak_password")`` if *password* is
        shorter than 12 characters.
        Logs the creation event to ``controller_events``.
        Returns the new ``user_id``.
        """
        if len(password) < self._MIN_PASSWORD_LEN:
            raise AuthError(
                f"Password must be at least {self._MIN_PASSWORD_LEN} characters.",
                "weak_password",
            )
        if self._db.get_user_by_username(username) is not None:
            raise AuthError(
                f"Username {username!r} is already taken.",
                "username_taken",
            )

        password_hash = self._hash_password(password)
        user_id = self._db.create_user(username, password_hash, role)
        self._db.log_event(
            level="INFO",
            component="auth",
            message=f"User {username!r} created with role {role!r}.",
            user_id=created_by_user_id,
        )
        logger.info(
            "User %r created (id=%d, role=%s).", username, user_id, role,
            extra={"component": "auth"},
        )
        return user_id

    def authenticate(self, username: str, password: str) -> TokenPair:
        """
        Verify *username* / *password*.  On success, update ``last_login``
        and return a :class:`TokenPair`.

        Always runs bcrypt even for unknown usernames to prevent timing
        attacks that could reveal whether a username exists in the database.

        Raises :class:`AuthError` ``("invalid_credentials")`` on wrong
        username or password.
        Raises :class:`AuthError` ``("user_inactive")`` if the account has
        been deactivated.
        """
        user = self._db.get_user_by_username(username)

        if user is None:
            # Unknown username — run bcrypt anyway to prevent timing oracle
            bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)
            raise AuthError("Invalid username or password", code="invalid_credentials")

        if not self._check_password(password, user.password_hash):
            raise AuthError("Invalid username or password.", "invalid_credentials")

        if not user.is_active:
            raise AuthError("Account is inactive.", "user_inactive")

        self._db.update_user_last_login(user.id)
        logger.info(
            "User %r authenticated successfully.", username,
            extra={"component": "auth"},
        )
        return self.issue_token(user)

    def change_password(
        self,
        user_id: int,
        old_password: str,
        new_password: str,
    ) -> None:
        """
        Verify *old_password*, then replace it with a bcrypt hash of
        *new_password*.

        Raises :class:`AuthError` ``("user_not_found")`` if *user_id* does
        not exist.
        Raises :class:`AuthError` ``("invalid_credentials")`` if
        *old_password* is wrong.
        Raises :class:`AuthError` ``("weak_password")`` if *new_password* is
        shorter than 12 characters.
        """
        user = self._db.get_user_by_id(user_id)
        if user is None:
            raise AuthError("User not found.", "user_not_found")

        if not self._check_password(old_password, user.password_hash):
            raise AuthError("Current password is incorrect.", "invalid_credentials")

        if len(new_password) < self._MIN_PASSWORD_LEN:
            raise AuthError(
                f"New password must be at least {self._MIN_PASSWORD_LEN} characters.",
                "weak_password",
            )

        self._db.update_user_password(user_id, self._hash_password(new_password))
        logger.info(
            "Password changed for user_id=%d.", user_id,
            extra={"component": "auth"},
        )

    def deactivate_user(self, user_id: int, deactivated_by_user_id: int) -> None:
        """
        Deactivate the account identified by *user_id*.

        Raises :class:`AuthError` ``("user_not_found")`` if the user does
        not exist.
        Logs the action to ``controller_events``.
        """
        user = self._db.get_user_by_id(user_id)
        if user is None:
            raise AuthError("User not found.", "user_not_found")

        self._db.deactivate_user(user_id)
        self._db.log_event(
            level="WARNING",
            component="auth",
            message=f"User {user.username!r} (id={user_id}) deactivated.",
            user_id=deactivated_by_user_id,
        )
        logger.warning(
            "User %r (id=%d) deactivated by user_id=%d.",
            user.username, user_id, deactivated_by_user_id,
            extra={"component": "auth"},
        )

    def update_role(
        self,
        user_id: int,
        new_role: str,
        updated_by_user_id: int,
    ) -> None:
        """
        Change the role for *user_id* to *new_role*.

        *new_role* must be one of ``admin``, ``operator``, or ``viewer``.
        Raises :exc:`ValueError` if *new_role* is not a recognised role.
        Raises :class:`AuthError` ``("user_not_found")`` if the user does
        not exist.
        Logs the change to ``controller_events``.
        """
        if new_role not in self._VALID_ROLES:
            raise ValueError(
                f"Invalid role {new_role!r}. Must be one of {sorted(self._VALID_ROLES)}."
            )

        user = self._db.get_user_by_id(user_id)
        if user is None:
            raise AuthError("User not found.", "user_not_found")

        self._db.update_user_role(user_id, new_role)
        self._db.log_event(
            level="INFO",
            component="auth",
            message=(
                f"User {user.username!r} (id={user_id}) role changed to {new_role!r}."
            ),
            user_id=updated_by_user_id,
        )
        logger.info(
            "Role for user %r (id=%d) changed to %r by user_id=%d.",
            user.username, user_id, new_role, updated_by_user_id,
            extra={"component": "auth"},
        )

    def list_users(self) -> list[UserRow]:
        """
        Return all users from the database.

        Password hashes are included in the returned rows.  Callers must not
        expose them via the API — redaction is the API layer's responsibility.
        """
        return self._db.list_users()

    def ensure_admin_exists(self) -> None:
        """
        First-run setup: create an ``admin`` user if the users table is empty.

        Prints credentials exactly once to stdout in a bordered box.
        The controller_events log entry does **not** contain the password.
        Does nothing if any users already exist.
        """
        if self._db.count_users() > 0:
            return

        password = secrets.token_urlsafe(12)
        self.create_user("admin", password, "admin")
        self._db.log_event(
            level="WARNING",
            component="auth",
            message="First-run admin user created.",
        )

        # Print credentials once — width of inner content is 45 characters.
        print("┌─────────────────────────────────────────────┐")
        print("│  WANControl first-run setup                 │")
        print("│  Username : admin                           │")
        print(f"│  Password : {password:<32}│")
        print("│  Change this password after first login.    │")
        print("└─────────────────────────────────────────────┘")

    # ── JWT ────────────────────────────────────────────────────────────────

    def issue_token(self, user: UserRow) -> TokenPair:
        """
        Sign a JWT for *user* using HS256 and the configured secret key.

        Payload fields: ``sub``, ``username``, ``role``, ``iat``, ``exp``.
        Returns a :class:`TokenPair`.
        """
        now = int(time.time())
        expiry_seconds = self._server_cfg.jwt_expiry_hours * 3600
        payload = {
            "sub": user.id,
            "username": user.username,
            "role": user.role,
            "iat": now,
            "exp": now + expiry_seconds,
        }
        token = pyjwt.encode(
            payload,
            self._server_cfg.secret_key,
            algorithm=JWT_ALGORITHM,
        )
        return TokenPair(
            access_token=token,
            token_type="bearer",
            expires_in=expiry_seconds,
        )

    def verify_token(self, token: str) -> UserPrincipal:
        """
        Decode and validate a JWT.

        Raises :class:`AuthError` ``("token_expired")`` if expired.
        Raises :class:`AuthError` ``("token_invalid")`` if malformed or the
        signature does not match.
        Raises :class:`AuthError` ``("user_inactive")`` if the token owner
        is no longer active.
        Does **not** check revocation — JWTs are stateless.
        Returns a :class:`UserPrincipal` with ``source="jwt"``.
        """
        try:
            payload = pyjwt.decode(
                token,
                self._server_cfg.secret_key,
                algorithms=[JWT_ALGORITHM],
            )
        except pyjwt.ExpiredSignatureError:
            raise AuthError("Token has expired.", "token_expired")
        except pyjwt.InvalidTokenError:
            raise AuthError("Token is invalid.", "token_invalid")

        user = self._db.get_user_by_id(payload["sub"])
        if user is None or not user.is_active:
            raise AuthError(
                "Account is inactive or no longer exists.", "user_inactive"
            )

        return UserPrincipal(
            user_id=payload["sub"],
            username=payload["username"],
            role=payload["role"],
            source="jwt",
        )

    # ── API tokens ─────────────────────────────────────────────────────────

    def create_api_token(
        self,
        user_id: int,
        label: str,
        expires_in_days: int | None = None,
    ) -> str:
        """
        Generate a random API token and store only its SHA-256 hash in the DB.

        Returns the raw token — this is the **only** time it is visible.
        ``expires_in_days=None`` means the token never expires.
        Raises :class:`AuthError` ``("user_not_found")`` if *user_id* does
        not exist.
        """
        if self._db.get_user_by_id(user_id) is None:
            raise AuthError("User not found.", "user_not_found")

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at: float | None = (
            time.time() + expires_in_days * 86400
            if expires_in_days is not None
            else None
        )
        self._db.create_api_token(user_id, token_hash, label, expires_at)
        logger.info(
            "API token created for user_id=%d, label=%r.", user_id, label,
            extra={"component": "auth"},
        )
        return raw_token

    def verify_api_token(self, raw_token: str) -> UserPrincipal:
        """
        Hash *raw_token* and look it up in the database.

        Raises :class:`AuthError` ``("token_invalid")`` if not found.
        Raises :class:`AuthError` ``("token_revoked")`` if revoked.
        Raises :class:`AuthError` ``("token_expired")`` if past expiry.
        Raises :class:`AuthError` ``("user_inactive")`` if the owning user
        is inactive.
        Calls :meth:`~wancontrol.database.Database.touch_api_token` on success.
        Returns a :class:`UserPrincipal` with ``source="api_token"``.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        token_row = self._db.get_api_token_by_hash(token_hash)

        if token_row is None:
            raise AuthError("API token not found.", "token_invalid")
        if token_row.is_revoked:
            raise AuthError("API token has been revoked.", "token_revoked")
        if token_row.expires_at is not None and time.time() > token_row.expires_at:
            raise AuthError("API token has expired.", "token_expired")

        user = self._db.get_user_by_id(token_row.user_id)
        if user is None or not user.is_active:
            raise AuthError(
                "Account is inactive or no longer exists.", "user_inactive"
            )

        self._db.touch_api_token(token_row.id)
        return UserPrincipal(
            user_id=user.id,
            username=user.username,
            role=user.role,
            source="api_token",
        )

    def revoke_api_token(self, token_id: int, revoked_by_user_id: int) -> None:
        """
        Revoke an API token by its database ``id``.
        Logs the action to ``controller_events``.
        """
        self._db.revoke_api_token(token_id)
        self._db.log_event(
            level="INFO",
            component="auth",
            message=f"API token id={token_id} revoked.",
            user_id=revoked_by_user_id,
        )
        logger.info(
            "API token id=%d revoked by user_id=%d.", token_id, revoked_by_user_id,
            extra={"component": "auth"},
        )

    def list_api_tokens(self, user_id: int | None = None) -> list[ApiTokenRow]:
        """Return API tokens, optionally filtered by *user_id*."""
        return self._db.list_api_tokens(user_id=user_id)

    # ── Role checks ────────────────────────────────────────────────────────

    def require_role(self, principal: UserPrincipal, minimum_role: str) -> None:
        """
        Raise :class:`AuthError` ``("insufficient_role")`` if *principal*'s
        role rank is below *minimum_role* according to :attr:`ROLE_HIERARCHY`.
        """
        principal_rank = self.ROLE_HIERARCHY.get(principal.role, 0)
        required_rank = self.ROLE_HIERARCHY.get(minimum_role, 0)
        if principal_rank < required_rank:
            raise AuthError(
                f"Role {principal.role!r} does not meet the required minimum "
                f"of {minimum_role!r}.",
                "insufficient_role",
            )
