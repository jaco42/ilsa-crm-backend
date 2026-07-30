from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 480

    resend_api_key: str = ""
    resend_from: str = "ILSA CRM <onboarding@resend.dev>"
    groq_api_key: str = ""
    service_api_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
