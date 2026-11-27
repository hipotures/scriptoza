--!nonstrict
-- Shared config, torrent model and formatting for the rTorrent Status plugin.
-- The config file is the same one the GNOME extension uses.

local M = {}

M.VERSION = "0.1.0"
M.PANEL_ID = "scriptoza/rtorrent-status:panel"
M.WIDGET_ID = "scriptoza/rtorrent-status:bar"

M.STATES = {
  error = { color = "#ff5555", glyph = "alert-triangle", label = "Error", rank = 0 },
  hashing = { color = "#f8e45c", glyph = "refresh", label = "Hashing", rank = 1 },
  downloading = { color = "#3584e4", glyph = "download", label = "Downloading", rank = 2 },
  seeding = { color = "#2ec27e", glyph = "check", label = "Seeding", rank = 3 },
  paused = { color = "#9a9996", glyph = "player-pause", label = "Paused", rank = 4 },
}

M.WAITING_COLOR = "#f8e45c"
M.IDLE_COLOR = "#9a9996"

M.DENSITIES = { "large", "medium", "compact" }
M.DENSITY_LABELS = { large = "Large", medium = "Medium", compact = "Compact" }
M.PROFILES = {
  large = { name = 14, sub = 12, padV = 6, gap = 12 },
  medium = { name = 13, sub = 11, padV = 4, gap = 10 },
  compact = { name = 12, sub = 10, padV = 2, gap = 8 },
}

M.SORT_FIELDS = { "state", "added", "name", "progress", "size", "down", "up", "eta" }
M.SORT_LABELS = {
  state = "State",
  added = "Added",
  name = "Name",
  progress = "Progress",
  size = "Size",
  down = "Down",
  up = "Up",
  eta = "ETA",
}

M.DEFAULT_CONFIG = {
  name = "rtorrent",
  host = "127.0.0.1",
  port = 5000,
  servers = { { host = "127.0.0.1", port = 5000 } },
  activeServer = 0,
  pollSeconds = 3,
  density = "large",
  sortBy = "state",
  sortDir = "asc",
  anonymize = false,
}

local function contains(list, value)
  for _, item in ipairs(list) do
    if item == value then
      return true
    end
  end
  return false
end
M.contains = contains

local function indexOf(list, value)
  for index, item in ipairs(list) do
    if item == value then
      return index
    end
  end
  return 0
end
M.indexOf = indexOf

local function trim(value)
  if type(value) ~= "string" then
    return ""
  end
  return noctalia.string.trim(value)
end

function M.configPath()
  local base = noctalia.getenv("XDG_CONFIG_HOME")
  if not base or base == "" then
    base = noctalia.expandPath("~/.config")
  end
  return base .. "/scriptoza/rtorrent-status.json"
end

local function normalizeServer(entry)
  if type(entry) ~= "table" then
    return nil
  end
  local host = trim(entry.host)
  if host == "" then
    return nil
  end
  local port = tonumber(entry.port)
  if not port or port ~= math.floor(port) or port < 1 or port > 65535 then
    port = M.DEFAULT_CONFIG.port
  end
  return { host = host, port = port }
end

function M.parseServerSpec(spec)
  local text = trim(spec)
  if text == "" then
    return nil
  end
  local colon = string.find(text, ":[^:]*$")
  if colon and colon > 1 and string.sub(text, -1) ~= "]" then
    local host = trim(string.sub(text, 1, colon - 1))
    local port = tonumber(trim(string.sub(text, colon + 1)))
    if host == "" or not port or port ~= math.floor(port) or port < 1 or port > 65535 then
      return nil
    end
    return { host = host, port = port }
  end
  return { host = text, port = M.DEFAULT_CONFIG.port }
end

local function normalizeConfig(raw)
  if type(raw) ~= "table" then
    raw = {}
  end
  local name = trim(raw.name)
  if name == "" then
    name = M.DEFAULT_CONFIG.name
  end
  local fallback = normalizeServer({ host = raw.host, port = raw.port })
    or { host = M.DEFAULT_CONFIG.host, port = M.DEFAULT_CONFIG.port }
  local servers = {}
  if type(raw.servers) == "table" then
    for _, entry in ipairs(raw.servers) do
      local server = normalizeServer(entry)
      if server then
        table.insert(servers, server)
      end
    end
  end
  if #servers == 0 then
    servers = { fallback }
  end
  local active = tonumber(raw.activeServer)
  if not active or active ~= math.floor(active) or active < 0 or active >= #servers then
    active = 0
  end
  local current = servers[active + 1]
  local poll = tonumber(raw.pollSeconds)
  if not poll or poll < 1 then
    poll = M.DEFAULT_CONFIG.pollSeconds
  end
  return {
    name = name,
    host = current.host,
    port = current.port,
    servers = servers,
    activeServer = active,
    pollSeconds = math.floor(poll + 0.5),
    density = contains(M.DENSITIES, raw.density) and raw.density or M.DEFAULT_CONFIG.density,
    sortBy = contains(M.SORT_FIELDS, raw.sortBy) and raw.sortBy or M.DEFAULT_CONFIG.sortBy,
    sortDir = (raw.sortDir == "asc" or raw.sortDir == "desc") and raw.sortDir or M.DEFAULT_CONFIG.sortDir,
    anonymize = raw.anonymize == true,
  }
end

local function readRaw(path)
  local text = noctalia.readFile(path)
  if not text then
    return nil
  end
  local value = noctalia.json.decode(text)
  if type(value) ~= "table" then
    return nil
  end
  return value
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

local function copy(value)
  local out = {}
  for key, item in pairs(value) do
    out[key] = item
  end
  return out
end

function M.loadConfig()
  local path = M.configPath()
  if not noctalia.fileExists(path) then
    local initial = copy(M.DEFAULT_CONFIG)
    writeConfig(initial, path)
    return normalizeConfig(initial)
  end
  return normalizeConfig(readRaw(path))
end

-- Merges a patch over the existing file, keeping unknown keys.
function M.updateConfig(patch)
  local path = M.configPath()
  local existing = readRaw(path) or {}
  local merged = normalizeConfig(existing)
  for key, value in pairs(existing) do
    merged[key] = value
  end
  for key, value in pairs(patch) do
    merged[key] = value
  end
  local ok, err = writeConfig(merged, path)
  if not ok then
    noctalia.log(`rTorrent Status: cannot save config: {err}`)
  end
  noctalia.state.set("configRev", noctalia.nowMs())
  return ok
end

function M.saveServers(servers, active)
  local valid = {}
  for _, entry in ipairs(servers) do
    local server = normalizeServer(entry)
    if server then
      table.insert(valid, server)
    end
  end
  if #valid == 0 then
    return false
  end
  if active < 0 or active >= #valid then
    active = 0
  end
  local current = valid[active + 1]
  return M.updateConfig({ servers = valid, activeServer = active, host = current.host, port = current.port })
end

-- ── Formatting ───────────────────────────────────────────────────────────────

local UNITS = { "B", "KiB", "MiB", "GiB", "TiB" }

function M.formatBytes(bytes)
  local value = tonumber(bytes) or 0
  if value <= 0 then
    return "0 B"
  end
  local exp = math.min(math.floor(math.log(value) / math.log(1024)), #UNITS - 1)
  local scaled = value / (1024 ^ exp)
  local decimals = 2
  if exp == 0 or scaled >= 100 then
    decimals = 0
  elseif scaled >= 10 then
    decimals = 1
  end
  return string.format(`%.{decimals}f %s`, scaled, UNITS[exp + 1])
end

function M.formatRate(bytesPerSec)
  return M.formatBytes(bytesPerSec) .. "/s"
end

local function formatEta(remaining, rate)
  if remaining <= 0 or rate <= 0 then
    return ""
  end
  local total = math.ceil(remaining / rate)
  local days = math.floor(total / 86400)
  local hours = math.floor((total % 86400) / 3600)
  local minutes = math.floor((total % 3600) / 60)
  local seconds = total % 60
  if days > 0 then
    return `{days}d {hours}h`
  elseif hours > 0 then
    return string.format("%dh %02dm", hours, minutes)
  elseif minutes > 0 then
    return string.format("%dm %02ds", minutes, seconds)
  end
  return `{seconds}s`
end

local function classifyState(isActive, complete, hashing, message)
  if hashing > 0 then
    return "hashing"
  end
  if message ~= "" and string.sub(message, 1, 8) ~= "Tracker:" then
    return "error"
  end
  if isActive == 1 and complete == 0 then
    return "downloading"
  elseif isActive == 1 and complete == 1 then
    return "seeding"
  end
  return "paused"
end

local function num(value)
  local n = tonumber(value)
  if not n or n ~= n or n < 0 then
    return 0
  end
  return n
end

function M.normalizeTorrent(row, queueIndex)
  local message = type(row[11]) == "string" and trim(row[11]) or ""
  local size = num(row[7])
  local completed = num(row[8])
  local down = num(row[9])
  local up = num(row[10])
  local state = classifyState(num(row[4]), num(row[5]), num(row[6]), message)
  local percent = size > 0 and math.min(100, completed / size * 100) or 0
  local remaining = math.max(0, size - completed)
  local etaSeconds = nil
  local eta = ""
  if state == "downloading" and remaining > 0 and down > 0 then
    etaSeconds = math.ceil(remaining / down)
    eta = formatEta(remaining, down)
  end
  local hash = tostring(row[1] or "")
  local name = tostring(row[2] or "")
  return {
    hash = hash,
    name = name ~= "" and name or hash,
    sizeBytes = size,
    completedBytes = completed,
    downRate = down,
    upRate = up,
    peersConnected = num(row[12]),
    seeders = num(row[13]),
    leechers = num(row[14]),
    upTotal = num(row[15]),
    ratio = num(row[16]) / 1000,
    message = message,
    state = state,
    percent = percent,
    etaSeconds = etaSeconds,
    eta = eta,
    queueIndex = queueIndex,
  }
end

function M.subtitle(torrent)
  local parts = {
    string.format("%.1f%%", torrent.percent),
    `{M.formatBytes(torrent.completedBytes)} / {M.formatBytes(torrent.sizeBytes)}`,
  }
  if torrent.downRate > 0 then
    table.insert(parts, "↓ " .. M.formatRate(torrent.downRate))
  end
  if torrent.upRate > 0 then
    table.insert(parts, "↑ " .. M.formatRate(torrent.upRate))
  end
  if torrent.eta ~= "" then
    table.insert(parts, torrent.eta)
  end
  if torrent.state == "error" and torrent.message ~= "" then
    table.insert(parts, torrent.message)
  end
  return table.concat(parts, " · ")
end

function M.tooltip(torrent)
  local peers = "Peers: 0"
  if torrent.peersConnected > 0 then
    peers = `Peers: {torrent.peersConnected} ({torrent.seeders} seeds · {torrent.leechers} leechers)`
  end
  local rates = `↓ {M.formatRate(torrent.downRate)} · ↑ {M.formatRate(torrent.upRate)}`
  local ratio = string.format("Up: %s · Ratio: %.2f", M.formatBytes(torrent.upTotal), torrent.ratio)
  local base = `{peers} · {rates} · {ratio}`
  if torrent.state == "error" and torrent.message ~= "" then
    return base .. "\n" .. torrent.message
  end
  return base
end

function M.sortTorrents(torrents, sortBy, sortDir)
  local dir = sortDir == "desc" and -1 or 1
  local function primary(a, b)
    if sortBy == "added" then
      return (a.queueIndex - b.queueIndex) * dir
    elseif sortBy == "name" then
      local la, lb = string.lower(a.name), string.lower(b.name)
      return (la < lb and -1 or (la > lb and 1 or 0)) * dir
    elseif sortBy == "progress" then
      return (a.percent - b.percent) * dir
    elseif sortBy == "size" then
      return (a.sizeBytes - b.sizeBytes) * dir
    elseif sortBy == "down" then
      return (a.downRate - b.downRate) * dir
    elseif sortBy == "up" then
      return (a.upRate - b.upRate) * dir
    elseif sortBy == "eta" then
      local aHas, bHas = a.etaSeconds ~= nil, b.etaSeconds ~= nil
      if aHas ~= bHas then
        return aHas and -1 or 1
      end
      if not aHas then
        return 0
      end
      return (a.etaSeconds - b.etaSeconds) * dir
    end
    return (M.STATES[a.state].rank - M.STATES[b.state].rank) * dir
  end
  local sorted = table.clone(torrents)
  table.sort(sorted, function(a, b)
    local result = primary(a, b)
    if result ~= 0 then
      return result < 0
    end
    local rank = M.STATES[a.state].rank - M.STATES[b.state].rank
    if rank ~= 0 then
      return rank < 0
    end
    local la, lb = string.lower(a.name), string.lower(b.name)
    if la ~= lb then
      return la < lb
    end
    return a.queueIndex < b.queueIndex
  end)
  return sorted
end

function M.summarize(torrents)
  local counts = { error = 0, hashing = 0, downloading = 0, seeding = 0, paused = 0 }
  local down, up = 0, 0
  for _, torrent in ipairs(torrents) do
    counts[torrent.state] += 1
    down += torrent.downRate
    up += torrent.upRate
  end
  return { counts = counts, totalDownRate = down, totalUpRate = up }
end

-- ── Anonymization (32-bit FNV-1a seed + xorshift, as in the GNOME extension) ─

local TWO32 = 4294967296
local NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
local HEX_CHARS = "0123456789ABCDEF"

local function mul32(a, b)
  local lo = a * bit32.band(b, 0xffff)
  local hi = (a * bit32.rshift(b, 16)) % 65536
  return (lo + hi * 65536) % TWO32
end

local function seededString(seedText, salt, length, alphabet)
  local state = bit32.bxor(2166136261, salt % TWO32)
  for i = 1, #seedText do
    state = bit32.bxor(state, string.byte(seedText, i))
    state = mul32(state, 16777619)
  end
  if state == 0 then
    state = 0x9e3779b9
  end
  local out = table.create(length)
  for i = 1, length do
    state = bit32.bxor(state, bit32.lshift(state, 13))
    state = bit32.bxor(state, bit32.rshift(state, 17))
    state = bit32.bxor(state, bit32.lshift(state, 5))
    local index = state % #alphabet + 1
    out[i] = string.sub(alphabet, index, index)
  end
  return table.concat(out)
end

function M.anonymize(torrent, salt)
  local seed = torrent.hash ~= "" and torrent.hash or torrent.name
  local nameLen = math.max(12, math.min(28, utf8.len(torrent.name) or 16))
  return seededString("name:" .. seed, salt, nameLen, NAME_CHARS)
end

-- ── Bar dots ─────────────────────────────────────────────────────────────────

-- kind: "solid", "ring" or "ring-dot"; size in logical px.
function M.dot(kind, color, opacity, size)
  size = size or 12
  local ringSize = math.floor(size * 0.9 + 0.5)
  if kind == "solid" then
    return ui.box({ width = ringSize, height = ringSize, radius = ringSize / 2, fill = color, opacity = opacity })
  end
  local stroke = math.max(1, size * 0.11)
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
    borderWidth = stroke,
    align = "center",
    justify = "center",
    opacity = opacity,
  }, children)
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
