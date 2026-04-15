"""add full-text search on chat_messages

Revision ID: a8_add_message_search
Revises: a7_add_attachments
Create Date: 2026-04-14

Adds:
- chat_messages.search_vector (tsvector)  — derived from body
- GIN index on search_vector             — O(log N) keyword lookup
- Trigger that keeps search_vector in sync with body (insert + update)
- Backfill for existing rows

Uses 'english' config for stemming (running→run, played→play).
For Italian content the 'italian' config would be better, but english
handles mixed English/Italian passably in MVP.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a8_add_message_search'
down_revision: Union[str, None] = 'a7_add_attachments'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add the tsvector column (nullable initially, backfill, then can be NOT NULL)
    op.execute("""
        ALTER TABLE chat_messages
        ADD COLUMN search_vector tsvector
    """)

    # 2. GIN index — the right kind for tsvector, enables fast @@ queries
    op.execute("""
        CREATE INDEX ix_chat_messages_search_vector
        ON chat_messages
        USING GIN (search_vector)
    """)

    # 3. Trigger function: recomputes search_vector from body on INSERT/UPDATE
    op.execute("""
        CREATE OR REPLACE FUNCTION chat_messages_search_vector_update()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english', COALESCE(NEW.body, ''));
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)

    op.execute("""
        CREATE TRIGGER chat_messages_search_vector_trigger
        BEFORE INSERT OR UPDATE OF body
        ON chat_messages
        FOR EACH ROW
        EXECUTE FUNCTION chat_messages_search_vector_update()
    """)

    # 4. Backfill existing rows so search works immediately on existing data
    op.execute("""
        UPDATE chat_messages
        SET search_vector = to_tsvector('english', COALESCE(body, ''))
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS chat_messages_search_vector_trigger ON chat_messages")
    op.execute("DROP FUNCTION IF EXISTS chat_messages_search_vector_update()")
    op.execute("DROP INDEX IF EXISTS ix_chat_messages_search_vector")
    op.execute("ALTER TABLE chat_messages DROP COLUMN IF EXISTS search_vector")
