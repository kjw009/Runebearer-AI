from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # LLM
    anthropic_api_key: str
    openai_api_key: str

    # Postgres
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "elden_rag"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Langfuse
    langfuse_public_key: str = "pk-lf-dev"
    langfuse_secret_key: str = "sk-lf-dev"
    langfuse_host: str = "http://localhost:3000"


settings = Settings()
