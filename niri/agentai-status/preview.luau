--!nonstrict
-- Read-only hover preview shown under the bar while the pointer is over the
-- widget: usage limits, agents with state and session title, and unavailable
-- machines in a dense list.

local common = require("./common.luau")

local WIDTH = 640
local MAX_ROWS = 20
local NAME_SIZE = 12
local DETAIL_SIZE = 11

local snapshot = noctalia.state.get("snapshot")

local function line(name, detail, color, icon)
  local children = {}
  if icon then
    table.insert(children, ui.image({ path = icon, width = 14, height = 14, fit = "contain" }))
  end
  table.insert(children, ui.label({ text = name, color = color, fontWeight = "semibold", fontSize = NAME_SIZE, maxLines = 1, flexGrow = 1 }))
  table.insert(children, ui.label({ text = detail, color = "on_surface_variant", fontSize = DETAIL_SIZE, maxLines = 1 }))
  return ui.row({ gap = 8, align = "center" }, children)
end

local function rows()
  if type(snapshot) ~= "table" then
    return { line("Herdr", "Checking agents…", "on_surface") }
  end
  if snapshot.waitingForServer and not snapshot.workerFailed then
    return { line("Herdr", "Waiting for the Herdr server to start", common.WAITING_COLOR) }
  end
  local out = {}
  local now = os.time()
  local usageShown = false
  for _, agentType in ipairs({ "claude", "codex" }) do
    local usage = type(snapshot.usage) == "table" and snapshot.usage[agentType] or nil
    local text = common.formatUsage(usage, now)
    if text ~= "" then
      table.insert(out, line(common.AGENT_TYPES[agentType].label, text, "on_surface", common.iconPath(agentType)))
      usageShown = true
    end
  end
  if usageShown then
    table.insert(out, ui.separator({}))
  end
  local agents = common.sortAgents(snapshot.agents or {})
  for index, agent in ipairs(agents) do
    if index > MAX_ROWS then
      table.insert(out, line(`… {#agents - MAX_ROWS} more`, "", "on_surface_variant"))
      break
    end
    local info = common.STATES[agent.state] or common.STATES.unknown
    local detail = info.label
    if type(agent.sessionTitle) == "string" and agent.sessionTitle ~= "" then
      detail = `{agent.sessionTitle} · {info.label}`
    end
    table.insert(out, line(agent.displayName or agent.location or "?", detail, info.color, common.iconPath(agent.agentType)))
  end
  if #agents == 0 then
    table.insert(out, line("Herdr", "No agents found", "on_surface_variant"))
  end
  for _, err in ipairs(snapshot.errors or {}) do
    local message = snapshot.workerFailed and tostring(err.message) or "unavailable"
    table.insert(out, line(err.machine or "Herdr", message, common.WAITING_COLOR))
  end
  return out
end

local function render()
  layer.render(ui.column({
    width = WIDTH,
    gap = 4,
    padding = 10,
    radius = 10,
    fill = "surface",
    border = "outline_variant",
    borderWidth = 1,
    align = "stretch",
  }, rows()))
end

noctalia.state.watch("snapshot", function(value)
  snapshot = value
  render()
end)

render()
