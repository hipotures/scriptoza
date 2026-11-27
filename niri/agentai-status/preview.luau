--!nonstrict
-- Read-only hover preview shown under the bar while the pointer is over the
-- widget: usage limits, agents with state and session title, and unavailable
-- machines in a dense list.

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

local function resetShort(seconds, now)
  if seconds - now < 86400 then
    return os.date("%H:%M", math.floor(seconds))
  end
  return os.date("%m-%d %H:%M", math.floor(seconds))
end

-- Fixed-width, right-aligned cell so the columns and the line ends match across providers.
local function cell(text, width)
  return ui.row({ width = width, justify = "end" }, {
    ui.label({ text = text, color = "on_surface_variant", fontSize = DETAIL_SIZE, maxLines = 1 }),
  })
end

-- Horizontal usage bar; flex weights avoid depending on the container width.
local function usageBar(color, used, height)
  used = math.max(0, math.min(100, tonumber(used) or 0))
  local children = {}
  if used > 0 then
    table.insert(children, ui.box({ flexGrow = used, height = height, radius = 2, fill = color }))
  end
  if used < 100 then
    table.insert(children, ui.spacer({ flexGrow = 100 - used }))
  end
  return ui.row({ height = height, radius = 2, fill = "on_surface/0.12", align = "stretch" }, children)
end

local function usageBlock(agentType, usage, now)
  local info = providerInfo(agentType)
  local windows = {}
  for _, pair in ipairs({ { "five", "5h" }, { "week", "7d" } }) do
    local window = usage[pair[1]]
    if type(window) == "table" and window.resetsAt and window.resetsAt > now then
      local used = math.max(0, math.min(100, tonumber(window.usedPercent) or 0))
      table.insert(windows, ui.row({ gap = 6, align = "center" }, {
        ui.label({ text = pair[2], width = 22, color = "on_surface_variant", fontSize = DETAIL_SIZE }),
        ui.column({ width = 90 }, { usageBar(info.color, used, 5) }),
        cell(string.format("%.1f%% used", used), 72),
        cell(resetShort(window.resetsAt, now), 72),
      }))
    end
  end
  if #windows == 0 then
    return nil
  end
  return ui.column({ gap = 2 }, {
    line({
      ui.label({ text = info.label, color = info.color, fontWeight = "bold", fontSize = NAME_SIZE }),
      ui.label({ text = "Usage limits", color = "on_surface", fontWeight = "semibold", fontSize = NAME_SIZE, maxLines = 1 }),
    }),
    ui.row({ gap = 16, align = "center" }, windows),
  })
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
  if type(agent.sessionTitle) == "string" and agent.sessionTitle ~= "" then
    table.insert(children, ui.label({ text = agent.sessionTitle, color = "on_surface_variant", fontSize = DETAIL_SIZE, maxLines = 1 }))
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
  local now = os.time()
  for _, agentType in ipairs({ "claude", "codex" }) do
    local usage = type(snapshot.usage) == "table" and snapshot.usage[agentType] or nil
    local block = type(usage) == "table" and usageBlock(agentType, usage, now) or nil
    if block then
      if #out > 0 then
        table.insert(out, ui.separator({}))
      end
      table.insert(out, block)
    end
  end
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
