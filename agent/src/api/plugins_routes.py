"""Plugins (MCP servers & skills) HTTP routes for the Web UI 插件 page.

Mounted by ``agent/api_server.py`` via ``register_plugins_routes(app, ...)``.

Read model: MCP servers come from the operator agent config
(``~/.vibe-trading/agent.json`` ``mcpServers``); skills are scanned from the
bundled ``agent/src/skills`` directory and the user directory
(``~/.vibe-trading/skills/user``). Secret values (``env`` / ``headers``) are
never returned — only their key names.
"""

from __future__ import annotations

import json
import sys as _sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from src.agent.skills import (
    _load_skill_dir,
    default_bundled_skills_dir,
    load_disabled_skill_names,
    save_disabled_skill_names,
)
from src.config.paths import get_config_path
from src.config.schema import MCPServerConfig, MCPServerConfigOverride

# Agent root (agent/) — resolved from this file's location (agent/src/api/).
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Pydantic models (defined locally -- NO shared modules, per maintainer rule)
# ---------------------------------------------------------------------------


class MCPServerInfo(BaseModel):
    """One configured MCP server as shown in the plugins UI."""

    name: str
    enabled: bool = True
    transport: str = "stdio"
    command: str = ""
    args: List[str] = Field(default_factory=list)
    url: str = ""
    env_keys: List[str] = Field(default_factory=list)
    header_keys: List[str] = Field(default_factory=list)
    has_auth: bool = False
    tool_timeout: float = 30.0
    init_timeout: Optional[float] = None
    enabled_tools: List[str] = Field(default_factory=lambda: ["*"])
    valid: bool = True
    error: Optional[str] = None


class SkillInfo(BaseModel):
    """One installed skill as shown in the plugins UI."""

    name: str
    description: str = ""
    category: str = "other"
    source: str  # "bundled" | "user"
    enabled: bool = True
    dir_path: str = ""


class PluginsResponse(BaseModel):
    """Payload for the plugins page: MCP servers + skills with toggle state."""

    config_path: str
    skills_state_path: str
    mcp: List[MCPServerInfo]
    skills: List[SkillInfo]


class UpdateMcpServerRequest(BaseModel):
    """Partial MCP server update. Only provided fields are changed."""

    enabled: Optional[bool] = None
    type: Optional[Literal["stdio", "sse", "streamableHttp"]] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    tool_timeout: Optional[float] = Field(default=None, ge=0.1)
    init_timeout: Optional[float] = Field(default=None, ge=0.1)
    enabled_tools: Optional[List[str]] = None


class UpdateSkillEnabledRequest(BaseModel):
    """Toggle one skill on/off."""

    enabled: bool


class SkillEnabledResponse(BaseModel):
    """Result of a skill toggle."""

    name: str
    enabled: bool
    state_path: str


# ---------------------------------------------------------------------------
# Route-module-local helpers
# ---------------------------------------------------------------------------


def _read_config_dict(path: Path) -> Dict[str, Any]:
    """Read the operator agent config into a plain dict (JSON, or YAML when available)."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover — optional dependency
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="YAML agent config requires PyYAML, which is not installed",
            ) from exc
        data = yaml.safe_load(text) or {}
    else:
        try:
            data = json.loads(text) if text.strip() else {}
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Agent config at {path} is not valid JSON: {exc}",
            ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent config at {path} must decode to a JSON/YAML object",
        )
    return data


def _write_config_dict(path: Path, data: Dict[str, Any]) -> None:
    """Write the operator agent config back to disk as JSON."""
    if path.suffix.lower() in {".yaml", ".yml"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Agent config at {path} is YAML; the plugins UI edits JSON configs. "
                "Rename the file to agent.json or edit it by hand."
            ),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mcp_servers_mapping(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return the raw ``mcpServers`` mapping, tolerating either key spelling."""
    for key in ("mcpServers", "mcp_servers"):
        servers = config.get(key)
        if isinstance(servers, dict):
            return servers
    return {}


def _mcp_servers_key(config: Dict[str, Any]) -> Optional[str]:
    """Return which spelling of the MCP mapping key the config file uses."""
    for key in ("mcpServers", "mcp_servers"):
        if isinstance(config.get(key), dict):
            return key
    return None


def _build_mcp_server_info(name: str, raw: Any) -> MCPServerInfo:
    """Build the public info payload for one raw MCP server entry.

    Invalid entries still appear (with ``valid=False`` and the validation
    error) so operators can see and fix them from the UI instead of the
    endpoint failing the whole listing.
    """
    if not isinstance(raw, dict):
        return MCPServerInfo(
            name=name,
            valid=False,
            error="Entry must be a JSON object",
        )
    env = raw.get("env") if isinstance(raw.get("env"), dict) else {}
    headers = raw.get("headers") if isinstance(raw.get("headers"), dict) else {}
    base = dict(raw)
    base.pop("env", None)
    base.pop("headers", None)
    base.pop("auth", None)
    try:
        server = MCPServerConfig.model_validate(base)
    except ValidationError as exc:
        return MCPServerInfo(
            name=name,
            enabled=bool(raw.get("enabled", True)),
            command=str(raw.get("command", "") or ""),
            args=[str(a) for a in raw.get("args", []) or []] if isinstance(raw.get("args"), list) else [],
            url=str(raw.get("url", "") or ""),
            env_keys=sorted(str(k) for k in env),
            header_keys=sorted(str(k) for k in headers),
            valid=False,
            error=str(exc.errors()[-1].get("msg", "invalid MCP server config")),
        )
    transport = "stdio"
    try:
        transport = server.resolved_transport()
    except ValueError:
        transport = str(server.type or "stdio")
    return MCPServerInfo(
        name=name,
        enabled=server.enabled,
        transport=transport,
        command=server.command,
        args=list(server.args),
        url=server.url,
        env_keys=sorted(str(k) for k in env),
        header_keys=sorted(str(k) for k in headers),
        has_auth=raw.get("auth") is not None,
        tool_timeout=server.tool_timeout,
        init_timeout=server.init_timeout,
        enabled_tools=list(server.enabled_tools),
    )


def _list_skills(
    bundled_dir: Path,
    user_dir: Path,
    state_path: Path,
) -> List[SkillInfo]:
    """Scan bundled + user skill directories and annotate toggle state.

    A user skill with the same name as a bundled skill overrides it (mirrors
    ``SkillsLoader``), so each name appears once with the winning source.
    """
    disabled = load_disabled_skill_names(state_path)
    found: Dict[str, SkillInfo] = {}
    for source, directory in (("user", user_dir), ("bundled", bundled_dir)):
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if not (path.is_dir() and (path / "SKILL.md").exists()):
                continue
            skill = _load_skill_dir(path)
            if skill is None or skill.name in found:
                continue
            found[skill.name] = SkillInfo(
                name=skill.name,
                description=skill.description,
                category=skill.category,
                source=source,
                enabled=skill.name not in disabled,
                dir_path=str(path),
            )
    return sorted(found.values(), key=lambda item: (item.category, item.name))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_plugins_routes(
    app: FastAPI,
    require_local_or_auth: AuthDep | None = None,
    require_settings_write_auth: AuthDep | None = None,
) -> None:
    """Mount the plugins routes onto ``app``."""
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")

    if host is None:
        raise RuntimeError(
            "register_plugins_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_local_or_auth is None:
        require_local_or_auth = host.require_local_or_auth
    if require_settings_write_auth is None:
        require_settings_write_auth = host.require_settings_write_auth

    @app.get(
        "/plugins",
        response_model=PluginsResponse,
        dependencies=[Depends(require_local_or_auth)],
    )
    async def list_plugins() -> PluginsResponse:
        """Return configured MCP servers and installed skills for the plugins page."""
        from src.agent.skills import DISABLED_SKILLS_PATH, USER_SKILLS_DIR

        config_path = get_config_path()
        config = _read_config_dict(config_path)
        servers = [
            _build_mcp_server_info(name, raw)
            for name, raw in sorted(_mcp_servers_mapping(config).items())
        ]
        skills = _list_skills(
            bundled_dir=default_bundled_skills_dir(),
            user_dir=USER_SKILLS_DIR,
            state_path=DISABLED_SKILLS_PATH,
        )
        return PluginsResponse(
            config_path=str(config_path),
            skills_state_path=str(DISABLED_SKILLS_PATH),
            mcp=servers,
            skills=skills,
        )

    @app.put(
        "/plugins/mcp/{name}",
        response_model=MCPServerInfo,
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def update_mcp_server(name: str, payload: UpdateMcpServerRequest) -> MCPServerInfo:
        """Partially update one MCP server entry in the operator agent config."""
        config_path = get_config_path()
        config = _read_config_dict(config_path)
        mapping_key = _mcp_servers_key(config)
        servers = _mcp_servers_mapping(config)
        if name not in servers:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MCP server '{name}' is not configured in {config_path}",
            )

        raw = servers[name] if isinstance(servers[name], dict) else {}
        updates = payload.model_dump(exclude_unset=True, exclude_none=True)
        if "args" in updates and not isinstance(updates["args"], list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="args must be a list of strings"
            )
        merged = {**raw, **updates}

        # Validate the merged entry (transport-specific conflicts, timeouts, ...)
        # before touching the file so a bad edit never corrupts the config.
        try:
            MCPServerConfig.model_validate(merged)
        except ValidationError as exc:
            detail = "; ".join(
                f"{'.'.join(str(part) for part in err.get('loc', []))}: {err.get('msg', '')}"
                for err in exc.errors()
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Update would produce an invalid MCP server config: {detail}",
            ) from exc

        servers[name] = merged
        if mapping_key is None:
            mapping_key = "mcpServers"
            config[mapping_key] = servers
        _write_config_dict(config_path, config)
        return _build_mcp_server_info(name, merged)

    @app.put(
        "/plugins/skills/{name}",
        response_model=SkillEnabledResponse,
        dependencies=[Depends(require_settings_write_auth)],
    )
    async def update_skill_enabled(name: str, payload: UpdateSkillEnabledRequest) -> SkillEnabledResponse:
        """Enable or disable one installed skill."""
        from src.agent.skills import DISABLED_SKILLS_PATH, USER_SKILLS_DIR

        bundled_dir = default_bundled_skills_dir()
        installed_names = {
            skill.name
            for skill in _list_skills(bundled_dir=bundled_dir, user_dir=USER_SKILLS_DIR, state_path=DISABLED_SKILLS_PATH)
        }
        if name not in installed_names:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill '{name}' is not installed",
            )

        disabled = load_disabled_skill_names(DISABLED_SKILLS_PATH)
        if payload.enabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        save_disabled_skill_names(disabled, DISABLED_SKILLS_PATH)
        return SkillEnabledResponse(
            name=name,
            enabled=payload.enabled,
            state_path=str(DISABLED_SKILLS_PATH),
        )
