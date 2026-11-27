--!nonstrict
-- Shared model, formatting and paths for the Herdr Agent Status plugin.

local M = {}

M.VERSION = "0.1.0"
M.PANEL_ID = "scriptoza/agentai-status:panel"
M.WIDGET_ID = "scriptoza/agentai-status:bar"

M.STATES = {
  blocked = { label = "Needs attention", color = "#f66151", glyph = "alert-triangle" },
  done = { label = "Done", color = "#57e389", glyph = "check" },
  working = { label = "Working", color = "#c061cb", glyph = "player-play" },
  unknown = { label = "Unknown", color = "#f8e45c", glyph = "help" },
  idle = { label = "Idle", color = "#b0b0b0", glyph = "player-pause" },
  offline = { label = "Disconnected", color = "#777777", glyph = "wifi-off" },
}

M.AGENT_TYPES = {
  codex = { label = "Codex" },
  claude = { label = "Claude Code" },
  agy = { label = "Antigravity" },
}

M.WAITING_COLOR = "#f8e45c"
M.IDLE_COLOR = "#b0b0b0"

M.DENSITIES = { "large", "medium", "compact" }
M.PROFILES = {
  large = { name = 14, sub = 12, padV = 6, gap = 12, usagePadV = 3 },
  medium = { name = 13, sub = 11, padV = 4, gap = 10, usagePadV = 2 },
  compact = { name = 12, sub = 10, padV = 2, gap = 8, usagePadV = 1 },
}

local PRIORITIES = { blocked = 1, working = 2, done = 3, unknown = 4, offline = 5, idle = 6 }

-- The installer copies the worker and icons into the plugin directory; a
-- checkout used directly as a plugin source reads them from ai/agentai-status.
function M.assetRoot()
  local dir = noctalia.pluginDir() or "."
  if noctalia.fileExists(dir .. "/worker/status-worker.js") then
    return dir .. "/worker"
  end
  return dir .. "/../../gnome/agentai-status"
end

function M.iconPath(agentType)
  local name = "anthropic.svg"
  if agentType == "codex" then
    name = noctalia.isDarkMode() and "openai-light.svg" or "openai.svg"
  elseif agentType == "agy" then
    name = "antigravity.svg"
  end
  return M.assetRoot() .. "/assets/icons/" .. name
end

-- ── Density config (shared with the GNOME extension) ─────────────────────────

local function configPath()
  local base = noctalia.getenv("XDG_CONFIG_HOME")
  if not base or base == "" then
    base = noctalia.expandPath("~/.config")
  end
  return base .. "/ai-agent-status/config.json"
end

local function readConfig()
  local text = noctalia.readFile(configPath())
  local value = text and noctalia.json.decode(text)
  return type(value) == "table" and value or {}
end

function M.loadDensity()
  local density = readConfig().density
  if M.PROFILES[density] then
    return density
  end
  return "large"
end

function M.saveDensity(density)
  local config = readConfig()
  config.density = density
  local path = configPath()
  noctalia.mkdirAll(string.match(path, "^(.*)/[^/]+$"))
  local text = noctalia.json.encode(config, true)
  local ok, err = noctalia.writeFile(path, (text or "{}") .. "\n")
  if not ok then
    noctalia.log(`Agent Status: cannot save the density: {err}`)
  end
end

-- ── Model ────────────────────────────────────────────────────────────────────

function M.sortAgents(agents)
  local sorted = table.clone(agents)
  table.sort(sorted, function(left, right)
    local lp, rp = PRIORITIES[left.state] or 99, PRIORITIES[right.state] or 99
    if lp ~= rp then
      return lp < rp
    end
    if left.state == "done" or left.state == "idle" then
      local la, ra = left.lastActivityAt or 0, right.lastActivityAt or 0
      if la ~= ra then
        return la > ra
      end
    end
    return (left.location or "") < (right.location or "")
  end)
  return sorted
end

local function formatRemaining(seconds)
  local minutes = math.max(1, math.ceil(seconds / 60))
  if minutes >= 1440 then
    return `{math.floor(minutes / 1440)}d`
  elseif minutes >= 60 then
    return string.format("%dh%02dm", math.floor(minutes / 60), minutes % 60)
  end
  return `{minutes}m`
end

function M.formatUsage(usage, now)
  if type(usage) ~= "table" then
    return ""
  end
  local parts = {}
  for _, pair in ipairs({ { "five", "5h" }, { "week", "wk" } }) do
    local window = usage[pair[1]]
    if type(window) == "table" and window.resetsAt and window.resetsAt > now then
      local left = math.max(0, math.min(100, math.floor(100 - (window.usedPercent or 0) + 0.5)))
      table.insert(parts, string.format("%s %d%% · %-5s", pair[2], left, formatRemaining(window.resetsAt - now)))
    end
  end
  return table.concat(parts, "  ")
end

-- Position of the bar that holds this widget (or of the chosen bar), and the bar section ("start", "center" or
-- "end") the widget is in, from the Noctalia config.
function M.barPosition(chosen)
  local function position(name)
    local value = noctalia.getSetting(`bar.{name}.position`)
    return type(value) == "string" and value or nil
  end
  local order = noctalia.getSetting("bar.order")
  local first
  if type(order) == "table" then
    for _, name in ipairs(order) do
      for _, section in ipairs({ "start", "center", "end" }) do
        local items = noctalia.getSetting(`bar.{name}.{section}`)
        local found = type(items) == "table" and table.find(items, M.WIDGET_ID) ~= nil
        if type(items) == "table" and not found then
          local groups = noctalia.getSetting(`bar.{name}.capsule_group`)
          for _, group in ipairs(type(groups) == "table" and groups or {}) do
            if type(group) == "table" and type(group.members) == "table" and table.find(group.members, M.WIDGET_ID)
              and table.find(items, `group:{group.id}`) then
              found = true
            end
          end
        end
        if found then
          first = first or { name = name, section = section }
        end
      end
    end
  end
  if type(chosen) == "string" and chosen ~= "" and chosen ~= "auto" then
    local value = position(chosen)
    if value then
      return value, first and first.section or "end"
    end
  end
  if first then
    return position(first.name) or "top", first.section
  end
  return type(order) == "table" and order[1] and position(order[1]) or "top", "end"
end

-- Places the hover preview on the bar's edge, above the section that holds the widget: at the start, the middle
-- or the end of the bar.
function M.previewPlacement(outputName, chosenBar)
  local position, section = M.barPosition(chosenBar)
  local edge = position == "bottom" and "bottom" or position == "left" and "left" or position == "right" and "right" or "top"
  local vertical = edge == "left" or edge == "right"
  local anchors = { edge }
  local margins = { [edge] = 4 }
  if section == "start" then
    local side = vertical and "top" or "left"
    table.insert(anchors, side)
    margins[side] = 8
  elseif section ~= "center" then
    local side = vertical and "bottom" or "right"
    table.insert(anchors, side)
    margins[side] = 8
  end
  return { anchors = anchors, margins = margins, clickThrough = true, output = outputName or "focused" }
end

function M.clock(ms)
  if not ms then
    return "—"
  end
  return os.date("%H:%M:%S", math.floor(ms / 1000))
end

return M
