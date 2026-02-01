# odoo-fast-mcp

## Creating a virtual environment with `uv` 🔧

### Quick steps

1. Create the virtual environment in the project root (seed `pip`, `setuptools`, `wheel`):

    ```bash
    uv venv .venv --seed
    # or to select a Python version:
    uv venv -p python3.11 .venv
    ```

2. Activate the venv:

    ```bash
    source .venv/bin/activate
    ```

3. Install project dependencies into the active environment:

    ```bash
    uv sync --active
    ```

## Installing the App 📦

Once the virtual environment is set up and activated:

1. **Install the app and its dependencies:**

    ```bash
    uv sync
    ```

    This installs the `odoo-fast-mcp` package in editable mode along with runtime dependencies (`OdooRPC`, `fastmcp`).

2. **For development (includes linting and type checking tools):**

    ```bash
    uv sync --extra dev
    ```

    This adds `ruff` (linter/formatter) and `ty` (type checker) to the environment.

> **Note:** The app's entry point is `odoo-fast-mcp`, configured in `pyproject.toml`. Run it with `odoo-fast-mcp --config config.json` after setup.

---

If you want a different workflow (e.g., using system site-packages or custom prompt), run `uv help venv` for more options.
