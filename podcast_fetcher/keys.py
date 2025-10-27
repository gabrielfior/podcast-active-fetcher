from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuration class for managing environment variables."""
    
    SQLALCHEMY_DATABASE_URI: str
    SUPABASE_ACCESS_TOKEN: str
    SUPABASE_MCP_URL: str
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_REGION: str
    TADDY_API_KEY: str
    TADDY_USER_ID: str
    TELEGRAM_BOT_TOKEN: str
    TRANSCRIPT_S3_BUCKET: str
    EPISODE_S3_BUCKET: str
    
    TELEGRAM_APP_API_ID: int
    TELEGRAM_APP_API_HASH: str
    AWS_SESSION_TOKEN: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )


