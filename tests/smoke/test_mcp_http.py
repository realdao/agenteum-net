from src.app import create_app


def test_create_app_mounts_mcp_endpoint():
    app = create_app()

    paths = {route.path for route in app.routes}

    assert "/mcp/full" in paths or any(path.startswith("/mcp/full") for path in paths)
