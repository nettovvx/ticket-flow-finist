from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "TicketFlow"
    app_env: str = Field(default="production", alias="APP_ENV")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    database_url: str = Field(
        default="postgresql+psycopg://ticketflow:ticketflow@postgres:5432/ticketflow",
        alias="DATABASE_URL",
    )

    server_host: str = Field(default="0.0.0.0", alias="SERVER_HOST")
    server_port: int = Field(default=8000, alias="SERVER_PORT")
    server_reload: bool = Field(default=False, alias="SERVER_RELOAD")

    bootstrap_admin_username: str = Field(default="admin", alias="BOOTSTRAP_ADMIN_USERNAME")
    bootstrap_admin_password: str = Field(default="admin123", alias="BOOTSTRAP_ADMIN_PASSWORD")
    bootstrap_admin_role: str = Field(default="admin", alias="BOOTSTRAP_ADMIN_ROLE")

    ticket_inbox_dir: Path = Field(default=Path("/opt/sirena-olt-client/received-files"), alias="TICKET_INBOX_DIR")
    ftp_tickets_dir: Path = Field(default=Path("/srv/ftp/tickets"), alias="FTP_TICKETS_DIR")
    ftp_tickets_processed_dir: Path = Field(default=Path("/srv/ftp/tickets/processed"), alias="FTP_TICKETS_PROCESSED_DIR")
    ftp_tickets_error_dir: Path = Field(default=Path("/srv/ftp/tickets/error"), alias="FTP_TICKETS_ERROR_DIR")

    ftp_realisations_dir: Path = Field(default=Path("/srv/ftp/realisations"), alias="FTP_REALISATIONS_DIR")
    onec_realisations_target_dir: Path = Field(default=Path("/mnt/1c-gds"), alias="ONEC_REALISATIONS_TARGET_DIR")
    onec_realisations_archive_dir: Path = Field(default=Path("/mnt/1c-gds/archive"), alias="ONEC_REALISATIONS_ARCHIVE_DIR")
    onec_realisations_bad_dir: Path = Field(default=Path("/mnt/1c-gds/bad"), alias="ONEC_REALISATIONS_BAD_DIR")
    onec_realisations_del_bad_dir: Path = Field(default=Path("/mnt/1c-gds/del_bad"), alias="ONEC_REALISATIONS_DEL_BAD_DIR")
    onec_realisations_empty_dir: Path = Field(default=Path("/mnt/1c-gds/empty"), alias="ONEC_REALISATIONS_EMPTY_DIR")

    onec_payments_source_dir: Path = Field(default=Path("/mnt/1c-payments"), alias="ONEC_PAYMENTS_SOURCE_DIR")
    ftp_payments_dir: Path = Field(default=Path("/srv/ftp/payments"), alias="FTP_PAYMENTS_DIR")
    ftp_payments_processed_dir: Path = Field(default=Path("/srv/ftp/payments/processed"), alias="FTP_PAYMENTS_PROCESSED_DIR")
    ftp_payments_error_dir: Path = Field(default=Path("/srv/ftp/payments/error"), alias="FTP_PAYMENTS_ERROR_DIR")

    file_scan_interval_sec: int = Field(default=5, alias="FILE_SCAN_INTERVAL_SEC")
    file_stable_age_sec: int = Field(default=3, alias="FILE_STABLE_AGE_SEC")

    base_dir: Path = BASE_DIR
    static_dir: Path = BASE_DIR / "app" / "static"
    web_dir: Path = BASE_DIR / "app" / "static" / "web"
    templates_dir: Path = BASE_DIR / "app" / "templates"


@lru_cache
def get_settings() -> Settings:
    return Settings()
