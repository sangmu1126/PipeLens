import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from pipelens.config import Settings
from pipelens.github import GitHubClient, GitHubConfigurationError
from pipelens.models import CurrentUser, GitHubInstallation, GitHubUser
from pipelens.store import AnalysisStore


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthenticatedSession:
    session_hash: str
    user: GitHubUser
    access_token: str


class AuthService:
    def __init__(self, settings: Settings, store: AnalysisStore, github: GitHubClient) -> None:
        self.settings = settings
        self.store = store
        self.github = github
        try:
            ciphers = [Fernet(key.encode()) for key in settings.token_encryption_key_ring]
            self.primary_cipher = ciphers[0]
            self.cipher = MultiFernet(ciphers)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "PIPELENS_TOKEN_ENCRYPTION_KEY and fallback keys must be Fernet keys"
            ) from exc

    @property
    def callback_url(self) -> str:
        return f"{self.settings.public_url.rstrip('/')}/auth/github/callback"

    def require_oauth_configuration(self) -> tuple[str, str]:
        if not self.settings.github_client_id or not self.settings.github_client_secret:
            raise GitHubConfigurationError("GitHub OAuth client credentials are not configured")
        return self.settings.github_client_id, self.settings.github_client_secret

    def new_oauth_state(self) -> str:
        nonce = secrets.token_urlsafe(32)
        signature = hmac.new(
            self.settings.session_secret.encode(), nonce.encode(), hashlib.sha256
        ).hexdigest()
        return f"{nonce}.{signature}"

    def verify_oauth_state(self, state: str | None, cookie_state: str | None) -> None:
        if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
            raise AuthenticationError("invalid OAuth state")
        try:
            nonce, signature = state.rsplit(".", 1)
        except ValueError as exc:
            raise AuthenticationError("invalid OAuth state") from exc
        expected = hmac.new(
            self.settings.session_secret.encode(), nonce.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise AuthenticationError("invalid OAuth state")

    async def complete_login(self, code: str) -> tuple[str, CurrentUser]:
        client_id, client_secret = self.require_oauth_configuration()
        token_payload = await self.github.exchange_user_code(
            client_id, client_secret, code, self.callback_url
        )
        access_token = token_payload["access_token"]
        raw_user = await self.github.authenticated_user(access_token)
        user = GitHubUser(
            github_user_id=raw_user["id"],
            login=raw_user["login"],
            avatar_url=raw_user.get("avatar_url"),
        )
        self.store.upsert_github_user(user)
        installations = await self.sync_installations(user.github_user_id, access_token)

        session_token = secrets.token_urlsafe(48)
        session_ttl = timedelta(days=self.settings.session_ttl_days)
        if token_payload.get("expires_in") is not None:
            session_ttl = min(session_ttl, timedelta(seconds=int(token_payload["expires_in"])))
        expires_at = datetime.now(UTC) + session_ttl
        self.store.create_auth_session(
            _hash_token(session_token),
            user.github_user_id,
            self.cipher.encrypt(access_token.encode()).decode(),
            expires_at,
        )
        return session_token, CurrentUser(**user.model_dump(), installations=installations)

    def authenticate(self, session_token: str | None) -> AuthenticatedSession | None:
        if not session_token:
            return None
        session_hash = _hash_token(session_token)
        row = self.store.get_auth_session(session_hash)
        if not row:
            return None
        expires_at = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            self.store.delete_auth_session(session_hash)
            return None
        encrypted_access_token = row["encrypted_access_token"].encode()
        try:
            access_token_bytes = self.primary_cipher.decrypt(encrypted_access_token)
        except InvalidToken:
            try:
                access_token_bytes = self.cipher.decrypt(encrypted_access_token)
            except InvalidToken:
                self.store.delete_auth_session(session_hash)
                return None
            self.store.update_auth_session_token(
                session_hash,
                self.primary_cipher.encrypt(access_token_bytes).decode(),
            )
        try:
            access_token = access_token_bytes.decode()
        except UnicodeDecodeError:
            self.store.delete_auth_session(session_hash)
            return None
        return AuthenticatedSession(
            session_hash=session_hash,
            user=GitHubUser(
                github_user_id=row["github_user_id"],
                login=row["login"],
                avatar_url=row["avatar_url"],
            ),
            access_token=access_token,
        )

    async def sync_installations(
        self, github_user_id: int, access_token: str
    ) -> list[GitHubInstallation]:
        raw_installations = await self.github.user_installations(access_token)
        installations = [
            GitHubInstallation(
                installation_id=item["id"],
                account_login=item["account"]["login"],
                account_type=item["account"].get("type", "Unknown"),
                repository_selection=item.get("repository_selection", "selected"),
            )
            for item in raw_installations
        ]
        self.store.replace_user_installations(github_user_id, installations)
        return installations

    def current_user(self, session: AuthenticatedSession) -> CurrentUser:
        return CurrentUser(
            **session.user.model_dump(),
            installations=self.store.installations_for_user(session.user.github_user_id),
        )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
