--!nonstrict
-- Bar indicator: one solid dot per non-paused torrent, a ring with a center dot
-- when everything is paused, an empty ring for an empty queue, and a slowly
-- pulsing yellow ring when the server is unreachable. Errors blink.

local common = require("./common.luau")

local snapshot = noctalia.state.get("snapshot")
local dots = {}
local mode = "steady"
local blinkDim = false
local lastBlinkMs = 0

local function buildDots()
  dots = {}
  mode = "steady"
  if type(snapshot) ~= "table" then
    table.insert(dots, { kind = "ring", color = common.IDLE_COLOR, state = "paused" })
    return
  end
  if snapshot.error then
    table.insert(dots, { kind = "ring", color = common.WAITING_COLOR, state = "waiting" })
    mode = "waiting"
    return
  end
  local sorted = common.sortTorrents(snapshot.torrents or {}, snapshot.sortBy, snapshot.sortDir)
  for _, torrent in ipairs(sorted) do
    if torrent.state ~= "paused" then
      table.insert(dots, { kind = "solid", color = common.STATES[torrent.state].color, state = torrent.state })
      if torrent.state == "error" then
        mode = "error"
      end
    end
  end
  if #dots == 0 then
    local kind = #sorted > 0 and "ring-dot" or "ring"
    table.insert(dots, { kind = kind, color = common.IDLE_COLOR, state = "paused" })
  end
end

local function render()
  local now = noctalia.nowMs()
  local children = table.create(#dots)
  for _, dot in ipairs(dots) do
    local opacity = 1
    if dot.state == "waiting" then
      local phase = (now % 3000) / 3000
      opacity = 0.64 + 0.36 * math.cos(phase * 2 * math.pi)
    elseif dot.state == "error" and blinkDim then
      opacity = 0.27
    end
    table.insert(children, common.dot(dot.kind, dot.color, opacity, 12))
  end
  local container = barWidget.isVertical() and ui.column or ui.row
  barWidget.render(container({ gap = 5, align = "center", justify = "center" }, children))
end

local MAX_ROWS = 15

-- Read-only hover summary; editing stays in the panel opened by a click.
local function tooltipRows()
  if type(snapshot) ~= "table" then
    return { { "rTorrent", "Checking…" } }
  end
  local server = `{snapshot.host}:{snapshot.port}`
  if snapshot.error then
    return { { server, "unavailable" }, { "Error", common.truncate(snapshot.error, 60) } }
  end
  local sorted = common.sortTorrents(snapshot.torrents or {}, snapshot.sortBy, snapshot.sortDir)
  local summary = common.summarize(sorted)
  local rows = {}
  for index, torrent in ipairs(sorted) do
    if index > MAX_ROWS then
      table.insert(rows, { "…", `{#sorted - MAX_ROWS} more` })
      break
    end
    local name = snapshot.anonymize and common.anonymize(torrent, snapshot.salt or 0) or torrent.name
    local parts = { common.STATES[torrent.state].label, string.format("%.1f%%", torrent.percent) }
    if torrent.downRate > 0 then
      table.insert(parts, "↓ " .. common.formatRate(torrent.downRate))
    end
    if torrent.upRate > 0 then
      table.insert(parts, "↑ " .. common.formatRate(torrent.upRate))
    end
    if torrent.eta ~= "" then
      table.insert(parts, torrent.eta)
    end
    table.insert(rows, { common.truncate(name, 40), table.concat(parts, " · ") })
  end
  if #sorted == 0 then
    table.insert(rows, { server, "No torrents" })
  end
  table.insert(rows, {
    "Total",
    `↓ {common.formatRate(summary.totalDownRate)}  ↑ {common.formatRate(summary.totalUpRate)} · {common.clock(snapshot.updatedAt)}`,
  })
  return rows
end

local function refresh()
  buildDots()
  if mode ~= "steady" then
    noctalia.setUpdateInterval(100)
  else
    noctalia.setUpdateInterval(1000)
  end
  barWidget.setTooltip(tooltipRows())
  render()
end

noctalia.state.watch("snapshot", function(value)
  snapshot = value
  refresh()
end)

function update()
  if mode == "error" then
    local now = noctalia.nowMs()
    if now - lastBlinkMs >= 600 then
      lastBlinkMs = now
      blinkDim = not blinkDim
      render()
    end
  elseif mode == "waiting" then
    render()
  end
end

refresh()
