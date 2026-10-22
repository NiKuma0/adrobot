"""singular table names, named constraints

Revision ID: 5d1c7e0a9b42
Revises: a8b9eb798419
Create Date: 2026-10-21 12:00:00.000000

Tables are recreated (not renamed) so that every constraint gets a name from the
metadata naming convention; SQLite can't rename constraints in place.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5d1c7e0a9b42'
down_revision: str | Sequence[str] | None = 'a8b9eb798419'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CAMPAIGN_COLUMNS = "id, keitaro_id, name, alias, created_at, synced_at"
STREAM_COLUMNS = "id, campaign_id, keitaro_id, name, position, schema"
STREAM_OFFER_COLUMNS = (
    "id, stream_id, offer_id, offer_name, state, share, pinned, published_state, published_share"
)


def _create_tables(campaign: str, stream: str, stream_offer: str, named: bool) -> None:
    def name(n: str) -> str | None:
        return n if named else None

    op.create_table(campaign,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('keitaro_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('alias', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('synced_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=name('pk_campaign')),
    sa.UniqueConstraint('keitaro_id', name=name('uq_campaign_keitaro_id'))
    )
    op.create_table(stream,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('keitaro_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('schema', sa.String(length=32), nullable=False),
    sa.ForeignKeyConstraint(['campaign_id'], [f'{campaign}.id'], ondelete='CASCADE',
                            name=name('fk_stream_campaign_id_campaign')),
    sa.PrimaryKeyConstraint('id', name=name('pk_stream')),
    sa.UniqueConstraint('keitaro_id', name=name('uq_stream_keitaro_id'))
    )
    op.create_table(stream_offer,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stream_id', sa.Integer(), nullable=False),
    sa.Column('offer_id', sa.Integer(), nullable=False),
    sa.Column('offer_name', sa.String(length=512), nullable=False),
    sa.Column('state', sa.String(length=16), nullable=False),
    sa.Column('share', sa.Integer(), nullable=False),
    sa.Column('pinned', sa.Boolean(), nullable=False),
    sa.Column('published_state', sa.String(length=16), nullable=True),
    sa.Column('published_share', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['stream_id'], [f'{stream}.id'], ondelete='CASCADE',
                            name=name('fk_stream_offer_stream_id_stream')),
    sa.PrimaryKeyConstraint('id', name=name('pk_stream_offer')),
    sa.UniqueConstraint('stream_id', 'offer_id', name=name('uq_stream_offer_stream_id_offer_id'))
    )


def _move(src: tuple[str, str, str], dst: tuple[str, str, str]) -> None:
    for s, d, columns in zip(src, dst, (CAMPAIGN_COLUMNS, STREAM_COLUMNS, STREAM_OFFER_COLUMNS)):
        op.execute(f"INSERT INTO {d} ({columns}) SELECT {columns} FROM {s}")
        if op.get_bind().dialect.name == "postgresql":
            # ids were copied explicitly, so the serial sequence has to catch up
            op.execute(f"SELECT setval(pg_get_serial_sequence('{d}', 'id'), coalesce(max(id), 0) + 1, false) FROM {d}")
    for s in reversed(src):
        op.drop_table(s)


OLD = ('campaigns', 'streams', 'stream_offers')
NEW = ('campaign', 'stream', 'stream_offer')


def upgrade() -> None:
    """Upgrade schema."""
    _create_tables(*NEW, named=True)
    _move(OLD, NEW)


def downgrade() -> None:
    """Downgrade schema."""
    _create_tables(*OLD, named=False)
    _move(NEW, OLD)
