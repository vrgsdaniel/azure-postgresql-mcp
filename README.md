# Azure Database for PostgreSQL MCP Server (Preview)

> **This is a fork of [Azure-Samples/azure-postgresql-mcp](https://github.com/Azure-Samples/azure-postgresql-mcp) with the following improvements:**
>
> - **Automatic IP firewall whitelisting** (`AZURE_AUTO_FIREWALL`): on startup the server detects your public IP and adds it to the Azure PostgreSQL firewall automatically, with a local cache to avoid redundant API calls on repeat starts.
> - **Improved logging**: the MCP process now emits structured `DEBUG`/`INFO`/`WARNING`/`ERROR` logs to stdout, visible in Claude Desktop's MCP log files (`~/Library/Logs/Claude/mcp-server-*.log`). The original used the Azure SDK's logger namespace which was set to `ERROR`, silently swallowing all diagnostic output.
> - **Robust AAD flag handling**: the `AZURE_USE_AAD` env var now accepts `"true"`, `"True"`, `"1"`, or `"yes"` (the original only matched the exact string `"True"`).

---

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/introduction) Server that lets your AI models talk to data hosted in Azure Database for PostgreSQL according to the MCP standard!

By utilizing this server, you can effortlessly connect any AI application that supports MCP to your PostgreSQL flexible server (using either PostgreSQL password-based authentication or Microsoft Entra authentication methods), enabling you to provide your business data as meaningful context in a standardized and secure manner.

This server exposes the following tools, which can be invoked by MCP Clients in your AI agents, AI applications or tools like Claude Desktop and Visual Studio Code:

- **List all databases** in your Azure Database for PostgreSQL flexible server instance.
- **List all tables** in a database along with their schema information.
- **Execute read queries** to retrieve data from your database.
- **Insert or update records** in your database.
- **Create a new table or drop an existing table** in your database.
- **List Azure Database for PostgreSQL flexible server configuration**, including its PostgreSQL version, and compute and storage configurations. *
- Retrieve specific **server parameter values.** *

_*Available when using Microsoft Entra authentication method_

## Getting Started

### Prerequisites

- [Python](https://www.python.org/downloads/) 3.10 or above
- An Azure Database for PostgreSQL flexible server instance with a database containing your business data. For instructions on creating a flexible instance, setting up a database, and connecting to it, please refer to this [quickstart guide](https://learn.microsoft.com/azure/postgresql/flexible-server/quickstart-create-server).
- An MCP Client application or tool such as [Claude Desktop](https://claude.ai/download) or [Visual Studio Code](https://code.visualstudio.com/download).

### Installation

1. Clone this repository:

    ```
    git clone https://github.com/vrgsdaniel/azure-postgresql-mcp.git
    cd azure-postgresql-mcp
    ```

    Alternatively, you can download only the `azure_postgresql_mcp.py` file to your working folder.

2. Create a virtual environment:

    Windows cmd.exe:
    ```
    python -m venv azure-postgresql-mcp-venv
    .\azure-postgresql-mcp-venv\Scripts\activate.bat
    ```
    Windows Powershell:
    ```
    python -m venv azure-postgresql-mcp-venv
    .\azure-postgresql-mcp-venv\Scripts\Activate.ps1
    ```
    Linux and MacOS:
    ```
    python -m venv azure-postgresql-mcp-venv
    source ./azure-postgresql-mcp-venv/bin/activate
    ```

3. Install the dependencies:

    ```
    pip install mcp[cli]
    pip install psycopg[binary]
    pip install azure-mgmt-postgresqlflexibleservers
    pip install azure-identity
    ```

### Use the MCP Server with Claude Desktop

1. In the Claude Desktop app, navigate to the "Settings" pane, select the "Developer" tab and click on "Edit Config".
2. Open the `claude_desktop_config.json` file and add the following configuration to the "mcpServers" section:

    ```json
    {
        "mcpServers": {
            "azure-postgresql-mcp": {
                "command": "<path to the virtual environment>/azure-postgresql-mcp-venv/bin/python",
                "args": [
                    "<path to azure_postgresql_mcp.py file>/azure_postgresql_mcp.py"
                ],
                "env": {
                    "PGHOST": "<Fully qualified name of your Azure Database for PostgreSQL instance>",
                    "PGUSER": "<Your Azure Database for PostgreSQL username>",
                    "PGPASSWORD": "<Your password>",
                    "PGDATABASE": "<Your database name>"
                }
            }
        }
    }
    ```
    **Note**: Here, we use password-based authentication for testing purposes only. We recommend using Microsoft Entra authentication. Please refer to [these instructions](#using-microsoft-entra-authentication-method) for guidance.

3. Restart the Claude Desktop app.
4. Upon restarting, you should see a hammer icon at the bottom of the input box. Selecting this icon will display the tools provided by the MCP Server.

### Use the MCP Server with Visual Studio Code

1. In Visual Studio Code, navigate to "File", select "Preferences" and then choose "Settings".
2. Search for "MCP" and select "Edit in settings.json".
3. Add the following configuration to the "mcp" section of the `settings.json` file:

    ```json
    {
        "mcp": {
            "inputs": [],
            "servers": {
                "azure-postgresql-mcp": {
                    "command": "<path to the virtual environment>/azure-postgresql-mcp-venv/bin/python",
                    "args": [
                        "<path to azure_postgresql_mcp.py file>/azure_postgresql_mcp.py"
                    ],
                    "env": {
                        "PGHOST": "<Fully qualified name of your Azure Database for PostgreSQL instance>",
                        "PGUSER": "<Your Azure Database for PostgreSQL username>",
                        "PGPASSWORD": "<Your password>",
                        "PGDATABASE": "<Your database name>"
                    }
                }
            }
        }
    }
    ```
4. Select the "Copilot" status icon in the upper-right corner to open the GitHub Copilot Chat window.
5. Choose "Agent mode" from the dropdown at the bottom of the chat input box.
6. Click on "Select Tools" (hammer icon) to view the tools exposed by the MCP Server.

## Using Microsoft Entra authentication method

To use Microsoft Entra authentication (recommended), update the MCP Server configuration with the following:

```json
"azure-postgresql-mcp": {
    "command": "<path to the virtual environment>/azure-postgresql-mcp-venv/bin/python",
    "args": [
        "<path to azure_postgresql_mcp.py file>/azure_postgresql_mcp.py"
    ],
    "env": {
        "PGHOST": "<Fully qualified name of your Azure Database for PostgreSQL instance>",
        "PGUSER": "<Your Microsoft Entra ID username or managed identity name>",
        "AZURE_USE_AAD": "True",
        "AZURE_SUBSCRIPTION_ID": "<Your Azure subscription ID>",
        "AZURE_RESOURCE_GROUP": "<Your Resource Group that contains the Azure Database for PostgreSQL instance>"
    }
}
```

### Automatic firewall IP whitelisting

If your PostgreSQL server uses IP allowlisting, you can have the MCP server automatically add your current public IP to the firewall on startup — with no slowdown on repeat starts.

Add this env var to the configuration above:

```json
"AZURE_AUTO_FIREWALL": "True"
```

**How it works:** On startup the server fetches your public IP from `api.ipify.org` and compares it against a local cache (`~/.azure_pg_mcp_ip_cache`). The Azure firewall rule is only updated when your IP has actually changed. This means:

- **First run / IP changed:** ~2–5 s to create or update the firewall rule, then connects normally.
- **Subsequent runs with same IP:** No Azure API call, no delay.

The firewall rule name defaults to `mcp-<your-OS-username>` (e.g. `mcp-daniel`), derived automatically — no extra config needed. Each developer on the team gets their own named rule with no risk of overwriting a colleague's entry. You can override the name with `AZURE_FIREWALL_RULE_NAME` if needed.

**Required Azure permissions:** the identity used must have the `PostgreSQL Flexible Server Firewall Rule Contributor` role (or equivalent) on the resource group containing the PostgreSQL server.

### Viewing MCP logs (Claude Desktop)

All startup and connection events are logged to stdout, which Claude Desktop captures per-server:

```bash
tail -f ~/Library/Logs/Claude/mcp-server-azure-postgresql-mcp.log
```

On a successful start with `AZURE_AUTO_FIREWALL=True` you should see output like:

```
[INFO] azure_postgresql_mcp: Initialising MCP for host: myserver.postgres.database.azure.com
[INFO] azure_postgresql_mcp: AZURE_AUTO_FIREWALL enabled — checking current public IP...
[INFO] azure_postgresql_mcp: Current public IP: 1.2.3.4
[INFO] azure_postgresql_mcp: Firewall rule 'mcp-daniel' updated successfully to allow 1.2.3.4.
[INFO] azure_postgresql_mcp: Password/token obtained successfully.
```

## Contributing

Contributions are welcome! For more details, see the [CONTRIBUTING.md](CONTRIBUTING.md) file.

## License

This project is licensed under the MIT License. For more details, see the [LICENSE](LICENSE.md) file.
