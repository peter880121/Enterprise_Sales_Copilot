"""Add isolated public-search receipts and quota serialization; no CRM changes."""

from alembic import op

revision = "0009_search"
down_revision = "0008_discovery"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE discovery_search_guard (
        id INTEGER NOT NULL,
        version INTEGER NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_search_guard_singleton CHECK (id = 1)
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )
    op.execute(
        """
        CREATE TABLE discovery_search_runs (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        profile_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        created_by VARCHAR(36) NOT NULL,
        request_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        request_hash BINARY(32) NOT NULL,
        profile_version INTEGER NOT NULL,
        public_query VARCHAR(200) NOT NULL,
        endpoint VARCHAR(100) NOT NULL,
        status VARCHAR(24) NOT NULL,
        provider_attempted BOOL NOT NULL,
        lease_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
        lease_until DATETIME(6),
        started_at DATETIME(6),
        completed_at DATETIME(6),
        error_code VARCHAR(64),
        result JSON,
        version BIGINT UNSIGNED NOT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT uq_search_actor_token UNIQUE (created_by, request_token),
        CONSTRAINT ck_search_status CHECK (status IN
        ('QUEUED','RUNNING','SUCCEEDED','FAILED','OUTCOME_UNKNOWN')),
        CONSTRAINT ck_search_versions CHECK (version >= 1 AND profile_version >= 1),
        FOREIGN KEY(profile_id) REFERENCES discovery_profiles (id) ON DELETE RESTRICT,
        FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )
    op.execute(
        """
        CREATE INDEX ix_search_claim ON discovery_search_runs (status, lease_until,
        created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_search_global_quota ON discovery_search_runs (created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_search_profile ON discovery_search_runs (profile_id, created_at, id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_search_user_quota ON discovery_search_runs (created_by, created_at)
        """
    )
    op.execute(
        """
        INSERT INTO discovery_search_guard (id, version) VALUES (1, 1)
        """
    )


def downgrade():
    raise RuntimeError("Search receipts must be retained; use a reviewed forward migration")
