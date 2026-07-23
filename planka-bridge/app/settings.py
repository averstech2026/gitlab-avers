from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    planka_base_url: str = "https://board.averstech.ru"
    # Публичный URL для ссылок в Issue (если API ходит по внутреннему Docker DNS)
    planka_public_url: str = ""
    planka_email: str = ""
    planka_password: str = ""
    planka_webhook_token: str = ""
    planka_ready_list_name: str = "В работе (очередь Git)"

    gitlab_base_url: str = "https://git.averstech.ru"
    gitlab_token: str = ""
    gitlab_project_id: str = ""
    gitlab_project_path: str = "avers/AVERS"
    gitlab_webhook_token: str = ""

    database_path: str = "/data/bridge.db"

    @property
    def planka_link_base(self) -> str:
        return (self.planka_public_url or self.planka_base_url).rstrip("/")


settings = Settings()