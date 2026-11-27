--!nonstrict
-- Shared config, model and formatting for the Agent Accounts plugin.

local M = {}

M.VERSION = "0.1.0"
M.PANEL_ID = "scriptoza/agent-accounts:panel"
M.WIDGET_ID = "scriptoza/agent-accounts:bar"

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
  previewBar = "auto",
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
    previewBar = type(raw.previewBar) == "string" and raw.previewBar ~= "" and raw.previewBar or "auto",
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

-- Same rules as the Agent Accounts web UI: a window whose reset is unknown, or a full window away, has not
-- started; a reported reset that already passed has ended. A window started on request (window_started_at)
-- counts as started until it would end, and its reset follows from the start while the provider still
-- reports the pre-start state. Returns { used, notStarted, resetsAt }.
function M.windowState(profile, limit, now)
  local span = (tonumber(limit.window_minutes) or 0) * 60
  local used = limit.exhausted == true and 100 or math.max(0, math.min(100, tonumber(limit.used_percent) or 0))
  local snapshot = type(profile.snapshot) == "table" and profile.snapshot or {}
  local observed = tonumber(snapshot.observed_at) or now
  local started = tonumber(profile.window_started_at)
  local startedReset = span > 0 and started and started + span > now and started + span or nil
  local resetsAt = tonumber(limit.resets_at)
  local fullWindowAway = not resetsAt or resetsAt - observed >= span - 120
  local notStarted = false
  if span > 0 and not startedReset then
    if resetsAt and resetsAt <= now then
      notStarted = true
    else
      notStarted = used == 0 and fullWindowAway
    end
  end
  if notStarted then
    return { used = 0, notStarted = true, resetsAt = nil }
  end
  if used == 0 and startedReset and fullWindowAway then
    resetsAt = startedReset
  end
  return { used = used, notStarted = false, resetsAt = resetsAt }
end

-- Used percentage of the longest and the shortest shown window, 0..100 each; equal for a single window.
function M.windowsUsed(profile, config)
  local limits = M.limitsOf(profile, config)
  if #limits == 0 then
    return 0, 0
  end
  local now = os.time()
  local longest = M.windowState(profile, limits[#limits], now).used
  local shortest = M.windowState(profile, limits[1], now).used
  return longest, shortest
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

-- Position of the bar that holds this widget (or of the chosen bar), from the Noctalia config.
function M.barPosition(chosen)
  local function position(name)
    local value = noctalia.getSetting(`bar.{name}.position`)
    return type(value) == "string" and value or nil
  end
  if type(chosen) == "string" and chosen ~= "" and chosen ~= "auto" then
    local value = position(chosen)
    if value then
      return value
    end
  end
  local order = noctalia.getSetting("bar.order")
  if type(order) ~= "table" then
    return "top"
  end
  for _, name in ipairs(order) do
    for _, section in ipairs({ "start", "center", "end" }) do
      local items = noctalia.getSetting(`bar.{name}.{section}`)
      if type(items) == "table" and table.find(items, M.WIDGET_ID) then
        return position(name) or "top"
      end
    end
  end
  return order[1] and position(order[1]) or "top"
end

-- Places the hover preview on the bar's edge, centered along it (the widget sits in the bar's center section).
function M.previewPlacement(outputName, chosenBar)
  local position = M.barPosition(chosenBar)
  local edge = position == "bottom" and "bottom" or position == "left" and "left" or position == "right" and "right" or "top"
  return { anchors = { edge }, margins = { [edge] = 4 }, clickThrough = true, output = outputName or "focused" }
end

M.GAUGE_STEP = 2

local function gaugeStep(used)
  used = math.max(0, math.min(100, tonumber(used) or 0))
  local step = math.floor(used / M.GAUGE_STEP + 0.5) * M.GAUGE_STEP
  if used > 0 then
    step = math.max(M.GAUGE_STEP, step)
  end
  if used < 100 then
    step = math.min(100 - M.GAUGE_STEP, step)
  end
  return step
end

local function gaugeSvg(color, outer, inner)
  local circumference = 2 * math.pi * 8.2
  local parts = {
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">',
    `<circle cx="10" cy="10" r="8.2" fill="none" stroke="{color}" stroke-width="2.6" opacity="0.22"/>`,
  }
  if outer >= 100 then
    table.insert(parts, `<circle cx="10" cy="10" r="8.2" fill="none" stroke="{color}" stroke-width="2.6"/>`)
  elseif outer > 0 then
    table.insert(parts, string.format(
      '<circle cx="10" cy="10" r="8.2" fill="none" stroke="%s" stroke-width="2.6" stroke-dasharray="%.2f %.2f" transform="rotate(-90 10 10)"/>',
      color, outer / 100 * circumference, circumference
    ))
  end
  table.insert(parts, `<circle cx="10" cy="10" r="5.2" fill="{color}" opacity="0.12"/>`)
  if inner >= 100 then
    table.insert(parts, `<circle cx="10" cy="10" r="5.2" fill="{color}"/>`)
  elseif inner > 0 then
    local angle = inner / 100 * 2 * math.pi
    local large = inner > 50 and 1 or 0
    table.insert(parts, string.format(
      '<path d="M10 10 L10 4.8 A5.2 5.2 0 %d 1 %.2f %.2f Z" fill="%s"/>',
      large, 10 + 5.2 * math.sin(angle), 10 - 5.2 * math.cos(angle), color
    ))
  end
  table.insert(parts, "</svg>\n")
  return table.concat(parts)
end

local gaugeCache = {}

-- Path of a cached SVG gauge: outer arc and inner pie, both filled clockwise from 12 o'clock.
function M.gaugeImage(color, outerUsed, innerUsed)
  local outer, inner = gaugeStep(outerUsed), gaugeStep(innerUsed)
  local key = `{color}-{outer}-{inner}`
  if gaugeCache[key] then
    return gaugeCache[key]
  end
  local base = noctalia.getenv("XDG_CACHE_HOME")
  if not base or base == "" then
    base = noctalia.expandPath("~/.cache")
  end
  local dir = base .. "/scriptoza/agent-accounts"
  local path = `{dir}/gauge-{(string.gsub(color, "#", ""))}-{outer}-{inner}.svg`
  if not noctalia.fileExists(path) then
    noctalia.mkdirAll(dir)
    noctalia.writeFile(path, gaugeSvg(color, outer, inner))
  end
  gaugeCache[key] = path
  return path
end

-- Concentric gauge: outer arc = longest window, inner pie = shortest window; size in logical px.
function M.usageDot(color, outerUsed, innerUsed, opacity, size)
  local gaugeSize = size or 20
  return ui.row({ width = gaugeSize, height = gaugeSize, align = "center", justify = "center", opacity = opacity }, {
    ui.image({ path = M.gaugeImage(color, outerUsed, innerUsed), width = gaugeSize, height = gaugeSize, fit = "contain" }),
  })
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
