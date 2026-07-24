"""환경변수 → Settings. 하드코딩 금지 원칙(docs/06-conventions.md §1)의 단일 진입점.

코드에 접속 문자열·자격증명 리터럴을 두지 않는다. 모든 환경 의존값은 os.environ에서만
읽고, 실패 시 값 자체를 노출하지 않는 명확한 ConfigError를 낸다(docs/06 §8 오류 처리).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 프로덕션 컨테이너는 env_file로 주입, dotenv 불필요
    load_dotenv = None

if load_dotenv is not None:
    # 이미 설정된 환경변수는 덮어쓰지 않는다(override=False 기본값) — 로컬 개발 편의용.
    load_dotenv()

_ALLOWED_DB_SSL_MODES = ("", "require")


class ConfigError(RuntimeError):
    """설정 로딩 실패. 메시지에 값(특히 자격증명)을 포함하지 않는다."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"필수 환경변수 누락: {name} (.env 확인, .env.example 참고, "
            "docs/08-setup-and-dev-order.md §1)"
        )
    return value


def _optional_env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _existing_dir(name: str, value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(
            f"{name} 경로가 존재하지 않음: {path} "
            "(docs/08-setup-and-dev-order.md §1 env 루트 설정 확인, 읽기 전용 자산)"
        )
    return path


# backend/app/config.py 기준 저장소 루트/frontend 기본 경로(로컬 개발은 env 없이 바로 동작).
# 컨테이너는 docker/Dockerfile이 FRONTEND_DIR을 명시 설정한다(레이아웃이 다르므로).
_DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _resolve_frontend_dir() -> Path | None:
    """프론트(frontend/) 정적 서빙 경로. 없으면 None(정적 서빙 비활성화, 필수 아님) —
    backend만 단독 기동(API 전용)하는 워크플로를 깨지 않기 위해 fail-closed가 아니라
    선택적 기능으로 둔다(docs/06-conventions.md §1 하드코딩 금지, 완료검증 §D-4)."""
    raw = os.environ.get("FRONTEND_DIR")
    path = Path(raw).expanduser().resolve() if raw else _DEFAULT_FRONTEND_DIR
    return path if path.is_dir() else None


def _parse_positive_int(name: str, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}은 정수여야 함: {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name}은 양수여야 함: {value}")
    return value


def _parse_cors_origins(raw: str) -> tuple[str, ...]:
    origins = tuple(o.strip() for o in raw.split(",") if o.strip())
    if not origins:
        raise ConfigError(
            "CORS_ALLOWED_ORIGINS 미설정 — 프론트 도메인을 명시적으로 지정할 것"
            "(docs/06-conventions.md §8, 와일드카드 금지)"
        )
    if any(o == "*" for o in origins):
        raise ConfigError("CORS_ALLOWED_ORIGINS에 와일드카드(*) 금지(docs/06-conventions.md §8)")
    return origins


def _validate_db_ssl_mode(value: str) -> str:
    if value not in _ALLOWED_DB_SSL_MODES:
        raise ConfigError(
            f"DB_SSL_MODE는 {_ALLOWED_DB_SSL_MODES} 중 하나여야 함(현재: {value!r}), "
            "docs/02-db-integration.md §6"
        )
    return value


def _mask_database_url(url: str) -> str:
    """자격증명을 가린 표시용 문자열. 로그·repr에서만 쓴다(원본 url은 그대로 보존)."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return "***"
    _, at, host_and_path = rest.partition("@")
    if not at:
        return f"{scheme}://***"
    return f"{scheme}://***@{host_and_path}"


@dataclass(frozen=True, repr=False)
class Settings:
    database_url: str
    advisor_artifact_database_url: str | None
    db_ssl_mode: str
    db_pool_size: int
    weather_proxy_url: str
    source_project_root: Path
    porting_package_root: Path
    cors_allowed_origins: tuple[str, ...]
    rate_limit_per_minute: int
    reference_cache_ttl_seconds: int
    frontend_dir: Path | None

    def __repr__(self) -> str:  # 자격증명 노출 방지(docs/06 §8)
        masked = _mask_database_url(self.database_url)
        masked_artifact = (
            _mask_database_url(self.advisor_artifact_database_url)
            if self.advisor_artifact_database_url
            else None
        )
        return (
            f"Settings(database_url={masked!r}, advisor_artifact_database_url={masked_artifact!r}, "
            f"db_ssl_mode={self.db_ssl_mode!r}, "
            f"db_pool_size={self.db_pool_size}, weather_proxy_url={self.weather_proxy_url!r}, "
            f"source_project_root={self.source_project_root}, "
            f"porting_package_root={self.porting_package_root}, "
            f"cors_allowed_origins={self.cors_allowed_origins}, "
            f"rate_limit_per_minute={self.rate_limit_per_minute}, "
            f"reference_cache_ttl_seconds={self.reference_cache_ttl_seconds}, "
            f"frontend_dir={self.frontend_dir})"
        )


def load_settings() -> Settings:
    """환경변수에서 Settings를 생성한다. 실패 시 ConfigError.

    ADVISOR_DATABASE_URL은 data-ingestion-backend의 DATABASE_URL(쓰기 role)과 별개다.
    이 서비스는 읽기 전용 role(advisor_readonly, docs/02-db-integration.md §6)로만
    접속해야 최소권한 원칙(docs/06-conventions.md §3)이 DB 레벨에서도 강제된다 —
    앱 코드가 SELECT만 issue하는 것만으로는 부족하다(공유 admin 계정 재사용 금지).
    """
    database_url = _require_env("ADVISOR_DATABASE_URL")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise ConfigError("ADVISOR_DATABASE_URL은 postgresql:// (또는 +psycopg2) 스킴이어야 함")

    # ADVISOR_ARTIFACT_DATABASE_URL(쓰기 role advisor_artifact_writer)은 배치
    # (backend/batch/{build_odr2,build_flow}.py)만 쓴다. API 프로세스(main.py 이하)는
    # 이 값을 참조하지 않으므로 필수로 두지 않는다 — 읽기전용 API 서버를 쓰기 자격증명 없이
    # 그대로 기동할 수 있어야 최소권한 원칙이 실질적으로 지켜진다.
    artifact_database_url = os.environ.get("ADVISOR_ARTIFACT_DATABASE_URL") or None
    if artifact_database_url and not artifact_database_url.startswith(
        ("postgresql://", "postgresql+psycopg2://")
    ):
        raise ConfigError("ADVISOR_ARTIFACT_DATABASE_URL은 postgresql:// (또는 +psycopg2) 스킴이어야 함")

    return Settings(
        database_url=database_url,
        advisor_artifact_database_url=artifact_database_url,
        db_ssl_mode=_validate_db_ssl_mode(_optional_env("DB_SSL_MODE", "")),
        db_pool_size=_parse_positive_int("DB_POOL_SIZE", _optional_env("DB_POOL_SIZE", "5")),
        weather_proxy_url=_optional_env("WEATHER_PROXY_URL", "http://localhost:3000/proxy"),
        source_project_root=_existing_dir(
            "SOURCE_PROJECT_ROOT", _require_env("SOURCE_PROJECT_ROOT")
        ),
        porting_package_root=_existing_dir(
            "PORTING_PACKAGE_ROOT", _require_env("PORTING_PACKAGE_ROOT")
        ),
        cors_allowed_origins=_parse_cors_origins(_optional_env("CORS_ALLOWED_ORIGINS", "")),
        rate_limit_per_minute=_parse_positive_int(
            "RATE_LIMIT_PER_MINUTE", _optional_env("RATE_LIMIT_PER_MINUTE", "60")
        ),
        reference_cache_ttl_seconds=_parse_positive_int(
            "REFERENCE_CACHE_TTL_SECONDS",
            _optional_env("REFERENCE_CACHE_TTL_SECONDS", "86400"),
        ),
        frontend_dir=_resolve_frontend_dir(),
    )


settings = load_settings()
