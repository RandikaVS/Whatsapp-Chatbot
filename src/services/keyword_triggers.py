# src/services/keyword_triggers.py
from typing import Optional

# Each entry: (keywords_to_match, response_to_send, special_action)
# The special_action can be None, "escalate", or "clear_history"
TRIGGERS = [
    # Human escalation — customer explicitly wants a person
    (["human", "agent", "person", "staff", "manager", "speak to someone"],
     "I'm connecting you with one of our team members. Please wait a moment.",
     "escalate"),

    # Reset conversation — useful when the AI has gone off track
    (["restart", "reset", "start over", "clear", "new conversation"],
     "I've reset our conversation. How can I help you today?",
     "clear_history"),

    # Stop messages — customer opts out
    (["stop", "unsubscribe", "opt out", "don't contact"],
     "You have been unsubscribed. We won't send you further messages.",
     "unsubscribe"),
]


def check_keyword_triggers(text: str) -> Optional[tuple[str, Optional[str]]]:
    """
    Checks if the message matches any keyword trigger.
    
    Returns (reply_text, action) if a trigger matches, or None if no match.
    The calling code should handle the action (escalate, clear_history, etc.)
    
    We check keywords BEFORE calling the AI — if a trigger matches,
    we skip the AI call entirely and return the fixed response.
    This is faster, cheaper, and more predictable than relying on the AI
    to detect these intentions correctly every time.
    """
    text_lower = text.lower().strip()
    
    for keywords, response, action in TRIGGERS:
        if any(kw in text_lower for kw in keywords):
            return response, action
    
    return None  # no trigger matched, proceed to AI