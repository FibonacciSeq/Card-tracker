-- Create the non-owner application role used by the API and workers.
-- The container's POSTGRES_USER (cardtracker_owner) owns the schema and runs
-- migrations; RLS is only enforced for a role that is not the table owner.
CREATE ROLE cardtracker_app LOGIN PASSWORD 'cardtracker_app';

GRANT CONNECT ON DATABASE cardtracker TO cardtracker_app;
GRANT USAGE ON SCHEMA public TO cardtracker_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cardtracker_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO cardtracker_app;
