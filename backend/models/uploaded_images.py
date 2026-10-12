from core.database import Base
from core.time_utils import utc_now
from sqlalchemy import CheckConstraint, Column, DateTime, Integer, LargeBinary, String


class Uploaded_images(Base):
    """Fotos subidas desde el CRM, guardadas en la misma base de datos.

    shortcut: Postgres como almacén evita otro servicio; sirve mientras cada tienda
    tenga pocas decenas de MB en fotos. Más allá conviene un almacén de objetos.
    """

    __tablename__ = "uploaded_images"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_uploaded_images_size_positive"),
        {"extend_existing": True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, nullable=False)
    content_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now)
