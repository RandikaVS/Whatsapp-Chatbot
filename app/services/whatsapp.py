# app/services/whatsapp.py
import httpx
from app.models.tenant import Tenant

META_API = "https://graph.facebook.com/v19.0"

class WhatsAppService:

    @staticmethod
    def send_text(tenant: Tenant, to_phone: str, message: str):
        url = f"{META_API}/{tenant.wa_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {tenant.wa_access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {"preview_url": False, "body": message}
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def send_template(tenant: Tenant, to_phone: str,
                      template_name: str, language: str = "en_US",
                      components: list = None):
        """Send approved template message (for outbound/first contact)"""
        url = f"{META_API}/{tenant.wa_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {tenant.wa_access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                "components": components or []
            }
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def send_interactive_buttons(tenant: Tenant, to_phone: str,
                                  body_text: str, buttons: list):
        """Send quick reply buttons"""
        url = f"{META_API}/{tenant.wa_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {tenant.wa_access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                        for b in buttons[:3]  # max 3 buttons
                    ]
                }
            }
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def mark_as_read(tenant: Tenant, message_id: str):
        """Mark message as read (shows blue ticks)"""
        url = f"{META_API}/{tenant.wa_phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {tenant.wa_access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id
        }
        httpx.post(url, json=payload, headers=headers)