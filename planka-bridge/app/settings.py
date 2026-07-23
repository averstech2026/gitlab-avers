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
    # Skip Planka "private" projects (sidebar «Мои» / My Own) — no GitLab Issues.
    # New personal projects are skipped automatically; shared/team projects still sync.
    planka_skip_private_projects: bool = True
    # Optional extra denylist (comma-separated ids), on top of private skip
    planka_skip_project_ids: str = ""
    planka_skip_board_ids: str = ""

    gitlab_base_url: str = "https://git.averstech.ru"
    gitlab_token: str = ""
    gitlab_project_id: str = ""
    gitlab_project_path: str = "avers/AVERS"
    gitlab_webhook_token: str = ""

    # Optional JSON map: planka username/email/name → gitlab username
    # e.g. {"ivan":"UBaHbI4"}
    planka_gitlab_user_map: str = ""

    # Optional JSON: gitlab path → planka label, e.g. {"avers/front":"git:Front"}
    # If empty, auto: avers/front → git:Front (from project name; truncated to 16 chars)
    gitlab_project_label_map: str = ""

    # Optional JSON: GitLab Issue label title → Planka label
    # e.g. {"front":"git:Front","plugins":"git:Plugins","взяли":"git:взяли"}
    # If empty, built-in defaults are used (front/plugins/взяли/…).
    gitlab_issue_label_map: str = ""

    database_path: str = "/data/bridge.db"

    @property
    def planka_link_base(self) -> str:
        return (self.planka_public_url or self.planka_base_url).rstrip("/")

    @staticmethod
    def _parse_id_set(raw: str) -> frozenset[str]:
        return frozenset(x.strip() for x in (raw or "").split(",") if x.strip())

    @property
    def skip_project_ids(self) -> frozenset[str]:
        return self._parse_id_set(self.planka_skip_project_ids)

    @property
    def skip_board_ids(self) -> frozenset[str]:
        return self._parse_id_set(self.planka_skip_board_ids)


settings = Settings()