import pytest

from hermes_cli.managed_policy import managed_mutation_denial


@pytest.mark.parametrize("path", [
    "/api/skills/install", "/api/tools/config", "/api/models/set",
    "/api/model/set", "/api/providers/set", "/api/profiles/create",
    "/api/profiles/delete", "/api/mcp", "/api/config", "/api/plugins/install",
])
def test_managed_desktop_denies_configuration_mutations(path):
    assert managed_mutation_denial("POST", path, managed=True) is not None


def test_managed_desktop_preserves_chat_history_streaming_and_mcp_execution():
    for method, path in [("POST", "/api/chat"), ("GET", "/api/sessions"),
                         ("GET", "/api/chat/stream"), ("POST", "/api/mcp/call")]:
        assert managed_mutation_denial(method, path, managed=True) is None


def test_policy_is_inactive_outside_managed_desktop():
    assert managed_mutation_denial("POST", "/api/config", managed=False) is None


def test_only_mutating_verbs_are_blocked():
    assert managed_mutation_denial("GET", "/api/models", managed=True) is None
    assert managed_mutation_denial("DELETE", "/api/plugins/foo", managed=True) is not None
