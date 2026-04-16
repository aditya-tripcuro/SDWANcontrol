"""
tests/unit/test_auth.py
~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for wancontrol.auth.

All tests use a real in-memory Database.  bcrypt is not mocked — instead,
BCRYPT_ROUNDS is patched to 4 via an autouse fixture so tests run fast while
still exercising the real bcrypt code paths.
"""

from __future__ import annotations

import hashlib
import time

import jwt as pyjwt
import pytest

import wancontrol.auth
from wancontrol.auth import (
    JWT_ALGORITHM,
    Auth,
    AuthError,
    TokenPair,
    UserPrincipal,
)
from wancontrol.config import ServerConfig
from wancontrol.database import Database


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fast_bcrypt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch BCRYPT_ROUNDS=4 for every test to keep bcrypt fast."""
    monkeypatch.setattr(wancontrol.auth, "BCRYPT_ROUNDS", 4)


@pytest.fixture
def auth(tmp_path):
    db = Database(":memory:")
    db.initialize()
    server_cfg = ServerConfig(
        host="0.0.0.0",
        port=5000,
        secret_key="a" * 32,
        jwt_expiry_hours=1,
        session_timeout_minutes=60,
    )
    return Auth(db=db, server_cfg=server_cfg)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_user(
    auth: Auth,
    username: str = "testuser",
    password: str = "password123456",
    role: str = "viewer",
) -> tuple[int, str]:
    """Create a user and return (user_id, raw_password)."""
    uid = auth.create_user(username, password, role)
    return uid, password


# ── FIRST RUN ─────────────────────────────────────────────────────────────────


class TestFirstRun:
    def test_ensure_admin_creates_user_when_empty(self, auth: Auth) -> None:
        auth.ensure_admin_exists()
        assert auth._db.count_users() == 1
        user = auth._db.get_user_by_username("admin")
        assert user is not None

    def test_ensure_admin_prints_credentials(self, auth: Auth, capsys) -> None:
        auth.ensure_admin_exists()
        out = capsys.readouterr().out
        assert "WANControl first-run setup" in out
        assert "Username : admin" in out
        assert "Password :" in out
        assert "Change this password after first login." in out

    def test_ensure_admin_does_not_log_password(self, auth: Auth, capsys) -> None:
        auth.ensure_admin_exists()
        out = capsys.readouterr().out

        # Extract the generated password from the printed box.
        password: str | None = None
        for line in out.splitlines():
            if "Password :" in line:
                after_colon = line.split("Password :")[-1]
                password = after_colon.strip().rstrip("│").strip()
                break

        assert password is not None and len(password) > 0

        # No controller event must contain the password string.
        for event in auth._db.get_events():
            assert password not in event.message

    def test_ensure_admin_noop_when_users_exist(self, auth: Auth) -> None:
        _make_user(auth, "existing", "existingpass123", "viewer")
        auth.ensure_admin_exists()
        assert auth._db.count_users() == 1  # no extra user created

    def test_ensure_admin_has_correct_role_and_is_active(self, auth: Auth) -> None:
        auth.ensure_admin_exists()
        user = auth._db.get_user_by_username("admin")
        assert user is not None
        assert user.role == "admin"
        assert user.is_active is True


# ── CREATE USER ───────────────────────────────────────────────────────────────


class TestCreateUser:
    def test_create_user_returns_int_id(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        assert isinstance(uid, int)
        assert uid > 0

    def test_created_user_retrievable_by_username(self, auth: Auth) -> None:
        uid, _ = _make_user(auth, username="alice")
        user = auth._db.get_user_by_username("alice")
        assert user is not None
        assert user.id == uid

    def test_password_stored_as_bcrypt_hash(self, auth: Auth) -> None:
        _make_user(auth, password="mypassword1234")
        user = auth._db.get_user_by_username("testuser")
        assert user is not None
        assert user.password_hash != "mypassword1234"
        assert user.password_hash.startswith("$2b$")

    def test_duplicate_username_raises_username_taken(self, auth: Auth) -> None:
        _make_user(auth, username="bob")
        with pytest.raises(AuthError) as exc_info:
            _make_user(auth, username="bob")
        assert exc_info.value.code == "username_taken"

    def test_short_password_raises_weak_password(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.create_user("carol", "tooshort", "viewer")
        assert exc_info.value.code == "weak_password"

    def test_role_stored_correctly(self, auth: Auth) -> None:
        uid, _ = _make_user(auth, role="operator")
        user = auth._db.get_user_by_id(uid)
        assert user is not None
        assert user.role == "operator"


# ── AUTHENTICATE ──────────────────────────────────────────────────────────────


class TestAuthenticate:
    def test_correct_credentials_return_token_pair(self, auth: Auth) -> None:
        _make_user(auth, username="diana", password="validpass1234")
        result = auth.authenticate("diana", "validpass1234")
        assert isinstance(result, TokenPair)
        assert result.token_type == "bearer"
        assert result.expires_in > 0
        assert len(result.access_token) > 0

    def test_wrong_password_raises_invalid_credentials(self, auth: Auth) -> None:
        _make_user(auth, username="eve", password="correctpass123")
        with pytest.raises(AuthError) as exc_info:
            auth.authenticate("eve", "wrongpassword!")
        assert exc_info.value.code == "invalid_credentials"

    def test_unknown_username_raises_invalid_credentials(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.authenticate("nobody_xyz", "doesnotmatter")
        assert exc_info.value.code == "invalid_credentials"

    def test_inactive_user_raises_user_inactive(self, auth: Auth) -> None:
        uid, pwd = _make_user(auth, username="frank")
        auth.deactivate_user(uid, uid)
        with pytest.raises(AuthError) as exc_info:
            auth.authenticate("frank", pwd)
        assert exc_info.value.code == "user_inactive"

    def test_successful_login_updates_last_login(self, auth: Auth) -> None:
        uid, pwd = _make_user(auth, username="grace")
        before = auth._db.get_user_by_id(uid)
        assert before is not None and before.last_login is None

        auth.authenticate("grace", pwd)

        after = auth._db.get_user_by_id(uid)
        assert after is not None and after.last_login is not None

    def test_timing_safety_unknown_vs_wrong_password(self, auth, monkeypatch):
        """
        Verify that authenticate() always runs bcrypt regardless of whether
        the username exists. Tests the code path, not wall-clock timing.

        Wall-clock timing tests are inherently flaky due to OS scheduling,
        CPU cache state, and bcrypt variance. Instead we verify that
        bcrypt.checkpw() is called in both the known-user/wrong-password
        and unknown-user code paths.
        """
        import bcrypt

        monkeypatch.setattr("wancontrol.auth.BCRYPT_ROUNDS", 4)

        # Create a known user
        auth.create_user("timing_user", "StrongPassword123!", "viewer")

        checkpw_calls = []

        original_checkpw = bcrypt.checkpw

        def tracking_checkpw(password: bytes, hashed: bytes) -> bool:
            checkpw_calls.append({"password_len": len(password)})
            return original_checkpw(password, hashed)

        monkeypatch.setattr("wancontrol.auth.bcrypt.checkpw", tracking_checkpw)

        # Known user, wrong password — bcrypt.checkpw must be called
        checkpw_calls.clear()
        with pytest.raises(AuthError) as exc_info:
            auth.authenticate("timing_user", "WrongPassword999!")
        assert exc_info.value.code == "invalid_credentials"
        assert len(checkpw_calls) == 1, (
            "bcrypt.checkpw must be called exactly once for known user / wrong password"
        )

        # Unknown user — bcrypt.checkpw must ALSO be called (dummy hash path)
        checkpw_calls.clear()
        with pytest.raises(AuthError) as exc_info:
            auth.authenticate("no_such_user", "AnyPassword123!")
        assert exc_info.value.code == "invalid_credentials"
        assert len(checkpw_calls) == 1, (
            "bcrypt.checkpw must be called exactly once for unknown username "
            "(timing attack prevention). If this fails, auth.py is leaking "
            "username existence via response time."
        )


# ── CHANGE PASSWORD ───────────────────────────────────────────────────────────


class TestChangePassword:
    def test_correct_old_password_updates_hash(self, auth: Auth) -> None:
        uid, old_pwd = _make_user(auth)
        old_hash = auth._db.get_user_by_id(uid).password_hash  # type: ignore[union-attr]
        auth.change_password(uid, old_pwd, "newpassword5678")
        new_hash = auth._db.get_user_by_id(uid).password_hash  # type: ignore[union-attr]
        assert new_hash != old_hash

    def test_wrong_old_password_raises_invalid_credentials(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        with pytest.raises(AuthError) as exc_info:
            auth.change_password(uid, "wrongoldpassword", "newpassword5678")
        assert exc_info.value.code == "invalid_credentials"

    def test_new_password_too_short_raises_weak_password(self, auth: Auth) -> None:
        uid, old_pwd = _make_user(auth)
        with pytest.raises(AuthError) as exc_info:
            auth.change_password(uid, old_pwd, "short")
        assert exc_info.value.code == "weak_password"

    def test_unknown_user_id_raises_user_not_found(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.change_password(9999, "oldpass123456", "newpass123456")
        assert exc_info.value.code == "user_not_found"

    def test_new_password_verifies_correctly_after_change(self, auth: Auth) -> None:
        uid, old_pwd = _make_user(auth, username="henry")
        auth.change_password(uid, old_pwd, "brandnewpass99")
        pair = auth.authenticate("henry", "brandnewpass99")
        assert isinstance(pair, TokenPair)


# ── JWT — ISSUE AND VERIFY ────────────────────────────────────────────────────


class TestJWT:
    def test_verify_token_returns_user_principal(self, auth: Auth) -> None:
        uid, pwd = _make_user(auth, username="iris")
        pair = auth.authenticate("iris", pwd)
        principal = auth.verify_token(pair.access_token)
        assert isinstance(principal, UserPrincipal)
        assert principal.user_id == uid
        assert principal.username == "iris"
        assert principal.role == "viewer"

    def test_user_principal_source_is_jwt(self, auth: Auth) -> None:
        uid, pwd = _make_user(auth, username="jack")
        pair = auth.authenticate("jack", pwd)
        principal = auth.verify_token(pair.access_token)
        assert principal.source == "jwt"

    def test_expired_token_raises_token_expired(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        now = int(time.time())
        payload = {
            "sub": uid,
            "username": "testuser",
            "role": "viewer",
            "iat": now - 7200,
            "exp": now - 1,
        }
        expired = pyjwt.encode(
            payload, auth._server_cfg.secret_key, algorithm=JWT_ALGORITHM
        )
        with pytest.raises(AuthError) as exc_info:
            auth.verify_token(expired)
        assert exc_info.value.code == "token_expired"

    def test_tampered_token_raises_token_invalid(self, auth: Auth) -> None:
        uid, pwd = _make_user(auth, username="kate")
        pair = auth.authenticate("kate", pwd)
        # Corrupt the signature portion of the JWT.
        parts = pair.access_token.split(".")
        tampered = parts[0] + "." + parts[1] + ".invalidsignature"
        with pytest.raises(AuthError) as exc_info:
            auth.verify_token(tampered)
        assert exc_info.value.code == "token_invalid"

    def test_wrong_secret_raises_token_invalid(self, auth: Auth) -> None:
        uid, pwd = _make_user(auth, username="leo")
        pair = auth.authenticate("leo", pwd)
        other_cfg = ServerConfig("0.0.0.0", 5000, "b" * 32, 1, 60)
        other_auth = Auth(db=auth._db, server_cfg=other_cfg)
        with pytest.raises(AuthError) as exc_info:
            other_auth.verify_token(pair.access_token)
        assert exc_info.value.code == "token_invalid"

    def test_deactivated_user_valid_jwt_raises_user_inactive(self, auth: Auth) -> None:
        uid, pwd = _make_user(auth, username="mia")
        pair = auth.authenticate("mia", pwd)
        auth.deactivate_user(uid, uid)
        with pytest.raises(AuthError) as exc_info:
            auth.verify_token(pair.access_token)
        assert exc_info.value.code == "user_inactive"

    def test_jwt_payload_contains_required_fields(self, auth: Auth) -> None:
        uid, _ = _make_user(auth, username="nick", role="operator")
        user = auth._db.get_user_by_id(uid)
        assert user is not None
        pair = auth.issue_token(user)
        payload = pyjwt.decode(
            pair.access_token,
            auth._server_cfg.secret_key,
            algorithms=[JWT_ALGORITHM],
        )
        assert payload["sub"] == uid
        assert payload["username"] == "nick"
        assert payload["role"] == "operator"
        assert "iat" in payload
        assert "exp" in payload
        assert payload["exp"] > payload["iat"]


# ── API TOKENS ────────────────────────────────────────────────────────────────


class TestApiTokens:
    def test_create_api_token_returns_raw_string(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        raw = auth.create_api_token(uid, "ci-runner")
        assert isinstance(raw, str)
        assert len(raw) > 0

    def test_raw_token_not_stored_in_db(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        raw = auth.create_api_token(uid, "test-token")
        rows = auth._db.list_api_tokens(user_id=uid)
        assert len(rows) == 1
        assert rows[0].token_hash != raw
        # Verify the DB stores the SHA-256 hex digest.
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert rows[0].token_hash == expected

    def test_verify_api_token_returns_user_principal(self, auth: Auth) -> None:
        uid, _ = _make_user(auth, username="olivia")
        raw = auth.create_api_token(uid, "my-token")
        principal = auth.verify_api_token(raw)
        assert isinstance(principal, UserPrincipal)
        assert principal.user_id == uid
        assert principal.username == "olivia"

    def test_verify_api_token_source_is_api_token(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        raw = auth.create_api_token(uid, "src-check")
        principal = auth.verify_api_token(raw)
        assert principal.source == "api_token"

    def test_unknown_token_raises_token_invalid(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.verify_api_token("completely_unknown_raw_token_value_xyz")
        assert exc_info.value.code == "token_invalid"

    def test_revoked_token_raises_token_revoked(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        raw = auth.create_api_token(uid, "revoke-me")
        rows = auth._db.list_api_tokens(user_id=uid)
        auth.revoke_api_token(rows[0].id, uid)
        with pytest.raises(AuthError) as exc_info:
            auth.verify_api_token(raw)
        assert exc_info.value.code == "token_revoked"

    def test_expired_api_token_raises_token_expired(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        raw = auth.create_api_token(uid, "old-token", expires_in_days=-1)
        with pytest.raises(AuthError) as exc_info:
            auth.verify_api_token(raw)
        assert exc_info.value.code == "token_expired"

    def test_verify_api_token_updates_last_used(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        raw = auth.create_api_token(uid, "track-use")
        rows_before = auth._db.list_api_tokens(user_id=uid)
        assert rows_before[0].last_used is None

        auth.verify_api_token(raw)

        rows_after = auth._db.list_api_tokens(user_id=uid)
        assert rows_after[0].last_used is not None

    def test_inactive_user_token_raises_user_inactive(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        raw = auth.create_api_token(uid, "inactive-check")
        auth.deactivate_user(uid, uid)
        with pytest.raises(AuthError) as exc_info:
            auth.verify_api_token(raw)
        assert exc_info.value.code == "user_inactive"

    def test_no_expiry_token_never_raises_token_expired(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        raw = auth.create_api_token(uid, "forever", expires_in_days=None)
        principal = auth.verify_api_token(raw)
        assert principal.user_id == uid

    def test_list_api_tokens_filters_by_user(self, auth: Auth) -> None:
        uid1, _ = _make_user(auth, username="user1")
        uid2, _ = _make_user(auth, username="user2")
        auth.create_api_token(uid1, "tok-a")
        auth.create_api_token(uid1, "tok-b")
        auth.create_api_token(uid2, "tok-c")

        tokens_u1 = auth.list_api_tokens(user_id=uid1)
        tokens_u2 = auth.list_api_tokens(user_id=uid2)
        assert len(tokens_u1) == 2
        assert len(tokens_u2) == 1
        assert all(t.user_id == uid1 for t in tokens_u1)

    def test_create_api_token_unknown_user_raises_user_not_found(
        self, auth: Auth
    ) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.create_api_token(9999, "phantom")
        assert exc_info.value.code == "user_not_found"


# ── ROLE CHECKS ───────────────────────────────────────────────────────────────


class TestRoleChecks:
    def _principal(self, role: str) -> UserPrincipal:
        return UserPrincipal(user_id=1, username="u", role=role, source="jwt")

    def test_require_role_passes_when_equal(self, auth: Auth) -> None:
        auth.require_role(self._principal("operator"), "operator")  # no exception

    def test_require_role_passes_when_above(self, auth: Auth) -> None:
        auth.require_role(self._principal("admin"), "viewer")  # no exception

    def test_require_role_raises_when_below(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.require_role(self._principal("viewer"), "admin")
        assert exc_info.value.code == "insufficient_role"

    def test_viewer_fails_operator_check(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.require_role(self._principal("viewer"), "operator")
        assert exc_info.value.code == "insufficient_role"

    def test_viewer_fails_admin_check(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.require_role(self._principal("viewer"), "admin")
        assert exc_info.value.code == "insufficient_role"

    def test_operator_passes_viewer_check(self, auth: Auth) -> None:
        auth.require_role(self._principal("operator"), "viewer")  # no exception

    def test_operator_fails_admin_check(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.require_role(self._principal("operator"), "admin")
        assert exc_info.value.code == "insufficient_role"

    def test_admin_passes_all_checks(self, auth: Auth) -> None:
        p = self._principal("admin")
        auth.require_role(p, "viewer")
        auth.require_role(p, "operator")
        auth.require_role(p, "admin")


# ── USER MANAGEMENT ───────────────────────────────────────────────────────────


class TestUserManagement:
    def test_deactivate_user_sets_is_active_false(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        auth.deactivate_user(uid, uid)
        user = auth._db.get_user_by_id(uid)
        assert user is not None
        assert user.is_active is False

    def test_deactivate_unknown_user_raises_user_not_found(self, auth: Auth) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.deactivate_user(9999, 1)
        assert exc_info.value.code == "user_not_found"

    def test_update_role_changes_role(self, auth: Auth) -> None:
        uid, _ = _make_user(auth, role="viewer")
        auth.update_role(uid, "operator", uid)
        user = auth._db.get_user_by_id(uid)
        assert user is not None
        assert user.role == "operator"

    def test_update_role_invalid_raises_value_error(self, auth: Auth) -> None:
        uid, _ = _make_user(auth)
        with pytest.raises(ValueError):
            auth.update_role(uid, "superuser", uid)

    def test_update_role_unknown_user_raises_user_not_found(
        self, auth: Auth
    ) -> None:
        with pytest.raises(AuthError) as exc_info:
            auth.update_role(9999, "admin", 1)
        assert exc_info.value.code == "user_not_found"

    def test_list_users_returns_all_users(self, auth: Auth) -> None:
        _make_user(auth, username="user_a")
        _make_user(auth, username="user_b")
        _make_user(auth, username="user_c")
        users = auth.list_users()
        assert len(users) == 3
        usernames = {u.username for u in users}
        assert usernames == {"user_a", "user_b", "user_c"}
