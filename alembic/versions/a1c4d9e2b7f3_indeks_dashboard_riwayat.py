"""indeks untuk filter tanggal dashboard dan riwayat

Revision ID: a1c4d9e2b7f3
Revises: efdf691e9e63
Create Date: 2026-10-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1c4d9e2b7f3'
down_revision: Union[str, Sequence[str], None] = 'efdf691e9e63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_compliance_stats_bucket_start', 'compliance_stats', ['bucket_start'], unique=False)
    op.create_index('ix_detection_logs_detected_at', 'detection_logs', ['detected_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_detection_logs_detected_at', table_name='detection_logs')
    op.drop_index('ix_compliance_stats_bucket_start', table_name='compliance_stats')