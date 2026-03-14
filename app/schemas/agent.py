# app/schemas/agent.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class AgentConfigResponse(BaseModel):
    """
    What the My Agent page receives when it first loads.
    This is the complete current state of the client's bot.
    The Optional fields may be None for newly registered tenants
    who haven't set up WhatsApp yet.
    """
    business_name:       str
    is_bot_active:       bool
    system_prompt:       str
    welcome_message:     str
    ai_model:            str
    language:            str
    temperature:         float
    max_tokens:          int
    reply_delay_seconds: int

    # Read-only fields — the frontend shows these but cannot write them
    plan:                  str
    monthly_message_limit: int
    messages_used:         int
    wa_connected:          bool  # computed: True if wa_phone_number_id is set

    class Config:
        from_attributes = True  # allows building from SQLAlchemy model instances


class AgentConfigUpdate(BaseModel):
    """
    What the "Save Changes" button sends to the backend.
    Every field is Optional because the client might only change one setting.
    The Field() calls define validation rules and sane boundaries.
    """
    business_name: Optional[str]   = Field(None, min_length=1, max_length=200)
    is_bot_active: Optional[bool]  = None
    system_prompt: Optional[str]   = Field(None, min_length=10, max_length=5000)
    welcome_message: Optional[str] = Field(None, max_length=500)
    ai_model:  Optional[str]       = None
    language:  Optional[str]       = None

    # We validate temperature to prevent values outside the 0.1–1.0 range
    temperature: Optional[float]   = Field(None, ge=0.1, le=1.0)
    max_tokens:  Optional[int]     = Field(None, ge=50, le=1000)
    reply_delay_seconds: Optional[int] = Field(None, ge=0, le=30)

    @field_validator("ai_model")
    @classmethod
    def validate_model(cls, v):
        # Only allow known models — prevents clients from sending
        # arbitrary strings that would fail at the AI API level
        allowed = {
            "gemini-2.0-flash", "gemini-1.5-pro",
            "gemini-2.5-flash-preview", "gemini-2.0-flash-lite",
            "gpt-4o-mini", "gpt-4o",
        }
        if v and v not in allowed:
            raise ValueError(f"Model '{v}' is not supported.")
        return v


class AgentTestRequest(BaseModel):
    """
    The payload sent when a client types in the test chat and hits send.
    We pass the CURRENT (possibly unsaved) config so the preview
    reflects exactly what the bot would do if the client saves now.
    """
    message:       str   = Field(..., min_length=1, max_length=1000)
    system_prompt: str   = Field(..., min_length=10)
    model:         str   = "gemini-2.0-flash"
    language:      str   = "auto"
    temperature:   float = Field(0.7, ge=0.1, le=1.0)
    max_tokens:    int   = Field(400,  ge=50,  le=1000)


class AgentTestResponse(BaseModel):
    reply:        str
    model_used:   str
    tokens_used:  int


class AgentStatsResponse(BaseModel):
    """
    The four stat cards shown in the right column of My Agent.
    These are aggregated from the conversations and messages tables.
    """
    conversations_this_month: int
    messages_handled:         int
    escalations_this_month:   int
    avg_response_time_seconds: float