\set app_password `cat /run/secrets/app_password`
SET custom.app_password TO :'app_password';

-- Create database bakingholic if it does not exist
SELECT 'CREATE DATABASE bakingholic OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'bakingholic')\gexec

-- Connect to bakingholic database
\c bakingholic

-- Run procedural setup in a PL/pgSQL block
DO $$
DECLARE
    app_pw text;
BEGIN
    -- Retrieve the password from the session custom setting
    app_pw := current_setting('custom.app_password', true);

    -- Create role bh_backend if it does not exist
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bh_backend') THEN
        IF app_pw IS NOT NULL AND app_pw <> '' THEN
            EXECUTE format('CREATE ROLE bh_backend WITH LOGIN PASSWORD %L', app_pw);
        ELSE
            EXECUTE 'CREATE ROLE bh_backend WITH LOGIN';
        END IF;
    END IF;

    -- Grant database privileges to bh_backend
    EXECUTE 'GRANT CONNECT ON DATABASE bakingholic TO bh_backend';
    EXECUTE 'GRANT CREATE ON DATABASE bakingholic TO bh_backend';

    -- Create target schemas if they do not exist
    EXECUTE 'CREATE SCHEMA IF NOT EXISTS alembic AUTHORIZATION bh_backend';
    EXECUTE 'CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION bh_backend';
    EXECUTE 'CREATE SCHEMA IF NOT EXISTS orders AUTHORIZATION bh_backend';
    EXECUTE 'CREATE SCHEMA IF NOT EXISTS shopee AUTHORIZATION bh_backend';
    EXECUTE 'CREATE SCHEMA IF NOT EXISTS warehouse AUTHORIZATION bh_backend';

    -- Set default privileges for new tables created by bh_backend in these schemas
    EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE bh_backend IN SCHEMA alembic, auth, orders, shopee, warehouse ' ||
            'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bh_backend';
END
$$;