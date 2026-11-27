--!nonstrict
-- Read-only hover preview shown under the bar while the pointer is over the
-- widget: agents with state and session title, and unavailable machines in a dense list.

local common = require("./common.luau")

local MIN_WIDTH = 360
local MAX_WIDTH = 640
local MAX_AGENTS = 20
local NAME_SIZE = 12
local DETAIL_SIZE = 11

local PROVIDERS = {
  claude = { label = "CLAUDE", color = "#e0896a" },
  codex = { label = "CODEX", color = "#57e389" },
  agy = { label = "ANTIGRAVITY", color = "#62a0ea" },
}

local snapshot = noctalia.state.get("snapshot")

local function providerInfo(agentType)
  return PROVIDERS[agentType] or { label = string.upper(tostring(agentType or "?")), color = common.IDLE_COLOR }
end

local function line(children)
  return ui.row({ gap = 8, align = "center" }, children)
end

local function message(text, color)
  return line({ ui.label({ text = text, color = color, fontSize = NAME_SIZE, maxLines = 2, flexGrow = 1 }) })
end

local function agentName(agent)
  local name = agent.displayName or agent.location or "?"
  local typeInfo = common.AGENT_TYPES[agent.agentType]
  if typeInfo then
    local suffix = ` · {typeInfo.label}`
    if string.sub(name, -#suffix) == suffix then
      name = string.sub(name, 1, #name - #suffix)
    end
  end
  return name
end

local function agentBlock(agent)
  local provider = providerInfo(agent.agentType)
  local state = common.STATES[agent.state] or common.STATES.unknown
  local children = {
    line({
      ui.label({ text = provider.label, color = provider.color, fontWeight = "bold", fontSize = NAME_SIZE }),
      ui.label({ text = agentName(agent), color = "on_surface", fontWeight = "semibold", fontSize = NAME_SIZE, maxLines = 1 }),
      ui.spacer({ flexGrow = 1 }),
      ui.label({ text = state.label, color = state.color, fontSize = DETAIL_SIZE, maxLines = 1 }),
    }),
  }
  local typeInfo = common.AGENT_TYPES[agent.agentType]
  local title = type(agent.sessionTitle) == "string" and agent.sessionTitle or ""
  if title ~= "" and not (typeInfo and title == typeInfo.label) then
    table.insert(children, ui.label({ text = title, color = "on_surface_variant", fontSize = DETAIL_SIZE, maxLines = 1 }))
  end
  return ui.column({ gap = 2 }, children)
end

local function rows()
  if type(snapshot) ~= "table" then
    return { message("Checking agents…", "on_surface_variant") }
  end
  if snapshot.waitingForServer and not snapshot.workerFailed then
    return { message("Waiting for the Herdr server to start", common.WAITING_COLOR) }
  end
  local out = {}
  local agents = common.sortAgents(snapshot.agents or {})
  for index, agent in ipairs(agents) do
    if #out > 0 then
      table.insert(out, ui.separator({}))
    end
    if index > MAX_AGENTS then
      table.insert(out, message(`… {#agents - MAX_AGENTS} more`, "on_surface_variant"))
      break
    end
    table.insert(out, agentBlock(agent))
  end
  if #agents == 0 then
    table.insert(out, message("No agents found", "on_surface_variant"))
  end
  for _, err in ipairs(snapshot.errors or {}) do
    local text = snapshot.workerFailed and tostring(err.message) or "unavailable"
    if #out > 0 then
      table.insert(out, ui.separator({}))
    end
    table.insert(out, line({
      ui.label({ text = err.machine or "Herdr", color = "on_surface", fontWeight = "semibold", fontSize = NAME_SIZE, maxLines = 1 }),
      ui.spacer({ flexGrow = 1 }),
      ui.label({ text = text, color = common.WAITING_COLOR, fontSize = DETAIL_SIZE, maxLines = 1 }),
    }))
  end
  return out
end

local function render()
  layer.render(ui.column({
    minWidth = MIN_WIDTH,
    maxWidth = MAX_WIDTH,
    gap = 6,
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
