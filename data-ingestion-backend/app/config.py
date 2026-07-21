"""환경변수 → Settings. 하드코딩 금지 원칙(docs/06-conventions.md §1)의 단일 진입점.

코드에 접속 문자열·자격증명 리터럴을 두지 않는다. 모든 환경 의존값은 os.environ에서만
읽고, 실패 시 값 자체를 노출하지 않는 명확한 ConfigError를 낸다(docs/06 §8 오류 처리).

이 앱은 저장소 루트의 .env를 공유한다(DATABASE_URL·SOURCE_PROJECT_ROOT는 backend/app이
쓰는 것과 동일한 값 — 같은 로컬 pgsql·같은 원본 프로젝트를 가리키므로 별도 .env를 두지 않는다,
data-ingestion-backend/_MIRROR.md 규칙 2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 프로덕션 컨테이너는 env_file로 주입, dotenv 불필요
    load_dotenv = None

_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

if load_dotenv is not None:
    # 이미 설정된 환경변수는 덮어쓰지 않는다(override=False 기본값) — 로컬 개발 편의용.
    # 저장소 루트(flight-route-advisor/.env)를 명시 지정: 이 앱은 backend/app과 같은 .env를 공유한다.
    if _REPO_ROOT_ENV_FILE.is_file():
        load_dotenv(dotenv_path=_REPO_ROOT_ENV_FILE)
    else:
        load_dotenv()

_ALLOWED_EXTENSIONS_WHITELIST = (".csv", ".xlsx", ".xls")


class ConfigError(RuntimeError):
    """설정 로딩 실패. 메시지에 값(특히 자격증명)을 포함하지 않는다."""


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"필수 환경변수 누락: {name} (저장소 루트 .env 확인, .env.example 참고, "
            "docs/08-setup-and-dev-order.md §1)"
        )
    return value


def _optional_env(name: str, default: str) -> str:
    # 빈 문자열(.env에 키만 두고 값 비움)도 미설정으로 취급해 기본값을 쓴다.
    return os.environ.get(name) or default


def _existing_dir(name: str, value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(
            f"{name} 경로가 존재하지 않음: {path} "
            "(docs/08-setup-and-dev-order.md §1 env 루트 설정 확인, 읽기 전용 자산)"
        )
    return path


def _ensured_dir(value: str) -> Path:
    """존재하지 않으면 생성한다(uploads/workspace는 이 앱이 쓰는 로컬 데이터 디렉터리)."""
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _parse_positive_int(name: str, raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}은 정수여야 함: {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name}은 양수여야 함: {value}")
    return value


def _parse_allowed_extensions(raw: str) -> tuple[str, ...]:
    extensions = tuple(e.strip().lower() for e in raw.split(",") if e.strip())
    if not extensions:
        raise ConfigError("ALLOWED_EXTENSIONS 미설정")
    unknown = [e for e in extensions if e not in _ALLOWED_EXTENSIONS_WHITELIST]
    if unknown:
        raise ConfigError(
            f"ALLOWED_EXTENSIONS에 허용되지 않은 확장자: {unknown} "
            f"(허용: {_ALLOWED_EXTENSIONS_WHITELIST}, docs/06-conventions.md §8 업로드 화이트리스트)"
        )
    return extensions


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
    source_project_root: Path
    upload_dir: Path
    workspace_root: Path
    max_upload_mb: int
    allowed_extensions: tuple[str, ...]
    delete_token: str | None

    def __repr__(self) -> str:  # 자격증명 노출 방지(docs/06 §8)
        masked = _mask_database_url(self.database_url)
        return (
            f"Settings(database_url={masked!r}, "
            f"source_project_root={self.source_project_root}, "
            f"upload_dir={self.upload_dir}, workspace_root={self.workspace_root}, "
            f"max_upload_mb={self.max_upload_mb}, "
            f"allowed_extensions={self.allowed_extensions}, "
            f"delete_token={'***' if self.delete_token else None})"
        )


_DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / "data"


def load_settings() -> Settings:
    """환경변수에서 Settings를 생성한다. 실패 시 ConfigError."""
    database_url = _require_env("DATABASE_URL")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg2://")):
        raise ConfigError("DATABASE_URL은 postgresql:// (또는 +psycopg2) 스킴이어야 함")

    return Settings(
        database_url=database_url,
        source_project_root=_existing_dir(
            "SOURCE_PROJECT_ROOT", _require_env("SOURCE_PROJECT_ROOT")
        ),
        upload_dir=_ensured_dir(
            _optional_env("INGESTION_UPLOAD_DIR", str(_DEFAULT_DATA_ROOT / "uploads"))
        ),
        workspace_root=_ensured_dir(
            _optional_env("INGESTION_WORKSPACE_ROOT", str(_DEFAULT_DATA_ROOT / "workspace"))
        ),
        max_upload_mb=_parse_positive_int(
            "MAX_UPLOAD_MB", _optional_env("MAX_UPLOAD_MB", "200")
        ),
        allowed_extensions=_parse_allowed_extensions(
            _optional_env("ALLOWED_EXTENSIONS", ".csv,.xlsx,.xls")
        ),
        # run 삭제(POST /runs/{id}/delete)는 되돌릴 수 없는 파괴적 작업인데 이 앱 전체에
        # 인증이 없다(코드리뷰 2026-07-21 발견) — 별도 인증 체계를 새로 만드는 대신, 이
        # 토큰이 설정된 경우에만 삭제 기능을 활성화하는 최소 게이트를 둔다(미설정 시
        # 기본적으로 삭제 비활성화 — fail-closed, routers/runs.py 참고).
        delete_token=_optional_env("INGESTION_DELETE_TOKEN", "") or None,
    )


settings = load_settings()
