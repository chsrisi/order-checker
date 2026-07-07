CREATE ROLE bh_backend WITH LOGIN PASSWORD 'secret_password'; -- change password to something secure!

GRANT CONNECT ON DATABASE bakingholic TO bh_backend;
GRANT CREATE ON DATABASE bakingholic TO bh_backend;

\c bakingholic

CREATE SCHEMA IF NOT EXISTS alembic AUTHORIZATION bh_backend;
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION bh_backend;
CREATE SCHEMA IF NOT EXISTS orders AUTHORIZATION bh_backend;
CREATE SCHEMA IF NOT EXISTS shopee AUTHORIZATION bh_backend;
CREATE SCHEMA IF NOT EXISTS warehouse AUTHORIZATION bh_backend;

ALTER DEFAULT PRIVILEGES FOR ROLE bh_backend IN SCHEMA alembic, auth, orders, shopee, warehouse
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bh_backend;