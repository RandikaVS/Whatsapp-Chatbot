# src/models/__init__.py
# Importing all models here ensures SQLAlchemy's metadata knows about
# every table. If you forget to import a model, Alembic won't include
# it in migrations and get_db queries against it will fail silently.

from src.models.admin import Admin
from src.models.tenant import Tenant
from src.models.product import Product
from src.models.Conversation import Conversation
from src.models.Message import Message

# You can now do: from src.models import Conversation, Message
# anywhere in your codebase without circular import issues.