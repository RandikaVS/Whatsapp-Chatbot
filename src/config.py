from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os
import psycopg2
from typing import ClassVar, Dict

load_dotenv()

class Settings(BaseSettings):
    
    CHAT_USER_TOKEN: str = os.getenv("CHAT_USER_TOKEN")
    PHONE_NUMBER_ID: str = os.getenv("PHONE_NUMBER_ID")
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")
    VERIFY_TOKEN: str = os.getenv("VERIFY_TOKEN")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")

    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "postgres")
    DATABASE_USER: str = os.getenv("DATABASE_USER", "postgres")
    DATABASE_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "sahanrandika")
    DATABASE_PORT: str = os.getenv("DATABASE_PORT", "5432")
    DATABASE_HOST: str = os.getenv("DATABASE_HOST", "0.0.0.0")

    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "meta_chatbot_secret_key")

    REDIS_URL: str = os.getenv("REDIS_URL", "rediss://default:gQAAAAAAAUkQAAIncDI4MzBkYmQ5NzlmNDU0YTE2OTVhZjcyNmVhNzJkYmNjMnAyODQyNDA@crucial-mouse-84240.upstash.io:6379")

    SQLALCHEMY_DATABASE_URI: str = 'postgresql+asyncpg://' \
                            + os.environ.get('DATABASE_USER') + ':' \
                            + os.environ.get('DATABASE_PASSWORD') + '@' \
                            + os.environ.get('DATABASE_HOST') + ':' \
                            + os.environ.get('DATABASE_PORT') + '/' \
                            + os.environ.get('DATABASE_NAME')
    
    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
            f"?ssl=require"
        )
    
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    

    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "b6c48e51ecc74f5a574be24407cd3822ef1138dcdcfd979a6d73bc7c20faded8f524914d0a0c042d664d54a12292d31edaa5721d8e83ef16730027e6cea70e20")                
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30   # access token lives 30 minutes
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7      # refresh token lives 7 days

    FLOW_STEPS_DICT: ClassVar[Dict[int, str]] = {
        0: "idle",
        1: "main_menu",
        2: "browsing",
        3: "product_detail",
        4: "collect_quantity",
        5: "collect_size",
        6: "collect_address",
        7: "confirm_order",
        8: "support",
    }

        
settings = Settings()
