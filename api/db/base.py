# Import all the models, so that Base has them before being imported by Alembic
from api.db.base_class import Base  # noqa: F401
from api.models.user import User  # noqa: F401
