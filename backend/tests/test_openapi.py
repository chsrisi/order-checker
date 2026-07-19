from src.main import app


def test_openapi_has_product_metadata():
    schema = app.openapi()
    assert schema["info"]["title"] == "Bakingholic Order Checker API"
    assert schema["info"]["version"] == "0.3.0-alpha"
    assert len(schema["tags"]) >= 8


def test_regression_routes_are_exposed():
    paths = app.openapi()["paths"]
    assert "/.well-known/jwks.json" in paths
    assert "/auth/admin" in paths
    assert "/pick-items/unassign" in paths
    assert "/admin/clear/outbound-items" in paths


def test_jwks_is_not_nested_under_auth():
    assert "/auth/.well-known/jwks.json" not in app.openapi()["paths"]


def test_every_http_operation_has_summary_and_description():
    for path, path_item in app.openapi()["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert operation.get("summary"), f"missing summary: {method.upper()} {path}"
            assert operation.get("description"), f"missing description: {method.upper()} {path}"


def test_protected_operations_advertise_bearer_security():
    schema = app.openapi()
    assert schema["paths"]["/outbound"]["post"]["security"]
    assert schema["paths"]["/admin/users"]["get"]["security"]
    assert "security" not in schema["paths"]["/.well-known/jwks.json"]["get"]


def test_user_schema_never_exposes_password_hash():
    operation = app.openapi()["paths"]["/admin/users"]["get"]
    schema_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]
    item_ref = schema_ref["items"]["$ref"]
    component = app.openapi()["components"]["schemas"][item_ref.rsplit("/", 1)[-1]]
    assert "password_hash" not in component["properties"]
