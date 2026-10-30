"""Display names for the requester and decider (UI shows names, not OIDC subject ids).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_runs ADD COLUMN requested_by_name varchar(255)")
    op.execute("ALTER TABLE approval_requests ADD COLUMN decided_by_name varchar(255)")


def downgrade() -> None:
    op.execute("ALTER TABLE approval_requests DROP COLUMN decided_by_name")
    op.execute("ALTER TABLE agent_runs DROP COLUMN requested_by_name")
