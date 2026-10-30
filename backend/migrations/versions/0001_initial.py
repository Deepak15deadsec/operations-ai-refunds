"""Initial schema: business data, runs, approvals, effects, audit, job queue.

Revision ID: 0001
Revises:
Create Date: 2026-10-30
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = "timestamptz NOT NULL DEFAULT now()"

SCHEMA = f"""
CREATE SCHEMA IF NOT EXISTS langgraph;

CREATE TABLE tenants (
    id uuid PRIMARY KEY,
    name varchar(200) NOT NULL,
    created_at {TS}, updated_at {TS}
);

CREATE TABLE customers (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    name varchar(200) NOT NULL,
    email varchar(320) NOT NULL,
    created_at {TS}, updated_at {TS},
    UNIQUE (tenant_id, id)
);

CREATE TABLE orders (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    order_number varchar(32) NOT NULL,
    customer_id uuid NOT NULL,
    total_amount_minor bigint NOT NULL CHECK (total_amount_minor >= 0),
    currency varchar(3) NOT NULL CHECK (currency = 'INR'),
    payment_status varchar(16) NOT NULL CHECK (payment_status IN ('paid','pending','failed')),
    shipping_status varchar(16) NOT NULL
        CHECK (shipping_status IN ('pending','in_transit','delayed','delivered','cancelled')),
    promised_delivery_at timestamptz NOT NULL,
    actual_delivery_at timestamptz,
    created_at {TS}, updated_at {TS},
    UNIQUE (tenant_id, order_number),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers(tenant_id, id)
);

CREATE TABLE tickets (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    ticket_number varchar(32) NOT NULL,
    customer_id uuid NOT NULL,
    order_id uuid,
    subject varchar(300) NOT NULL,
    description text NOT NULL,
    priority varchar(16) NOT NULL CHECK (priority IN ('low','medium','high','urgent')),
    status varchar(16) NOT NULL CHECK (status IN ('open','pending','resolved','escalated')),
    created_at {TS}, updated_at {TS},
    UNIQUE (tenant_id, ticket_number),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, customer_id) REFERENCES customers(tenant_id, id),
    FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, id)
);
CREATE INDEX ix_tickets_tenant_status_priority ON tickets (tenant_id, status, priority);

CREATE TABLE delivery_events (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    order_id uuid NOT NULL,
    event_type varchar(64) NOT NULL,
    event_time timestamptz NOT NULL,
    description text NOT NULL,
    created_at {TS}, updated_at {TS},
    FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, id)
);
CREATE INDEX ix_delivery_events_order ON delivery_events (tenant_id, order_id, event_time);

CREATE TABLE refund_policies (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    version varchar(32) NOT NULL,
    effective_from timestamptz NOT NULL,
    min_delay_days integer NOT NULL DEFAULT 5 CHECK (min_delay_days >= 0),
    refund_percent integer NOT NULL DEFAULT 100 CHECK (refund_percent BETWEEN 0 AND 100),
    active boolean NOT NULL DEFAULT false,
    policy_text text NOT NULL,
    created_at {TS}, updated_at {TS},
    UNIQUE (tenant_id, version)
);
CREATE UNIQUE INDEX ux_refund_policies_one_active ON refund_policies (tenant_id) WHERE active;

CREATE TABLE agent_runs (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    requested_by_user_id varchar(255) NOT NULL,
    parent_run_id uuid REFERENCES agent_runs(id),
    ticket_id uuid,
    mode varchar(16) NOT NULL DEFAULT 'ticket' CHECK (mode IN ('ticket','batch')),
    original_instruction text NOT NULL,
    batch_filters jsonb,
    thread_id varchar(64) NOT NULL UNIQUE,
    status varchar(32) NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued','running','investigating','validating','awaiting_approval','resuming','executing',
        'completed','completed_no_action','rejected','failed','cancelled','needs_human_review')),
    error_code varchar(64),
    error_message text,
    findings jsonb,
    summary jsonb,
    usage jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    created_at {TS}, updated_at {TS},
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, ticket_id) REFERENCES tickets(tenant_id, id)
);
CREATE INDEX ix_agent_runs_tenant_created ON agent_runs (tenant_id, created_at DESC);
CREATE INDEX ix_agent_runs_parent ON agent_runs (parent_run_id);

CREATE TABLE agent_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    run_id uuid NOT NULL,
    event_type varchar(64) NOT NULL,
    payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    created_at {TS},
    FOREIGN KEY (tenant_id, run_id) REFERENCES agent_runs(tenant_id, id)
);
CREATE INDEX ix_agent_events_run ON agent_events (run_id, id);

CREATE TABLE proposed_actions (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    run_id uuid NOT NULL,
    ticket_id uuid NOT NULL,
    action_type varchar(32) NOT NULL CHECK (action_type IN ('refund','send_reply','escalate_ticket')),
    payload jsonb NOT NULL,
    payload_sha256 varchar(64) NOT NULL,
    policy_version varchar(32),
    status varchar(32) NOT NULL DEFAULT 'proposed' CHECK (status IN (
        'proposed','pending_approval','approved','rejected','executing','completed','failed',
        'expired','needs_review')),
    status_reason varchar(64),
    reason text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at {TS}, updated_at {TS},
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES agent_runs(tenant_id, id),
    FOREIGN KEY (tenant_id, ticket_id) REFERENCES tickets(tenant_id, id)
);
CREATE INDEX ix_proposed_actions_run ON proposed_actions (run_id);

CREATE TABLE approval_requests (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    action_id uuid NOT NULL UNIQUE,
    status varchar(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','rejected','expired')),
    requested_by varchar(255) NOT NULL,
    decided_by varchar(255),
    decided_at timestamptz,
    decision_note text,
    expires_at timestamptz NOT NULL,
    action_hash varchar(64) NOT NULL,
    created_at {TS}, updated_at {TS},
    FOREIGN KEY (tenant_id, action_id) REFERENCES proposed_actions(tenant_id, id),
    CHECK ((status = 'pending') = (decided_at IS NULL) OR status = 'expired')
);
CREATE INDEX ix_approval_requests_tenant_status ON approval_requests (tenant_id, status, expires_at);

CREATE TABLE refunds (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    order_id uuid NOT NULL,
    action_id uuid UNIQUE,
    idempotency_key varchar(128) NOT NULL UNIQUE,
    amount_minor bigint NOT NULL CHECK (amount_minor > 0),
    currency varchar(3) NOT NULL CHECK (currency = 'INR'),
    status varchar(32) NOT NULL DEFAULT 'simulated_success' CHECK (status = 'simulated_success'),
    created_at {TS}, updated_at {TS},
    UNIQUE (tenant_id, order_id),
    FOREIGN KEY (tenant_id, order_id) REFERENCES orders(tenant_id, id),
    FOREIGN KEY (tenant_id, action_id) REFERENCES proposed_actions(tenant_id, id)
);

CREATE TABLE outbound_messages (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    ticket_id uuid NOT NULL,
    action_id uuid NOT NULL UNIQUE,
    idempotency_key varchar(128) NOT NULL UNIQUE,
    destination varchar(320) NOT NULL,
    body text NOT NULL,
    status varchar(32) NOT NULL DEFAULT 'simulated_sent' CHECK (status = 'simulated_sent'),
    created_at {TS},
    FOREIGN KEY (tenant_id, ticket_id) REFERENCES tickets(tenant_id, id),
    FOREIGN KEY (tenant_id, action_id) REFERENCES proposed_actions(tenant_id, id)
);

CREATE TABLE audit_events (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    actor_type varchar(16) NOT NULL CHECK (actor_type IN ('user','agent','system')),
    actor_id varchar(255) NOT NULL,
    run_id uuid REFERENCES agent_runs(id),
    action_id uuid REFERENCES proposed_actions(id),
    event_type varchar(64) NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    created_at {TS}
);
CREATE INDEX ix_audit_events_tenant_created ON audit_events (tenant_id, created_at DESC);

CREATE TABLE worker_jobs (
    id uuid PRIMARY KEY,
    tenant_id uuid REFERENCES tenants(id),
    run_id uuid REFERENCES agent_runs(id),
    job_type varchar(32) NOT NULL CHECK (job_type IN ('start','resume','expire_approvals')),
    dedupe_key varchar(200) NOT NULL UNIQUE,
    payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    status varchar(16) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','leased','done','failed','cancelled')),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    last_error text,
    available_at timestamptz NOT NULL DEFAULT now(),
    lease_owner varchar(128),
    leased_until timestamptz,
    created_at {TS}, updated_at {TS}
);
CREATE INDEX ix_worker_jobs_claim ON worker_jobs (status, available_at);
CREATE INDEX ix_worker_jobs_run ON worker_jobs (run_id, status);
"""

TRIGGERS = """
-- Append-only audit log. app.maintenance='on' (SET LOCAL) is used only by seeding/test resets.
CREATE FUNCTION forbid_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('app.maintenance', true), 'off') = 'on' THEN
        RETURN coalesce(OLD, NEW);
    END IF;
    RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER audit_events_no_update_delete BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION forbid_audit_mutation();
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_audit_mutation();

-- Action arguments are immutable once submitted; a modified action needs a new proposal.
CREATE FUNCTION forbid_action_payload_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('app.maintenance', true), 'off') = 'on' THEN
        RETURN NEW;
    END IF;
    IF NEW.payload IS DISTINCT FROM OLD.payload
       OR NEW.payload_sha256 IS DISTINCT FROM OLD.payload_sha256
       OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
       OR NEW.action_type IS DISTINCT FROM OLD.action_type
       OR NEW.ticket_id IS DISTINCT FROM OLD.ticket_id THEN
        RAISE EXCEPTION 'proposed action % is immutable', OLD.id USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER proposed_actions_immutable BEFORE UPDATE ON proposed_actions
    FOR EACH ROW EXECUTE FUNCTION forbid_action_payload_change();

-- Read-only role used by the MCP server, if the role exists (created by infra/postgres/init.sql).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_readonly') THEN
        GRANT USAGE ON SCHEMA public TO app_readonly;
        GRANT SELECT ON tenants, customers, orders, tickets, delivery_events, refund_policies, refunds
            TO app_readonly;
    END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(SCHEMA)
    op.execute(TRIGGERS)


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS worker_jobs, audit_events, outbound_messages, refunds, approval_requests,
            proposed_actions, agent_events, agent_runs, refund_policies, delivery_events, tickets, orders,
            customers, tenants CASCADE;
        DROP FUNCTION IF EXISTS forbid_audit_mutation, forbid_action_payload_change;
        """
    )
