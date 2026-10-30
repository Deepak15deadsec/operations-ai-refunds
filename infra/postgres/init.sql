-- Runs once when the Postgres volume is first created.
-- Read-only role for the MCP server (SELECT grants are applied by the Alembic migration).
CREATE ROLE app_readonly LOGIN PASSWORD 'local_only_ro';
GRANT CONNECT ON DATABASE operations TO app_readonly;
