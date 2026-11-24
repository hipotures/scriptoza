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

local function refresh()
  buildDots()
  if mode ~= "steady" then
    noctalia.setUpdateInterval(100)
  else
    noctalia.setUpdateInterval(1000)
  end
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

function onClick()
  noctalia.layer.hide("preview")
  noctalia.togglePanel(common.PANEL_ID)
end

-- Hover shows the read-only preview layer under the bar; editing stays in the panel.
function onHover(entered)
  if entered then
    noctalia.layer.configure("preview", common.previewPlacement(barWidget.outputName()))
    noctalia.layer.show("preview")
  else
    noctalia.layer.hide("preview")
  end
end

barWidget.clearTooltip()
refresh()
