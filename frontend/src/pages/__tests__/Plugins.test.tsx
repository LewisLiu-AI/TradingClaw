import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Plugins } from "../Plugins";

const apiMock = vi.hoisted(() => ({
  listPlugins: vi.fn(),
  updateMCPServer: vi.fn(),
  updateSkillEnabled: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: apiMock,
}));

const pluginsPayload = {
  config_path: "~/.vibe-trading/agent.json",
  skills_state_path: "~/.vibe-trading/skills/disabled.json",
  mcp: [
    {
      name: "weather-mcp",
      enabled: true,
      transport: "stdio",
      command: "uvx",
      args: ["weather-mcp"],
      url: "",
      env_keys: ["API_TOKEN"],
      header_keys: [],
      has_auth: false,
      tool_timeout: 30,
      init_timeout: null,
      enabled_tools: ["*"],
      valid: true,
      error: null,
    },
    {
      name: "remote-mcp",
      enabled: false,
      transport: "streamableHttp",
      command: "",
      args: [],
      url: "https://example.com/mcp",
      env_keys: [],
      header_keys: ["Authorization"],
      has_auth: false,
      tool_timeout: 30,
      init_timeout: null,
      enabled_tools: ["*"],
      valid: true,
      error: null,
    },
  ],
  skills: [
    {
      name: "my-skill",
      description: "A user created skill",
      category: "strategy",
      source: "user",
      enabled: true,
      dir_path: "/tmp/user/my-skill",
    },
    {
      name: "bundled-skill",
      description: "A bundled skill",
      category: "analysis",
      source: "bundled",
      enabled: false,
      dir_path: "/tmp/bundled/bundled-skill",
    },
  ],
};

describe("Plugins page", () => {
  beforeEach(() => {
    apiMock.listPlugins.mockReset();
    apiMock.updateMCPServer.mockReset();
    apiMock.updateSkillEnabled.mockReset();
    apiMock.listPlugins.mockResolvedValue(pluginsPayload);
  });

  it("renders MCP servers with toggles and switches to skills tab", async () => {
    render(<Plugins />);

    expect(await screen.findByText("weather-mcp")).toBeInTheDocument();
    expect(screen.getByText("remote-mcp")).toBeInTheDocument();

    const mcpTab = screen.getByRole("tab", { name: /MCP/ });
    expect(mcpTab).toHaveAttribute("aria-selected", "true");

    fireEvent.click(screen.getByRole("tab", { name: /Skills/ }));
    expect(await screen.findByText("my-skill")).toBeInTheDocument();
    expect(screen.getByText("bundled-skill")).toBeInTheDocument();
    expect(screen.queryByText("weather-mcp")).not.toBeInTheDocument();
  });

  it("toggles an MCP server through the API", async () => {
    apiMock.updateMCPServer.mockResolvedValue({ ...pluginsPayload.mcp[1], enabled: true });
    render(<Plugins />);
    await screen.findByText("remote-mcp");

    fireEvent.click(screen.getByRole("switch", { name: /remote-mcp/ }));

    await waitFor(() => {
      expect(apiMock.updateMCPServer).toHaveBeenCalledWith("remote-mcp", { enabled: true });
    });
  });

  it("toggles a skill through the API", async () => {
    apiMock.updateSkillEnabled.mockResolvedValue({ name: "my-skill", enabled: false, state_path: "x" });
    render(<Plugins />);
    await screen.findByText("weather-mcp");

    fireEvent.click(screen.getByRole("tab", { name: /Skills/ }));
    await screen.findByText("my-skill");

    fireEvent.click(screen.getByRole("switch", { name: /my-skill/ }));

    await waitFor(() => {
      expect(apiMock.updateSkillEnabled).toHaveBeenCalledWith("my-skill", false);
    });
  });

  it("filters entries by search text", async () => {
    render(<Plugins />);
    await screen.findByText("weather-mcp");

    fireEvent.change(screen.getByPlaceholderText("Search MCP servers"), {
      target: { value: "remote" },
    });

    expect(screen.queryByText("weather-mcp")).not.toBeInTheDocument();
    expect(screen.getByText("remote-mcp")).toBeInTheDocument();
  });

  it("opens the MCP settings dialog and saves edits", async () => {
    apiMock.updateMCPServer.mockResolvedValue({ ...pluginsPayload.mcp[0], command: "npx" });
    render(<Plugins />);
    await screen.findByText("weather-mcp");

    fireEvent.click(screen.getByRole("button", { name: /Settings weather-mcp/ }));
    expect(await screen.findByText("MCP server settings")).toBeInTheDocument();

    fireEvent.change(screen.getByDisplayValue("uvx"), { target: { value: "npx" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(apiMock.updateMCPServer).toHaveBeenCalledWith(
        "weather-mcp",
        expect.objectContaining({ command: "npx" })
      );
    });
  });

  it("shows the empty state when no MCP servers are configured", async () => {
    apiMock.listPlugins.mockResolvedValue({ ...pluginsPayload, mcp: [] });
    render(<Plugins />);

    expect(await screen.findByText("No MCP servers configured")).toBeInTheDocument();
  });
});
