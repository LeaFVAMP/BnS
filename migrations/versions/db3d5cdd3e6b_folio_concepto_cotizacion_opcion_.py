"""folio + concepto + cotizacion_opcion + cotizacion_item + uq folio/child_seq

Revision ID: db3d5cdd3e6b
Revises: 5edf09ec4627
Create Date: 2025-09-10 04:40:52.086502

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'db3d5cdd3e6b'
down_revision = '5edf09ec4627'
branch_labels = None
depends_on = None


def upgrade():
    # Para SQLite, usa batch_alter_table
    with op.batch_alter_table("concepto", schema=None) as batch_op:
        batch_op.add_column(sa.Column("moneda", sa.String(length=3), nullable=False, server_default="MXN"))

    # Si quieres retirar el server_default (opcional; en SQLite no siempre aplica)
    try:
        with op.batch_alter_table("concepto", schema=None) as batch_op:
            batch_op.alter_column("moneda", server_default=None)
    except Exception:
        # en SQLite probablemente no se pueda; lo ignoramos
        pass


def downgrade():
    with op.batch_alter_table("concepto", schema=None) as batch_op:
        batch_op.drop_column("moneda")