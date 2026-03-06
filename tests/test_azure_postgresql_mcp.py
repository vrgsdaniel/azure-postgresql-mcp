import logging
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

# Constants
NETWORK_ERROR_MESSAGE = "Network error"

from azure_postgresql_mcp import AzurePostgreSQLMCP


class TestAzurePostgreSQLMCPAADEnabled(unittest.TestCase):
    """Tests for AzurePostgreSQLMCP with AAD enabled."""

    @patch("azure_postgresql_mcp.DefaultAzureCredential")
    @patch("azure_postgresql_mcp.PostgreSQLManagementClient")
    def setUp(self, mock_postgresql_client, mock_credential):
        # Mock the credential and client
        mock_credential.return_value = MagicMock()
        mock_client_instance = MagicMock()
        mock_postgresql_client.return_value = mock_client_instance

        """Set up the AzurePostgreSQLMCP instance with AAD enabled."""
        with patch.dict(
            "os.environ",
            {
                "AZURE_USE_AAD": "True",
                "PGHOST": "test-host",
                "PGUSER": "test-user",
                "PGPASSWORD": "test-password",
                "AZURE_SUBSCRIPTION_ID": "test-subscription-id",
                "AZURE_RESOURCE_GROUP": "test-resource-group",
            },
        ):
            self.azure_pg_mcp = AzurePostgreSQLMCP()
            self.azure_pg_mcp.init()

    def test_get_server_config(self):
        mock_server = MagicMock()
        mock_server.name = "test-server"
        mock_server.location = "eastus"
        mock_server.version = "12"
        mock_server.sku.name = "Standard_D2s_v3"
        mock_server.storage.storage_size_gb = 100
        mock_server.backup.backup_retention_days = 7
        mock_server.backup.geo_redundant_backup = "Enabled"

        # Ensure the mocked server response is serializable
        self.azure_pg_mcp.postgresql_client.servers.get.return_value = mock_server
        # Call the method
        result = self.azure_pg_mcp.get_server_config()

        # Assert the result
        self.assertIn("test-server", result)
        self.assertIn("eastus", result)
        self.assertIn("12", result)
        self.assertIn("Standard_D2s_v3", result)
        self.assertIn("100", result)
        self.assertIn("7", result)
        self.assertIn("Enabled", result)

    def test_get_server_parameter(self):
        # Mock the configuration response
        mock_configuration = MagicMock()
        mock_configuration.name = "max_connections"
        mock_configuration.value = "100"

        self.azure_pg_mcp.postgresql_client.configurations.get.return_value = (
            mock_configuration
        )

        # Call the method
        result = self.azure_pg_mcp.get_server_parameter("max_connections")

        # Assert the result
        self.assertIn("max_connections", result)
        self.assertIn("100", result)


class TestAzurePostgreSQLMCPAADDisabled(unittest.TestCase):
    """Tests for AzurePostgreSQLMCP with AAD disabled."""

    def setUp(self):
        patcher = patch.dict(
            "os.environ",
            {
                "PGHOST": "test-host",
                "PGUSER": "test-user",
                "PGPASSWORD": "test-password",
            },
        )
        self.addCleanup(patcher.stop)
        patcher.start()
        self.azure_pg_mcp = AzurePostgreSQLMCP()
        self.azure_pg_mcp.init()

    @patch("psycopg.connect")
    def test_query_data(self, mock_connect):
        # Mock the cursor and its behavior
        mock_cursor = MagicMock()
        mock_cursor.description = [("col1",), ("col2",)]
        mock_cursor.fetchall.return_value = [(1, "value1"), (2, "value2")]

        mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        # Call the method
        result = self.azure_pg_mcp.query_data("test_db", "SELECT * FROM test_table;")

        # Assert the result
        self.assertIn("value1", result)
        self.assertIn("value2", result)

    @patch("psycopg.connect")
    def test_create_table(self, mock_connect):
        # Mock the connection and cursor
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        # Call the method
        self.azure_pg_mcp.create_table("test_db", "CREATE TABLE test_table (id INT);")

        # Assert that the query was executed and committed
        mock_cursor.execute.assert_called_once_with("CREATE TABLE test_table (id INT);")
        mock_connect.return_value.__enter__.return_value.commit.assert_called_once()

    @patch("psycopg.connect")
    def test_drop_table(self, mock_connect):
        # Mock the connection and cursor
        mock_cursor = MagicMock()
        mock_connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value = (
            mock_cursor
        )

        # Call the method
        self.azure_pg_mcp.drop_table("test_db", "DROP TABLE test_table;")

        # Assert that the query was executed and committed
        mock_cursor.execute.assert_called_once_with("DROP TABLE test_table;")
        mock_connect.return_value.__enter__.return_value.commit.assert_called_once()


class TestAzurePostgreSQLMCPNetworkErrors(unittest.TestCase):
    """Tests for handling network errors in AzurePostgreSQLMCP."""

    @patch("azure_postgresql_mcp.DefaultAzureCredential")
    @patch("azure_postgresql_mcp.PostgreSQLManagementClient")
    def setUp(self, mock_postgresql_client, mock_credential):
        # Mock the credential and client
        mock_credential.return_value = MagicMock()
        mock_client_instance = MagicMock()
        mock_postgresql_client.return_value = mock_client_instance

        with patch.dict(
            "os.environ",
            {
                "PGHOST": "test-host",
                "PGUSER": "test-user",
                "PGPASSWORD": "test-password",
                "AZURE_SUBSCRIPTION_ID": "test-subscription-id",
                "AZURE_RESOURCE_GROUP": "test-resource-group",
                "AZURE_USE_AAD": "True",
            },
        ):
            self.azure_pg_mcp = AzurePostgreSQLMCP()
            self.azure_pg_mcp.init()

    @patch("psycopg.connect")
    def test_query_data_network_error(self, mock_connect):
        # Simulate a network error
        mock_connect.side_effect = Exception(NETWORK_ERROR_MESSAGE)

        # Call the method
        result = self.azure_pg_mcp.query_data("test_db", "SELECT * FROM test_table;")

        # Assert the result
        self.assertEqual(result, "")

    @patch("psycopg.connect")
    def test_create_table_network_error(self, mock_connect):
        # Simulate a network error
        mock_connect.side_effect = Exception("Network error")

        # Call the method
        self.azure_pg_mcp.create_table("test_db", "CREATE TABLE test_table (id INT);")

        # Assert that no exception was raised
        mock_connect.return_value.__enter__.return_value.commit.assert_not_called()

    def test_get_server_config_network_error(self):
        # Simulate a network error
        self.azure_pg_mcp.postgresql_client.servers.get.side_effect = Exception(
            NETWORK_ERROR_MESSAGE
        )

        with self.assertRaises(Exception) as context:
            self.azure_pg_mcp.get_server_config()

        # Assert the exception message
        self.assertEqual(str(context.exception), "Network error")

    def test_get_server_parameter_network_error(self):
        # Simulate a network error
        self.azure_pg_mcp.postgresql_client.configurations.get.side_effect = Exception(
            NETWORK_ERROR_MESSAGE
        )

        with self.assertRaises(Exception) as context:
            self.azure_pg_mcp.get_server_parameter("max_connections")

        # Assert the exception message
        self.assertEqual(str(context.exception), "Network error")


class TestEnsureIpWhitelisted(unittest.TestCase):
    """Tests for the ensure_ip_whitelisted automatic firewall management method."""

    _AAD_ENV = {
        "AZURE_USE_AAD": "True",
        "PGHOST": "test-host.postgres.database.azure.com",
        "PGUSER": "test-user",
        "AZURE_SUBSCRIPTION_ID": "test-sub",
        "AZURE_RESOURCE_GROUP": "test-rg",
    }

    @patch("azure_postgresql_mcp.DefaultAzureCredential")
    @patch("azure_postgresql_mcp.PostgreSQLManagementClient")
    def setUp(self, mock_pg_client_cls, mock_credential_cls):
        mock_credential_cls.return_value = MagicMock()
        self.mock_pg_client = MagicMock()
        mock_pg_client_cls.return_value = self.mock_pg_client

        # Suppress ensure_ip_whitelisted during init so each test controls it directly.
        with patch.object(AzurePostgreSQLMCP, "ensure_ip_whitelisted"):
            with patch.dict("os.environ", self._AAD_ENV):
                self.azure_pg_mcp = AzurePostgreSQLMCP()
                self.azure_pg_mcp.init()

        # Use a real temp directory for cache file I/O so we don't need nested mock_opens.
        self._cache_dir = tempfile.mkdtemp()
        self._cache_path = os.path.join(self._cache_dir, "ip_cache")

    def tearDown(self):
        shutil.rmtree(self._cache_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_ip_response(self, ip: str):
        """Return a mock urlopen context manager that yields the given IP."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = ip.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def _write_cache(self, ip: str):
        with open(self._cache_path, "w") as f:
            f.write(ip)

    def _read_cache(self) -> str:
        with open(self._cache_path) as f:
            return f.read().strip()

    def _run(self, extra_env=None):
        """Call ensure_ip_whitelisted with the cache path redirected to the temp dir."""
        env = {"AZURE_AUTO_FIREWALL": "True", **self._AAD_ENV, **(extra_env or {})}
        with patch.dict("os.environ", env):
            with patch("os.path.expanduser", return_value=self._cache_path):
                self.azure_pg_mcp.ensure_ip_whitelisted()

    # ------------------------------------------------------------------
    # Tests: opt-in / prerequisite guards
    # ------------------------------------------------------------------

    def test_skipped_when_feature_disabled(self):
        """Should do nothing at all when AZURE_AUTO_FIREWALL is not 'True'."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            with patch.dict("os.environ", {"AZURE_AUTO_FIREWALL": ""}):
                self.azure_pg_mcp.ensure_ip_whitelisted()
        mock_urlopen.assert_not_called()

    def test_skipped_when_aad_not_enabled(self):
        """Should skip and warn when AAD is not in use (no management client available)."""
        self.azure_pg_mcp.aad_in_use = "False"
        with patch("urllib.request.urlopen") as mock_urlopen:
            with patch.dict("os.environ", {"AZURE_AUTO_FIREWALL": "True"}):
                self.azure_pg_mcp.ensure_ip_whitelisted()
        mock_urlopen.assert_not_called()
        self.mock_pg_client.firewall_rules.begin_create_or_update.assert_not_called()

    # ------------------------------------------------------------------
    # Tests: failure resilience
    # ------------------------------------------------------------------

    def test_graceful_skip_when_ip_fetch_fails(self):
        """Should not crash or call Azure when the public IP cannot be determined."""
        with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
            # Should not raise
            self._run()
        self.mock_pg_client.firewall_rules.begin_create_or_update.assert_not_called()

    def test_cache_not_written_when_azure_call_fails(self):
        """Should not update the cache when the Azure API call raises an error."""
        self._write_cache("1.2.3.4")
        self.mock_pg_client.firewall_rules.begin_create_or_update.side_effect = Exception(
            "Azure API error"
        )
        with patch("urllib.request.urlopen", return_value=self._make_ip_response("9.9.9.9")):
            self._run()

        # Cache should still hold the old IP — not overwritten with the new one.
        self.assertEqual(self._read_cache(), "1.2.3.4")

    # ------------------------------------------------------------------
    # Tests: core caching logic
    # ------------------------------------------------------------------

    def test_no_azure_call_when_ip_unchanged(self):
        """Should skip the Azure API when the cached IP matches the current public IP."""
        self._write_cache("1.2.3.4")
        with patch("urllib.request.urlopen", return_value=self._make_ip_response("1.2.3.4")):
            self._run()
        self.mock_pg_client.firewall_rules.begin_create_or_update.assert_not_called()

    def test_azure_called_when_ip_changes(self):
        """Should call the Azure API and update the cache when the IP has changed."""
        self._write_cache("1.2.3.4")
        with patch("urllib.request.urlopen", return_value=self._make_ip_response("5.6.7.8")):
            with patch("getpass.getuser", return_value="testuser"):
                self._run()

        self.mock_pg_client.firewall_rules.begin_create_or_update.assert_called_once()
        self.assertEqual(self._read_cache(), "5.6.7.8")

    def test_azure_called_on_first_run_no_cache(self):
        """Should call the Azure API when no cache file exists (first run)."""
        # No cache file written — self._cache_path does not exist yet.
        with patch("urllib.request.urlopen", return_value=self._make_ip_response("9.10.11.12")):
            with patch("getpass.getuser", return_value="testuser"):
                self._run()

        self.mock_pg_client.firewall_rules.begin_create_or_update.assert_called_once()
        self.assertEqual(self._read_cache(), "9.10.11.12")

    # ------------------------------------------------------------------
    # Tests: correct Azure API arguments
    # ------------------------------------------------------------------

    def test_firewall_rule_created_with_correct_ip(self):
        """The FirewallRule passed to Azure should use the detected public IP."""
        self._write_cache("1.2.3.4")
        with patch("urllib.request.urlopen", return_value=self._make_ip_response("5.6.7.8")):
            with patch("getpass.getuser", return_value="testuser"):
                self._run()

        _, kwargs = self.mock_pg_client.firewall_rules.begin_create_or_update.call_args
        positional = self.mock_pg_client.firewall_rules.begin_create_or_update.call_args[0]
        firewall_rule = positional[3]
        self.assertEqual(firewall_rule.start_ip_address, "5.6.7.8")
        self.assertEqual(firewall_rule.end_ip_address, "5.6.7.8")

    def test_firewall_rule_targets_correct_resource_group_and_server(self):
        """The Azure call should use the resource group and server name from config."""
        self._write_cache("1.2.3.4")
        with patch("urllib.request.urlopen", return_value=self._make_ip_response("5.6.7.8")):
            with patch("getpass.getuser", return_value="testuser"):
                self._run()

        positional = self.mock_pg_client.firewall_rules.begin_create_or_update.call_args[0]
        self.assertEqual(positional[0], "test-rg")       # resource_group_name
        self.assertEqual(positional[1], "test-host")     # server_name (stripped from PGHOST)

    # ------------------------------------------------------------------
    # Tests: rule naming
    # ------------------------------------------------------------------

    def test_default_rule_name_derived_from_os_username(self):
        """Default firewall rule name should be 'mcp-<whoami>'."""
        self._write_cache("1.2.3.4")
        with patch("urllib.request.urlopen", return_value=self._make_ip_response("5.6.7.8")):
            with patch("getpass.getuser", return_value="daniel"):
                self._run()

        positional = self.mock_pg_client.firewall_rules.begin_create_or_update.call_args[0]
        self.assertEqual(positional[2], "mcp-daniel")

    def test_rule_name_overridden_by_env_var(self):
        """AZURE_FIREWALL_RULE_NAME should override the default rule name."""
        self._write_cache("1.2.3.4")
        with patch("urllib.request.urlopen", return_value=self._make_ip_response("5.6.7.8")):
            with patch("getpass.getuser", return_value="daniel"):
                self._run(extra_env={"AZURE_FIREWALL_RULE_NAME": "my-custom-rule"})

        positional = self.mock_pg_client.firewall_rules.begin_create_or_update.call_args[0]
        self.assertEqual(positional[2], "my-custom-rule")


if __name__ == "__main__":
    unittest.main()
