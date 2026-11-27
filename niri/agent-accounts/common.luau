--!nonstrict
-- Shared config, model and formatting for the Agent Accounts plugin.

local M = {}

M.VERSION = "0.1.0"
M.PANEL_ID = "scriptoza/agent-accounts:panel"

M.WAITING_COLOR = "#f8e45c"
M.ERROR_COLOR = "#f66151"
M.IDLE_COLOR = "#b0b0b0"

M.PROVIDERS = {
  claude = { label = "CLAUDE", color = "#e0896a" },
  antigravity = { label = "ANTIGRAVITY", color = "#62a0ea" },
  codex = { label = "CODEX", color = "#57e389" },
}

M.GROUP_LABELS = {
  ["Gemini Models"] = "Gemini",
  ["Claude and GPT models"] = "Claude & GPT",
}

M.DEFAULT_CONFIG = {
  servers = { "http://limits.homestack.app:8080/", "https://limits.hs.armum.eu/" },
  activeServer = 0,
  pollSeconds = 60,
  showFree = false,
  order = {},
  groups = {},
}

local function trim(value)
  if type(value) ~= "string" then
    return ""
  end
  return (string.gsub(string.gsub(value, "^%s+", ""), "%s+$", ""))
end

-- Accepts "host:port", "host" or a full URL and returns a base URL ending in "/".
function M.normalizeServer(value)
  local text = trim(value)
  if text == "" or string.find(text, "%s") then
    return nil
  end
  if not string.match(text, "^https?://") then
    text = "http://" .. text
  end
  if not string.match(text, "/$") then
    text ..= "/"
  end
  return text
end

function M.configPath()
  local base = noctalia.getenv("XDG_CONFIG_HOME")
  if not base or base == "" then
    base = noctalia.expandPath("~/.config")
  end
  return base .. "/scriptoza/agent-accounts.json"
end

local function readRaw(path)
  local text = noctalia.readFile(path)
  local value = text and noctalia.json.decode(text)
  return type(value) == "table" and value or nil
end

local function writeConfig(config, path)
  local dir = string.match(path, "^(.*)/[^/]+$")
  if dir then
    noctalia.mkdirAll(dir)
  end
  local text, err = noctalia.json.encode(config, true)
  if not text then
    return false, err
  end
  return noctalia.writeFile(path, text .. "\n")
end

local function normalizeConfig(raw)
  if type(raw) ~= "table" then
    raw = {}
  end
  local servers = {}
  if type(raw.servers) == "table" then
    for _, entry in ipairs(raw.servers) do
      local server = M.normalizeServer(entry)
      if server and not table.find(servers, server) then
        table.insert(servers, server)
      end
    end
  end
  if #servers == 0 then
    servers = table.clone(M.DEFAULT_CONFIG.servers)
  end
  local active = tonumber(raw.activeServer)
  if not active or active ~= math.floor(active) or active < 0 or active >= #servers then
    active = 0
  end
  local poll = tonumber(raw.pollSeconds)
  if not poll or poll < 10 then
    poll = M.DEFAULT_CONFIG.pollSeconds
  end
  local order = {}
  if type(raw.order) == "table" then
    for _, id in ipairs(raw.order) do
      if type(id) == "string" and not table.find(order, id) then
        table.insert(order, id)
      end
    end
  end
  local groups = {}
  if type(raw.groups) == "table" then
    for id, group in pairs(raw.groups) do
      if type(id) == "string" and type(group) == "string" then
        groups[id] = group
      end
    end
  end
  return {
    servers = servers,
    activeServer = active,
    url = servers[active + 1],
    pollSeconds = math.floor(poll + 0.5),
    showFree = raw.showFree == true,
    order = order,
    groups = groups,
  }
end

function M.loadConfig()
  local path = M.configPath()
  if not noctalia.fileExists(path) then
    writeConfig(table.clone(M.DEFAULT_CONFIG), path)
  end
  return normalizeConfig(readRaw(path))
end

-- Merges a patch over the existing file, keeping unknown keys, and asks the service to poll again.
function M.updateConfig(patch)
  local path = M.configPath()
  local existing = readRaw(path) or {}
  local merged = normalizeConfig(existing)
  merged.url = nil
  for key, value in pairs(existing) do
    merged[key] = value
  end
  for key, value in pairs(patch) do
    merged[key] = value
  end
  local ok, err = writeConfig(merged, path)
  if not ok then
    noctalia.log(`Agent Accounts: cannot save config: {err}`)
  end
  noctalia.state.set("configRev", noctalia.nowMs())
  return ok
end

-- ── Model ────────────────────────────────────────────────────────────────────

function M.isFree(profile)
  local account = type(profile.account) == "table" and profile.account or {}
  return type(account.plan) == "string" and string.lower(account.plan) == "free"
end

function M.groupsOf(profile)
  local groups = {}
  local snapshot = type(profile.snapshot) == "table" and profile.snapshot or {}
  for _, limit in ipairs(snapshot.limits or {}) do
    if type(limit.model) == "string" and not table.find(groups, limit.model) then
      table.insert(groups, limit.model)
    end
  end
  return groups
end

-- The configured group, else the first Gemini group, else the first group.
function M.selectedGroup(profile, config)
  local groups = M.groupsOf(profile)
  if #groups == 0 then
    return nil
  end
  local wanted = config.groups[profile.id]
  if wanted and table.find(groups, wanted) then
    return wanted
  end
  for _, group in ipairs(groups) do
    if string.find(string.lower(group), "gemini", 1, true) then
      return group
    end
  end
  return groups[1]
end

function M.groupLabel(group)
  return M.GROUP_LABELS[group] or group
end

-- Limits to show for a profile, shortest window first.
function M.limitsOf(profile, config)
  local snapshot = type(profile.snapshot) == "table" and profile.snapshot or {}
  local group = M.selectedGroup(profile, config)
  local out = {}
  for _, limit in ipairs(snapshot.limits or {}) do
    if type(limit) == "table" and (group == nil or limit.model == group) then
      table.insert(out, limit)
    end
  end
  table.sort(out, function(left, right)
    return (left.window_minutes or 0) < (right.window_minutes or 0)
  end)
  return out
end

-- Highest used percentage among the shown windows, 0..100.
function M.maxUsed(profile, config)
  local used = 0
  for _, limit in ipairs(M.limitsOf(profile, config)) do
    local value = limit.exhausted == true and 100 or tonumber(limit.used_percent) or 0
    used = math.max(used, value)
  end
  return math.max(0, math.min(100, used))
end

-- Profiles filtered by the free toggle and sorted by the configured order (unknown ones keep API order).
function M.visibleProfiles(profiles, config)
  local out = {}
  for index, profile in ipairs(profiles or {}) do
    if type(profile) == "table" and not profile.deleting and (config.showFree or not M.isFree(profile)) then
      table.insert(out, { profile = profile, index = index })
    end
  end
  table.sort(out, function(left, right)
    local lo = table.find(config.order, left.profile.id) or (1000 + left.index)
    local ro = table.find(config.order, right.profile.id) or (1000 + right.index)
    return lo < ro
  end)
  local sorted = table.create(#out)
  for _, entry in ipairs(out) do
    table.insert(sorted, entry.profile)
  end
  return sorted
end

-- ── Formatting ───────────────────────────────────────────────────────────────

function M.windowLabel(minutes)
  minutes = tonumber(minutes) or 0
  if minutes > 0 and minutes % 1440 == 0 then
    return `{minutes // 1440}-day`
  elseif minutes > 0 and minutes % 60 == 0 then
    return `{minutes // 60}-hour`
  end
  return `{minutes}-min`
end

function M.shortWindow(minutes)
  minutes = tonumber(minutes) or 0
  if minutes > 0 and minutes % 1440 == 0 then
    return `{minutes // 1440}d`
  elseif minutes > 0 and minutes % 60 == 0 then
    return `{minutes // 60}h`
  end
  return `{minutes}m`
end

function M.percent(value)
  return string.format("%.1f%%", tonumber(value) or 0)
end

function M.dateTime(seconds)
  if not seconds then
    return "—"
  end
  return os.date("%Y-%m-%d %H:%M", math.floor(seconds))
end

function M.clock(ms)
  if not ms then
    return "—"
  end
  return os.date("%H:%M:%S", math.floor(ms / 1000))
end

local function addMonth(seconds)
  local parts = os.date("*t", math.floor(seconds))
  parts.month += 1
  return os.time(parts)
end

-- "Ends in 12d 13h" from the owner-entered last payment (plus one month) or the provider period end.
function M.periodLeft(profile, now)
  local account = type(profile.account) == "table" and profile.account or {}
  local ends = nil
  if tonumber(profile.last_payment) then
    ends = addMonth(profile.last_payment)
  elseif tonumber(account.period_end) then
    ends = account.period_end
  end
  if not ends then
    return nil
  end
  local left = ends - now
  if left <= 0 then
    return "Ended"
  end
  local days = left // 86400
  local hours = (left % 86400) // 3600
  if days > 0 then
    return `Ends in {days}d {hours}h`
  end
  return `Ends in {hours}h {(left % 3600) // 60}m`
end

function M.accountName(profile)
  local account = type(profile.account) == "table" and profile.account or {}
  local name = account.email
  if type(name) ~= "string" or name == "" then
    name = profile.display_name
  end
  return type(name) == "string" and name ~= "" and name or "?"
end

function M.providerInfo(profile)
  return M.PROVIDERS[profile.provider] or { label = string.upper(tostring(profile.provider or "?")), color = M.IDLE_COLOR }
end

-- Problem text for a profile, or nil when it is healthy.
function M.problem(profile)
  if profile.enabled == false then
    return "Disabled"
  end
  if type(profile.error) == "table" and profile.error.message then
    return tostring(profile.error.message)
  end
  if profile.auth_status and profile.auth_status ~= "authenticated" then
    return `Authentication: {profile.auth_status}`
  end
  if profile.stale then
    return "Stale data"
  end
  return nil
end

-- Places the hover preview on the bar's edge, at the end where the status widgets sit.
function M.previewPlacement(outputName)
  local position = noctalia.getSetting("bar.default.position") or "top"
  local anchors = { "top", "right" }
  local margins = { top = 4, right = 8 }
  if position == "bottom" then
    anchors = { "bottom", "right" }
    margins = { bottom = 4, right = 8 }
  elseif position == "left" then
    anchors = { "left", "bottom" }
    margins = { left = 4, bottom = 8 }
  elseif position == "right" then
    anchors = { "right", "bottom" }
    margins = { right = 4, bottom = 8 }
  end
  return { anchors = anchors, margins = margins, clickThrough = true, output = outputName or "focused" }
end

-- A ring whose center disc grows with the used fraction (area-proportional); size in logical px.
function M.usageDot(color, used, opacity, size)
  size = size or 12
  local ringSize = math.floor(size * 0.9 + 0.5)
  local border = math.max(1, size * 0.11)
  local innerMax = ringSize - 2 * border - 2
  local inner = math.floor(innerMax * math.sqrt(math.max(0, math.min(100, used)) / 100) + 0.5)
  local children = {}
  if inner >= 2 then
    children = { ui.box({ width = inner, height = inner, radius = inner / 2, fill = color }) }
  end
  return ui.row({
    width = ringSize,
    height = ringSize,
    radius = ringSize / 2,
    border = color,
    borderWidth = border,
    align = "center",
    justify = "center",
    opacity = opacity,
  }, children)
end

-- Horizontal usage bar; flex weights avoid depending on the container width.
function M.usageBar(color, used, height)
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

return M
