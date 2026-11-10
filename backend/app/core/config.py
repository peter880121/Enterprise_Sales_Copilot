import os
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr | None = None
    db_host: str | None = None
    db_port: int = Field(default=3306, ge=1, le=65535)
    db_user: str | None = None
    db_password: SecretStr | None = None
    db_name: str | None = None
    csrf_signing_key: SecretStr = Field(
        validation_alias=AliasChoices("CSRF_SIGNING_KEY", "SESSION_SECRET")
    )
    allowed_origin: str = "http://localhost:5173"
    cookie_secure: bool = False
    cookie_name: str = "esc_session"
    session_idle_minutes: int = Field(default=30, ge=1, le=1440)
    session_absolute_hours: int = Field(default=8, ge=1, le=168)
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=5, ge=0, le=20)
    minio_endpoint: str
    minio_port: int = Field(default=9000, ge=1, le=65535)
    minio_use_ssl: bool = False
    minio_access_key: SecretStr
    minio_secret_key: SecretStr
    minio_bucket: str = "esc-evidence"
    ai_mode: Literal["mock", "real"] = "mock"
    knowledge_enabled: bool = False
    tavily_base_url: str = "https://mcp.tavily.com/mcp"
    tavily_api_key: SecretStr | None = None
    discovery_search_enabled: bool = False
    discovery_search_user_daily_limit: int = Field(default=10, ge=1, le=100)
    discovery_search_global_daily_limit: int = Field(default=50, ge=1, le=1000)
    enable_dev_seed: bool = False

    @field_validator("minio_bucket", mode="before")
    @classmethod
    def empty_bucket_default(cls, value):
        return value or "esc-evidence"

    @field_validator("database_url")
    @classmethod
    def mysql_only(cls, value: SecretStr):
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
            if url.drivername not in {"mysql", "mysql+pymysql"} or not url.database:
                raise ValueError
        except Exception:
            raise ValueError("DATABASE_URL must identify a MySQL database") from None
        return value

    @field_validator("csrf_signing_key", "minio_secret_key")
    @classmethod
    def required_secret(cls, value: SecretStr, info):
        minimum = 32 if info.field_name == "csrf_signing_key" else 8
        if len(value.get_secret_value()) < minimum:
            raise ValueError(f"{info.field_name} requires at least {minimum} characters")
        return value

    @field_validator("minio_endpoint")
    @classmethod
    def storage_host(cls, value):
        # Accept the user's host or http(s) endpoint; never accept paths/credentials.
        parsed = urlsplit(value if "://" in value else "//" + value)
        if not parsed.hostname or parsed.username or parsed.path not in {"", "/"}:
            raise ValueError("MINIO_ENDPOINT must be a storage host without credentials or paths")
        return value.rstrip("/")

    @field_validator("allowed_origin")
    @classmethod
    def exact_origin(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("ALLOWED_ORIGIN must be an exact http(s) origin")
        if parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError("ALLOWED_ORIGIN must not contain credentials, path, query or fragment")
        return value

    @model_validator(mode="after")
    def production_security(self):
        if not self.database_url:
            if not all((self.db_host, self.db_user, self.db_password, self.db_name)):
                raise ValueError("DATABASE_URL or complete DB_HOST/USER/PASSWORD/NAME is required")
        if self.app_env == "production":
            if not self.cookie_secure or not self.allowed_origin.startswith("https://"):
                raise ValueError("production requires COOKIE_SECURE=true and HTTPS ALLOWED_ORIGIN")
            if self.enable_dev_seed:
                raise ValueError("development seed is forbidden in production")
        return self

    @property
    def sqlalchemy_url(self):
        if not self.database_url:
            return URL.create(
                "mysql+pymysql",
                username=self.db_user,
                password=self.db_password.get_secret_value(),
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                query={"charset": "utf8mb4"},
            )
        url = make_url(self.database_url.get_secret_value()).set(drivername="mysql+pymysql")
        # Prisma-style URLs may contain connection options unsupported by PyMySQL.
        return url.difference_update_query(["schema", "connection_limit", "pool_timeout"])

    @property
    def storage_address(self) -> str:
        parsed = urlsplit(
            self.minio_endpoint if "://" in self.minio_endpoint else "//" + self.minio_endpoint
        )
        host = parsed.hostname
        if host and ":" in host:
            host = f"[{host}]"
        return f"{host}:{parsed.port or self.minio_port}"


@lru_cache
def get_settings() -> Settings:
    env_file = os.getenv("ESC_ENV_FILE")
    return Settings(_env_file=env_file) if env_file else Settings()
