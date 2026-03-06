"""
Copyright (c) Microsoft Corporation.
Licensed under the MIT License.
"""

"""
MCP server for Azure Database for PostgreSQL - Flexible Server.

This server exposes the following capabilities:

Tools:
- create_table: Creates a table in a database.
- drop_table: Drops a table in a database.
- get_databases: Gets the list of all the databases in a server instance.
- get_schemas: Gets schemas of all the tables.
- get_server_config: Gets the configuration of a server instance. [Available with Microsoft EntraID]
- get_server_parameter: Gets the value of a server parameter. [Available with Microsoft EntraID]
- query_data: Runs read queries on a database.
- update_values: Updates or inserts values into a table.

Resources:
- databases: Gets the list of all databases in a server instance.

To run the code using PowerShell, expose the following variables:

```
$env:PGHOST="<Fully qualified name of your Azure Database for PostgreSQL instance>"
$env:PGUSER="<Your Azure Database for PostgreSQL username>"
$env:PGPASSWORD="<Your password>"
```

Run the MCP Server using the following command:

```
python azure_postgresql_mcp.py
```

For detailed usage instructions, please refer to the README.md file.

"""

import json
import logging
import os
import sys
import getpass
import ssl
import threading
import urllib.parse
import urllib.request

import certifi
import psycopg
from azure.identity import DefaultAzureCredential
from azure.mgmt.postgresqlflexibleservers import PostgreSQLManagementClient
from azure.mgmt.postgresqlflexibleservers.models import FirewallRule
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.resources import FunctionResource

logger = logging.getLogger("azure_postgresql_mcp")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setLevel(logging.DEBUG)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)

logging.getLogger("azure").setLevel(logging.ERROR)


class AzurePostgreSQLMCP:
    def init(self):
        self._firewall_update_thread = None
        self.aad_in_use = os.environ.get("AZURE_USE_AAD")
        self.dbhost = self.get_environ_variable("PGHOST")
        self.dbuser = urllib.parse.quote(self.get_environ_variable("PGUSER"))

        logger.info(f"Initialising MCP for host: {self.dbhost}, user: {self.dbuser}")
        logger.info(f"AZURE_USE_AAD={self.aad_in_use!r}")

        self._aad_enabled = str(self.aad_in_use).strip().lower() in ("true", "1", "yes")

        if self._aad_enabled:
            self.subscription_id = self.get_environ_variable("AZURE_SUBSCRIPTION_ID")
            self.resource_group_name = self.get_environ_variable("AZURE_RESOURCE_GROUP")
            self.server_name = self.dbhost.split(".", 1)[0] if "." in self.dbhost else self.dbhost
            logger.info(
                f"AAD enabled — subscription={self.subscription_id}, "
                f"resource_group={self.resource_group_name}, server={self.server_name}"
            )
            self.credential = DefaultAzureCredential()
            self.postgresql_client = PostgreSQLManagementClient(self.credential, self.subscription_id)
        else:
            logger.info("AAD disabled — using password auth (PGPASSWORD).")

        # Automatically ensure the current machine's IP is whitelisted in the firewall.
        # Only runs when AZURE_AUTO_FIREWALL=True (requires the management client above).
        self.start_firewall_update()

        # Password initialisation must come after AAD setup (token requires credential).
        self.password = self.get_password()
        logger.info("Password/token obtained successfully.")

    def start_firewall_update(self):
        """Starts firewall update in background unless explicitly configured to run synchronously."""
        auto_firewall_async = str(os.environ.get("AZURE_AUTO_FIREWALL_ASYNC", "true")).strip().lower()
        if auto_firewall_async in ("false", "0", "no"):
            logger.info("AZURE_AUTO_FIREWALL_ASYNC disabled — running firewall update synchronously.")
            self.ensure_ip_whitelisted()
            return

        self._firewall_update_thread = threading.Thread(
            target=self.ensure_ip_whitelisted,
            name="azure-pg-firewall-update",
            daemon=True,
        )
        self._firewall_update_thread.start()
        logger.info("Firewall auto-whitelisting started in background thread.")

    def ensure_ip_whitelisted(self):
        """
        Ensures the current machine's public IP is allowed through the Azure PostgreSQL
        firewall. Only runs when AZURE_AUTO_FIREWALL=True and AAD is enabled.


                Optional env vars:
                    AZURE_AUTO_FIREWALL       - Set to "True" to enable (default: disabled)
                    AZURE_AUTO_FIREWALL_ASYNC - Set to "False" to block startup until firewall update completes
                    AZURE_FIREWALL_RULE_NAME  - Rule name to create/update (default: "mcp-<username>")
        """
        auto_firewall = str(os.environ.get("AZURE_AUTO_FIREWALL", "")).strip().lower()
        if auto_firewall not in ("true", "1", "yes"):
            logger.debug(
                "AZURE_AUTO_FIREWALL not set or not truthy — skipping firewall update. "
                "Set AZURE_AUTO_FIREWALL=True in your MCP env config to enable auto-whitelisting."
            )
            return

        if not self._aad_enabled:
            logger.warning("AZURE_AUTO_FIREWALL requires AZURE_USE_AAD=True. Skipping firewall update.")
            return

        logger.info("AZURE_AUTO_FIREWALL enabled — checking current public IP...")

        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen("https://api.ipify.org", timeout=5, context=ssl_context) as resp:
                current_ip = resp.read().decode().strip()
            logger.info(f"Current public IP: {current_ip}")
        except Exception as e:
            logger.warning(f"Could not determine public IP for firewall update: {e}")
            return

        # Check the cache — only call Azure when the IP has actually changed.
        cache_path = os.path.expanduser("~/.azure_pg_mcp_ip_cache")
        cached_ip = None
        if os.path.exists(cache_path):
            try:
                with open(cache_path) as f:
                    cached_ip = f.read().strip()
                logger.debug(f"Cached IP: {cached_ip!r}")
            except OSError as e:
                logger.warning(f"Could not read IP cache from {cache_path}: {e}")

        if current_ip == cached_ip:
            logger.info(f"Public IP {current_ip} unchanged — skipping firewall update.")
            return

        default_rule_name = f"mcp-{getpass.getuser()}"
        rule_name = os.environ.get("AZURE_FIREWALL_RULE_NAME", default_rule_name)
        logger.info(
            f"IP changed ({cached_ip!r} → {current_ip!r}). "
            f"Updating firewall rule '{rule_name}' on server '{self.server_name}'..."
        )

        try:
            poller = self.postgresql_client.firewall_rules.begin_create_or_update(
                self.resource_group_name,
                self.server_name,
                rule_name,
                FirewallRule(start_ip_address=current_ip, end_ip_address=current_ip),
            )
            poller.result()
            logger.info(f"Firewall rule '{rule_name}' updated successfully to allow {current_ip}.")
        except Exception as e:
            logger.error(f"Failed to update firewall rule '{rule_name}': {e}")
            return

        try:
            with open(cache_path, "w") as f:
                f.write(current_ip)
            logger.debug(f"IP cache written to {cache_path}.")
        except OSError as e:
            logger.warning(f"Could not write IP cache to {cache_path}: {e}")

    @staticmethod
    def get_environ_variable(name: str):
        """Helper function to get environment variable or raise an error."""
        value = os.environ.get(name)
        if value is None:
            raise EnvironmentError(f"Environment variable {name} not found.")
        return value

    def get_password(self) -> str:
        """Get password based on the auth mode set."""
        if self._aad_enabled:
            logger.debug("Acquiring AAD token for PostgreSQL...")
            return self.credential.get_token("https://ossrdbms-aad.database.windows.net/.default").token
        else:
            return self.get_environ_variable("PGPASSWORD")

    def get_dbs_resource_uri(self):
        """Gets the resource URI exposed as MCP resource for getting list of dbs."""
        dbhost_normalized = self.dbhost.split(".", 1)[0] if "." in self.dbhost else self.dbhost
        return f"flexpg://{dbhost_normalized}/databases"

    def get_databases_internal(self) -> str:
        """Internal function which gets the list of all databases in a server instance."""
        try:
            with psycopg.connect(
                f"host={self.dbhost} user={self.dbuser} dbname='postgres' password={self.password}"
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT datname FROM pg_database WHERE datistemplate = false;")
                    colnames = [desc[0] for desc in cur.description]
                    dbs = cur.fetchall()
                    return json.dumps(
                        {
                            "columns": str(colnames),
                            "rows": "".join(str(row) for row in dbs),
                        }
                    )
        except Exception as e:
            logger.error(f"get_databases error: {str(e)}")
            return ""

    def get_databases_resource(self):
        """Gets list of databases as a resource."""
        return self.get_databases_internal()

    def get_databases(self):
        """Gets the list of all the databases in a server instance."""
        return self.get_databases_internal()

    def get_connection_uri(self, dbname: str) -> str:
        """Construct URI for connection."""
        return f"host={self.dbhost} dbname={dbname} user={self.dbuser} password={self.password}"

    def get_schemas(self, database: str):
        """Gets schemas of all the tables."""
        try:
            with psycopg.connect(self.get_connection_uri(database)) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT table_name, column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position;"
                    )
                    colnames = [desc[0] for desc in cur.description]
                    tables = cur.fetchall()
                    return json.dumps(
                        {
                            "columns": str(colnames),
                            "rows": "".join(str(row) for row in tables),
                        }
                    )
        except Exception as e:
            logger.error(f"get_schemas error: {str(e)}")
            return ""

    def query_data(self, dbname: str, s: str) -> str:
        """Runs read queries on a database."""
        try:
            with psycopg.connect(self.get_connection_uri(dbname)) as conn:
                with conn.cursor() as cur:
                    cur.execute(s)
                    rows = cur.fetchall()
                    colnames = [desc[0] for desc in cur.description]
                    return json.dumps(
                        {
                            "columns": str(colnames),
                            "rows": ",".join(str(row) for row in rows),
                        }
                    )
        except Exception as e:
            logger.error(f"query_data error: {str(e)}")
            return ""

    def exec_and_commit(self, dbname: str, s: str) -> None:
        """Internal function to execute and commit transaction."""
        try:
            with psycopg.connect(self.get_connection_uri(dbname)) as conn:
                with conn.cursor() as cur:
                    cur.execute(s)
                    conn.commit()
        except Exception as e:
            logger.error(f"exec_and_commit error: {str(e)}")

    def update_values(self, dbname: str, s: str):
        """Updates or inserts values into a table."""
        self.exec_and_commit(dbname, s)

    def create_table(self, dbname: str, s: str):
        """Creates a table in a database."""
        self.exec_and_commit(dbname, s)

    def drop_table(self, dbname: str, s: str):
        """Drops a table in a database."""
        self.exec_and_commit(dbname, s)

    def get_server_config(self) -> str:
        """Gets the configuration of a server instance. [Available with Microsoft EntraID]"""
        if self._aad_enabled:
            try:
                server = self.postgresql_client.servers.get(self.resource_group_name, self.server_name)
                return json.dumps(
                    {
                        "server": {
                            "name": server.name,
                            "location": server.location,
                            "version": server.version,
                            "sku": server.sku.name,
                            "storage_profile": {
                                "storage_size_gb": server.storage.storage_size_gb,
                                "backup_retention_days": server.backup.backup_retention_days,
                                "geo_redundant_backup": server.backup.geo_redundant_backup,
                            },
                        },
                    }
                )
            except Exception as e:
                logger.error(f"Failed to get PostgreSQL server configuration: {e}")
                raise e
        else:
            raise NotImplementedError("This tool is available only with Microsoft EntraID")

    def get_server_parameter(self, parameter_name: str) -> str:
        """Gets the value of a server parameter. [Available with Microsoft EntraID]"""
        if self._aad_enabled:
            try:
                configuration = self.postgresql_client.configurations.get(
                    self.resource_group_name, self.server_name, parameter_name
                )
                return json.dumps({"param": configuration.name, "value": configuration.value})
            except Exception as e:
                logger.error(f"Failed to get PostgreSQL server parameter '{parameter_name}': {e}")
                raise e
        else:
            raise NotImplementedError("This tool is available only with Microsoft EntraID")


if __name__ == "__main__":
    mcp = FastMCP("Flex PG Explorer")
    azure_pg_mcp = AzurePostgreSQLMCP()
    azure_pg_mcp.init()
    mcp.add_tool(azure_pg_mcp.get_databases)
    mcp.add_tool(azure_pg_mcp.get_schemas)
    mcp.add_tool(azure_pg_mcp.query_data)
    mcp.add_tool(azure_pg_mcp.update_values)
    mcp.add_tool(azure_pg_mcp.create_table)
    mcp.add_tool(azure_pg_mcp.drop_table)
    mcp.add_tool(azure_pg_mcp.get_server_config)
    mcp.add_tool(azure_pg_mcp.get_server_parameter)
    databases_resource = FunctionResource(
        name=azure_pg_mcp.get_dbs_resource_uri(),
        uri=azure_pg_mcp.get_dbs_resource_uri(),
        description="List of databases in the server",
        mime_type="application/json",
        fn=azure_pg_mcp.get_databases_resource,
    )
    mcp.add_resource(databases_resource)
    mcp.run()
