# app/models/__init__.py
# Importing all models here ensures SQLAlchemy's metadata knows about
# every table. If you forget to import a model, Alembic won't include
# it in migrations and get_db queries against it will fail silently.

from app.models.admin import Admin
from app.models.Tenant import Tenant
from app.models.product import Product
from app.models.Conversation import Conversation
from app.models.Message import Message

# You can now do: from app.models import Conversation, Message
# anywhere in your codebase without circular import issues.