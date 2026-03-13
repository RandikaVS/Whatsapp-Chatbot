from celery import Celery
from app.services.ai_engine import AIEngine
from app.services.whatsapp import WhatsAppService
from app.services.session import SessionService
from app.database import get_db

celery_app = Celery("tasks", broker="redis://localhost:6379/0")

@celery_app.task(bind=True, max_retries=3)
def process_message_async(self, tenant_id: str, message_data: dict, contacts: list):
    try:
        db = get_db()
        
        # 1. Check message type
        msg_type = message_data.get("type")  # text, image, audio, etc.
        phone = message_data["from"]
        wa_msg_id = message_data["id"]
        
        # 2. Deduplicate (Meta sometimes delivers twice)
        # if MessageService.exists(db, wa_msg_id):
        #     return
        
        # 3. Get or create conversation
        tenant = None  # TenantService.get(db, tenant_id) --- IGNORE ---
        conversation = None
        
        # 4. Check if human takeover is active
        if conversation.is_human_takeover:
            return  # Human agent handles it, don't respond with AI
        
        # 5. Check message limit
        if tenant.messages_used_this_month >= tenant.monthly_message_limit:
            WhatsAppService.send_text(
                tenant, phone,
                "Service limit reached. Please contact support."
            )
            return
        
        # 6. Get conversation history from Redis (last 20 messages)
        history = SessionService.get_history(tenant_id, phone)
        
        # 7. Extract text content
        if msg_type == "text":
            user_text = message_data["text"]["body"]
        elif msg_type == "audio":
            # Transcribe with Whisper
            user_text = AIEngine.transcribe_audio(message_data, tenant)
        else:
            user_text = f"[{msg_type} message received]"
        
        # 8. Save user message to DB
        # MessageService.create(db, conversation.id, "user", user_text, wa_msg_id)
        
        # 9. Generate AI response
        bot_config = tenant.bot_config
        response_text, tokens = AIEngine.generate(
            system_prompt=bot_config.get("system_prompt", "You are a helpful assistant."),
            history=history,
            user_message=user_text,
            model=bot_config.get("model", "gpt-4o-mini")
        )
        
        # 10. Send reply via WhatsApp
        WhatsAppService.send_text(tenant, phone, response_text)
        
        # 11. Persist to Redis history + DB
        SessionService.append(tenant_id, phone, "user", user_text)
        SessionService.append(tenant_id, phone, "assistant", response_text)
        # MessageService.create(db, conversation.id, "assistant", response_text,
        #                       tokens_used=tokens)
        
        # 12. Increment usage counter
        # TenantService.increment_usage(db, tenant_id)
        
        db.commit()
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)