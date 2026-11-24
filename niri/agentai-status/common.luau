--!nonstrict
-- Shared model, formatting and paths for the Herdr Agent Status plugin.

local M = {}

M.VERSION = "0.1.0"
M.PANEL_ID = "scriptoza/agentai-status:panel"

M.STATES = {
  blocked = { label = "Needs attention", color = "#f66151", glyph = "alert-triangle" },
  done = { label = "Done", color = "#57e389", glyph = "check" },
  working = { label = "Working", color = "#62a0ea", glyph = "player-play" },
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

-- Shortens text to at most `limit` characters, counted in UTF-8 code points.
function M.truncate(text, limit)
  text = tostring(text or "")
  local length = utf8.len(text)
  if not length or length <= limit then
    return text
  end
  return string.sub(text, 1, utf8.offset(text, limit) - 1) .. "…"
end

function M.clock(ms)
  if not ms then
    return "—"
  end
  return os.date("%H:%M:%S", math.floor(ms / 1000))
end

-- kind: "solid", "ring" or "ring-dot"; size in logical px.
function M.dot(kind, color, opacity, size)
  size = size or 12
  local ringSize = math.floor(size * 0.9 + 0.5)
  if kind == "solid" then
    return ui.box({ width = ringSize, height = ringSize, radius = ringSize / 2, fill = color, opacity = opacity })
  end
  local children = {}
  if kind == "ring-dot" then
    local inner = math.max(3, math.floor(size * 0.32 + 0.5))
    children = { ui.box({ width = inner, height = inner, radius = inner / 2, fill = color }) }
  end
  return ui.row({
    width = ringSize,
    height = ringSize,
    radius = ringSize / 2,
    border = color,
    borderWidth = math.max(1, size * 0.11),
    align = "center",
    justify = "center",
    opacity = opacity,
  }, children)
end

return M
