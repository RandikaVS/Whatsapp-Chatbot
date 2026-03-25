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
    DATABASE_PASSWORD: str = os.getenv("DATABASE_PASSWORD", "VhJmu3DjzkzVagip")
    DATABASE_PORT: str = os.getenv("DATABASE_PORT", "5432")
    DATABASE_HOST: str = os.getenv("DATABASE_HOST", "db.ebjgtfcryrpzbagwqlio.supabase.co")

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

    DEFAULT_STEPS = [
        {
            "step_index": 0, "step_key": "idle", "display_name": "Idle / Entry",
            "is_enabled": True,
            "description": "Triggered when customer says hi/hello/start/help",
            "message": "Hi {{customer_name}}! 👋 Welcome to *{{business_name}}*!\n\nHow can I help you today?",
            "buttons": [
                {"id": "flow_browse",  "title": "🛍️ Browse Products"},
                {"id": "flow_order",   "title": "📦 My Orders"},
                {"id": "flow_support", "title": "💬 Support"},
            ],
        },
        {
            "step_index": 1, "step_key": "main_menu", "display_name": "Main Menu",
            "is_enabled": True,
            "description": "Routes customer to Browse, Orders, or Support",
            "message": "Please choose an option below:",
            "buttons": [
                {"id": "flow_browse",  "title": "🛍️ Browse Products"},
                {"id": "flow_order",   "title": "📦 My Orders"},
                {"id": "flow_support", "title": "💬 Support"},
            ],
        },
        {
            "step_index": 2, "step_key": "browsing", "display_name": "Product Browser",
            "is_enabled": True,
            "description": "Shows product list from catalog as WhatsApp list",
            "message": "Here are our available products 👇\n\nTap a product to see details and order.",
            "buttons": [],
        },
        {
            "step_index": 3, "step_key": "product_detail", "display_name": "Product Detail",
            "is_enabled": True,
            "description": "Shows product details with Order / Back buttons",
            "message": "{{product_details}}",
            "buttons": [
                {"id": "flow_add_to_order", "title": "✅ Order This"},
                {"id": "flow_back",         "title": "◀️ Back to List"},
                {"id": "flow_main_menu",    "title": "🏠 Main Menu"},
            ],
        },
        {
            "step_index": 4, "step_key": "collect_quantity", "display_name": "Collect Quantity",
            "is_enabled": True,
            "description": "Asks how many units the customer wants",
            "message": "Great choice! 🎉 You selected *{{product_name}}*.\n\nPlease enter the *quantity* you'd like to order:",
            "buttons": [],
        },
        {
            "step_index": 5, "step_key": "collect_size", "display_name": "Collect Size",
            "is_enabled": True,
            "description": "Asks customer for their size",
            "message": "What *size* do you need? (e.g. 40, 42, 44)",
            "buttons": [],
        },
        {
            "step_index": 6, "step_key": "collect_address", "display_name": "Collect Address",
            "is_enabled": True,
            "description": "Asks for delivery address",
            "message": "📍 What is your *delivery address*?",
            "buttons": [],
        },
        {
            "step_index": 7, "step_key": "confirm_order", "display_name": "Order Confirmation",
            "is_enabled": True,
            "description": "Shows order summary and asks for confirmation",
            "message": (
                "📋 *Order Summary*\n\n"
                "Product : {{product_name}}\n"
                "Size    : {{size}}\n"
                "Qty     : {{quantity}}\n"
                "Address : {{address}}\n"
                "Total   : {{currency}} {{total}}\n\n"
                "Delivery in 2-3 business days. 🚚"
            ),
            "buttons": [
                {"id": "flow_confirm", "title": "✅ Confirm Order"},
                {"id": "flow_cancel",  "title": "❌ Cancel"},
            ],
        },
        {
            "step_index": 8, "step_key": "support", "display_name": "AI Support Chat",
            "is_enabled": True,
            "description": "Hands off to AI using system prompt from My Agent settings",
            "message": "💬 *Support*\n\nTell me what you need help with and I'll assist you right away.",
            "buttons": [],
        },
    ]

        
settings = Settings()
