"""Independent discovery intake tables; no existing CRM data is changed."""

from alembic import op

revision = "0008_discovery"
down_revision = "0007_regenerate"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE discovery_profiles (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        owner_id VARCHAR(36) NOT NULL,
        name VARCHAR(200) NOT NULL,
        product VARCHAR(200) NOT NULL,
        keywords JSON NOT NULL,
        regions JSON NOT NULL,
        visibility VARCHAR(16) NOT NULL,
        version BIGINT UNSIGNED NOT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_discovery_visibility CHECK (visibility IN ('PRIVATE',
        'TEAM')),
        CONSTRAINT ck_discovery_profile_version CHECK (version >= 1),
        FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE RESTRICT
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )
    op.execute(
        """
        CREATE INDEX ix_discovery_profile_owner ON discovery_profiles (owner_id,
        created_at,
        id)
        """
    )
    op.execute(
        """
        CREATE TABLE discovery_access (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        profile_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        user_id VARCHAR(36) NOT NULL,
        is_active BOOL NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (profile_id,
        user_id),
        FOREIGN KEY(profile_id) REFERENCES discovery_profiles (id) ON DELETE RESTRICT,
        FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )
    op.execute(
        """
        CREATE TABLE discovery_materials (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        profile_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        uploaded_by VARCHAR(36) NOT NULL,
        title VARCHAR(200) NOT NULL,
        purpose VARCHAR(32) NOT NULL,
        content MEDIUMTEXT NOT NULL,
        original_bytes MEDIUMBLOB NOT NULL,
        sha256 BINARY(32) NOT NULL,
        created_at DATETIME(6) NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_discovery_purpose CHECK (purpose IN ('SELLER_CAPABILITY',
        'BUYER_DEMAND')),
        UNIQUE (profile_id,
        purpose,
        sha256),
        FOREIGN KEY(profile_id) REFERENCES discovery_profiles (id) ON DELETE RESTRICT,
        FOREIGN KEY(uploaded_by) REFERENCES users (id) ON DELETE RESTRICT
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )
    op.execute(
        """
        CREATE INDEX ix_discovery_material_profile ON discovery_materials (profile_id,
        created_at,
        id)
        """
    )
    op.execute(
        """
        CREATE TABLE discovery_runs (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        profile_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        created_by VARCHAR(36) NOT NULL,
        request_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        request_hash BINARY(32) NOT NULL,
        profile_snapshot JSON NOT NULL,
        status VARCHAR(16) NOT NULL,
        attempts INTEGER NOT NULL,
        lease_token CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
        lease_until DATETIME(6),
        error_code VARCHAR(64),
        result_count INTEGER NOT NULL,
        version BIGINT UNSIGNED NOT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (created_by,
        request_token),
        CONSTRAINT ck_discovery_run CHECK (status IN ('QUEUED',
        'RUNNING',
        'SUCCEEDED',
        'FAILED')),
        CONSTRAINT ck_discovery_run_version CHECK (version >= 1 AND attempts >= 0 AND
        attempts <= 3),
        FOREIGN KEY(profile_id) REFERENCES discovery_profiles (id) ON DELETE RESTRICT,
        FOREIGN KEY(created_by) REFERENCES users (id) ON DELETE RESTRICT
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )
    op.execute(
        """
        CREATE INDEX ix_discovery_run_claim ON discovery_runs (status,
        lease_until,
        created_at,
        id)
        """
    )
    op.execute(
        """
        CREATE TABLE discovery_run_materials (
        run_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        material_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        PRIMARY KEY (run_id,
        material_id),
        FOREIGN KEY(run_id) REFERENCES discovery_runs (id) ON DELETE RESTRICT,
        FOREIGN KEY(material_id) REFERENCES discovery_materials (id) ON DELETE RESTRICT
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )
    op.execute(
        """
        CREATE TABLE discovery_leads (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        profile_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        run_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        material_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        owner_id VARCHAR(36) NOT NULL,
        buyer_name VARCHAR(200) NOT NULL,
        project_name VARCHAR(200) NOT NULL,
        notice_type VARCHAR(32) NOT NULL,
        analysis JSON NOT NULL,
        status VARCHAR(24) NOT NULL,
        summary_shared BOOL NOT NULL,
        review_note VARCHAR(1000),
        account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
        version BIGINT UNSIGNED NOT NULL,
        created_at DATETIME(6) NOT NULL,
        updated_at DATETIME(6) NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (material_id),
        CONSTRAINT ck_discovery_lead CHECK (status IN ('NEW',
        'IN_REVIEW',
        'QUALIFIED',
        'DISQUALIFIED')),
        CONSTRAINT ck_discovery_lead_version CHECK (version >= 1),
        FOREIGN KEY(profile_id) REFERENCES discovery_profiles (id) ON DELETE RESTRICT,
        FOREIGN KEY(run_id) REFERENCES discovery_runs (id) ON DELETE RESTRICT,
        FOREIGN KEY(material_id) REFERENCES discovery_materials (id) ON DELETE RESTRICT,
        FOREIGN KEY(owner_id) REFERENCES users (id) ON DELETE RESTRICT,
        FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )
    op.execute(
        """
        CREATE INDEX ix_discovery_lead_profile ON discovery_leads (profile_id,
        status,
        created_at,
        id)
        """
    )
    op.execute(
        """
        CREATE TABLE discovery_account_links (
        id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        lead_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        account_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        actor_id VARCHAR(36) NOT NULL,
        request_key VARCHAR(128) NOT NULL,
        request_hash BINARY(32) NOT NULL,
        result JSON NOT NULL,
        created_at DATETIME(6) NOT NULL,
        PRIMARY KEY (id),
        UNIQUE (lead_id),
        FOREIGN KEY(lead_id) REFERENCES discovery_leads (id) ON DELETE RESTRICT,
        FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
        FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE RESTRICT
        )ENGINE=InnoDB CHARSET=utf8mb4
        """
    )


def downgrade():
    raise RuntimeError("Discovery intake rollback requires a reviewed forward repair")
