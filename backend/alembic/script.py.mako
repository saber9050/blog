"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

# Alembic 的版本标识
revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    """升级。"""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """回滚。

    ⚠️ MySQL 的 DDL 不支持事务，升级中途失败不会自动回滚，
    所以每个迁移文件尽量只做一件事。
    """
    ${downgrades if downgrades else "pass"}
