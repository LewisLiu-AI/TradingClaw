"""Tests for the plugins (MCP servers & skills) API and toggle plumbing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.config.schema import MCPServerConfig


@pytest.fixture
def runtime_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Hermetic stand-ins for the agent config and skills directories."""
    config_path = tmp_path / "agent.json"
    bundled_skills = tmp_path / "bundled-skills"
    user_skills = tmp_path / "user-skills"
    disabled_state = tmp_path / "skills-state" / "disabled.json"

    import src.agent.skills as skills_module
    import src.api.plugins_routes as plugins_module

    monkeypatch.setattr(plugins_module, "get_config_path", lambda: config_path)
    monkeypatch.setattr(plugins_module, "default_bundled_skills_dir", lambda: bundled_skills)
    monkeypatch.setattr(skills_module, "USER_SKILLS_DIR", user_skills)
    monkeypatch.setattr(skills_module, "DISABLED_SKILLS_PATH", disabled_state)

    return {
        "config_path": config_path,
        "bundled_skills": bundled_skills,
        "user_skills": user_skills,
        "disabled_state": disabled_state,
    }


def _make_skill(directory: Path, dirname: str, name: str, description: str = "", category: str = "other") -> None:
    skill_dir = directory / dirname
    skill_dir.mkdir(parents=True)
    frontmatter = [f"name: {name}"]
    if description:
        frontmatter.append(f"description: {description}")
    if category != "other":
        frontmatter.append(f"category: {category}")
    (skill_dir / "SKILL.md").write_text(
        "---\n" + "\n".join(frontmatter) + "\n---\nBody of " + name + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


# ---------------------------------------------------------------------------
# GET /plugins
# ---------------------------------------------------------------------------


def test_list_plugins_returns_mcp_servers_and_skills(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    runtime_dirs["config_path"].write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local-tools": {
                        "command": "uvx",
                        "args": ["some-mcp-server"],
                        "env": {"API_TOKEN": "super-secret"},
                        "enabled": False,
                    },
                    "remote-tools": {
                        "type": "streamableHttp",
                        "url": "https://example.com/mcp",
                        "headers": {"Authorization": "Bearer super-secret"},
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    _make_skill(runtime_dirs["bundled_skills"], "alpha-skill", "alpha-skill", "Bundled alpha", "strategy")
    _make_skill(runtime_dirs["user_skills"], "my-skill", "my-skill", "User skill")

    response = client.get("/plugins")

    assert response.status_code == 200
    body = response.json()
    by_name = {server["name"]: server for server in body["mcp"]}
    assert by_name["local-tools"]["enabled"] is False
    assert by_name["local-tools"]["transport"] == "stdio"
    assert by_name["local-tools"]["command"] == "uvx"
    assert by_name["local-tools"]["env_keys"] == ["API_TOKEN"]
    assert by_name["remote-tools"]["enabled"] is True
    assert by_name["remote-tools"]["transport"] == "streamableHttp"
    assert by_name["remote-tools"]["has_auth"] is False

    # Secret values must never be returned — only key names.
    assert "super-secret" not in response.text

    skills = {skill["name"]: skill for skill in body["skills"]}
    assert skills["alpha-skill"]["source"] == "bundled"
    assert skills["alpha-skill"]["category"] == "strategy"
    assert skills["my-skill"]["source"] == "user"
    assert all(skill["enabled"] for skill in skills.values())
    assert body["config_path"].endswith("agent.json")


def test_list_plugins_dedupes_user_over_bundled_and_reports_disabled(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    _make_skill(runtime_dirs["bundled_skills"], "shared", "shared", "Bundled version")
    _make_skill(runtime_dirs["user_skills"], "shared", "shared", "User override")
    _make_skill(runtime_dirs["bundled_skills"], "off-skill", "off-skill", "Disabled skill")
    runtime_dirs["disabled_state"].parent.mkdir(parents=True, exist_ok=True)
    runtime_dirs["disabled_state"].write_text(
        json.dumps({"disabled": ["off-skill"]}), encoding="utf-8"
    )

    body = client.get("/plugins").json()

    shared = [skill for skill in body["skills"] if skill["name"] == "shared"]
    assert len(shared) == 1
    assert shared[0]["source"] == "user"
    assert shared[0]["description"] == "User override"
    off = [skill for skill in body["skills"] if skill["name"] == "off-skill"]
    assert len(off) == 1
    assert off[0]["enabled"] is False


def test_list_plugins_reports_invalid_mcp_entry_without_failing(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    runtime_dirs["config_path"].write_text(
        json.dumps(
            {
                "mcpServers": {
                    "broken": {"type": "streamableHttp", "command": "nope"},
                    "fine": {"command": "uvx", "args": ["mcp-server"]},
                }
            }
        ),
        encoding="utf-8",
    )

    body = client.get("/plugins").json()

    by_name = {server["name"]: server for server in body["mcp"]}
    assert by_name["broken"]["valid"] is False
    assert by_name["broken"]["error"]
    assert by_name["fine"]["valid"] is True


# ---------------------------------------------------------------------------
# PUT /plugins/mcp/{name}
# ---------------------------------------------------------------------------


def test_update_mcp_server_toggle_persists_enabled_false(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    runtime_dirs["config_path"].write_text(
        json.dumps({"mcpServers": {"svc": {"command": "uvx", "args": ["mcp-server"]}}}),
        encoding="utf-8",
    )

    response = client.put("/plugins/mcp/svc", json={"enabled": False})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    on_disk = json.loads(runtime_dirs["config_path"].read_text(encoding="utf-8"))
    assert on_disk["mcpServers"]["svc"]["enabled"] is False
    # The previously configured keys survive the round-trip.
    assert on_disk["mcpServers"]["svc"]["command"] == "uvx"


def test_update_mcp_server_reenables_and_preserves_env(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    runtime_dirs["config_path"].write_text(
        json.dumps(
            {
                "mcpServers": {
                    "svc": {
                        "command": "uvx",
                        "env": {"API_TOKEN": "keep-me"},
                        "enabled": False,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    response = client.put("/plugins/mcp/svc", json={"enabled": True})

    assert response.status_code == 200
    on_disk = json.loads(runtime_dirs["config_path"].read_text(encoding="utf-8"))
    assert on_disk["mcpServers"]["svc"]["enabled"] is True
    assert on_disk["mcpServers"]["svc"]["env"] == {"API_TOKEN": "keep-me"}


def test_update_mcp_server_edits_fields_and_validates(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    runtime_dirs["config_path"].write_text(
        json.dumps({"mcpServers": {"svc": {"command": "uvx", "args": ["mcp-server"]}}}),
        encoding="utf-8",
    )

    response = client.put(
        "/plugins/mcp/svc",
        json={"command": "npx", "args": ["-y", "other-mcp"], "tool_timeout": 12.5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["command"] == "npx"
    assert body["args"] == ["-y", "other-mcp"]
    assert body["tool_timeout"] == 12.5
    on_disk = json.loads(runtime_dirs["config_path"].read_text(encoding="utf-8"))
    assert on_disk["mcpServers"]["svc"]["tool_timeout"] == 12.5


def test_update_mcp_server_rejects_invalid_transport_combo(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    original = json.dumps({"mcpServers": {"svc": {"command": "uvx", "args": ["mcp-server"]}}})
    runtime_dirs["config_path"].write_text(original, encoding="utf-8")

    # stdio servers must not carry a url (transport validation).
    response = client.put("/plugins/mcp/svc", json={"url": "https://example.com/mcp"})

    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()
    assert runtime_dirs["config_path"].read_text(encoding="utf-8") == original


def test_update_mcp_server_unknown_name_returns_404(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    runtime_dirs["config_path"].write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")

    response = client.put("/plugins/mcp/ghost", json={"enabled": False})

    assert response.status_code == 404


def test_update_mcp_server_without_config_file_returns_404(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    response = client.put("/plugins/mcp/ghost", json={"enabled": False})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /plugins/skills/{name}
# ---------------------------------------------------------------------------


def test_update_skill_disable_then_enable_round_trip(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    _make_skill(runtime_dirs["bundled_skills"], "my-skill", "my-skill", "A skill")

    disable = client.put("/plugins/skills/my-skill", json={"enabled": False})
    assert disable.status_code == 200
    assert disable.json()["enabled"] is False
    assert json.loads(runtime_dirs["disabled_state"].read_text(encoding="utf-8")) == {
        "disabled": ["my-skill"]
    }

    listing = client.get("/plugins").json()
    skill = next(skill for skill in listing["skills"] if skill["name"] == "my-skill")
    assert skill["enabled"] is False

    enable = client.put("/plugins/skills/my-skill", json={"enabled": True})
    assert enable.status_code == 200
    assert enable.json()["enabled"] is True
    assert json.loads(runtime_dirs["disabled_state"].read_text(encoding="utf-8")) == {
        "disabled": []
    }


def test_update_skill_unknown_name_returns_404(
    client: TestClient, runtime_dirs: dict[str, Path]
) -> None:
    response = client.put("/plugins/skills/ghost", json={"enabled": False})

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Toggle plumbing outside the HTTP layer
# ---------------------------------------------------------------------------


def test_skills_loader_excludes_disabled_skills(runtime_dirs: dict[str, Path]) -> None:
    from src.agent.skills import SkillsLoader, load_disabled_skill_names, save_disabled_skill_names

    _make_skill(runtime_dirs["bundled_skills"], "kept", "kept", "Kept")
    _make_skill(runtime_dirs["bundled_skills"], "skipped", "skipped", "Skipped")

    loader = SkillsLoader(
        skills_dir=runtime_dirs["bundled_skills"],
        user_skills_dir=runtime_dirs["user_skills"],
        disabled_state_path=runtime_dirs["disabled_state"],
    )
    assert sorted(skill.name for skill in loader.skills) == ["kept", "skipped"]

    save_disabled_skill_names({"skipped"}, runtime_dirs["disabled_state"])
    assert load_disabled_skill_names(runtime_dirs["disabled_state"]) == {"skipped"}

    loader = SkillsLoader(
        skills_dir=runtime_dirs["bundled_skills"],
        user_skills_dir=runtime_dirs["user_skills"],
        disabled_state_path=runtime_dirs["disabled_state"],
    )
    assert [skill.name for skill in loader.skills] == ["kept"]
    assert loader.get_content("skipped").startswith("Error:")


def test_mcp_server_config_accepts_enabled_field() -> None:
    server = MCPServerConfig.model_validate({"command": "uvx", "enabled": False})
    assert server.enabled is False
    assert MCPServerConfig.model_validate({"command": "uvx"}).enabled is True


def test_build_registry_skips_disabled_mcp_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.schema import AgentConfig
    from src.tools import build_registry

    warnings: list[str] = []

    def _fail(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("build_mcp_tool_wrappers must not run for a disabled server")

    import src.tools.mcp as mcp_module

    monkeypatch.setattr(mcp_module, "build_mcp_tool_wrappers", _fail)
    config = AgentConfig.model_validate(
        {"mcpServers": {"off": {"command": "uvx", "args": ["mcp-server"], "enabled": False}}}
    )

    registry = build_registry(
        agent_config=config,
        include_shell_tools=False,
        warn_callback=warnings.append,
    )

    assert registry.get("mcp_off_anything") is None
    assert any("disabled" in message for message in warnings)
