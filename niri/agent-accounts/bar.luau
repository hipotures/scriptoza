--!nonstrict
-- Bar indicator: one gauge per shown account; the outer arc shows the used percentage of its
-- longest window and the inner pie that of its shortest, both filled clockwise. Accounts with stale data, errors or
-- disabled checks are dimmed. A pulsing yellow ring means the service cannot be
-- reached; a pulsing red ring means its health check fails.

local common = require("./common.luau")

local snapshot = noctalia.state.get("snapshot")
local config = common.loadConfig()
local dots = {}
local pulsing = false

local function buildDots()
  dots = {}
  pulsing = false
  if type(snapshot) ~= "table" or snapshot.error then
    table.insert(dots, { color = common.WAITING_COLOR, outer = 0, inner = 0 })
    pulsing = true
    return
  end
  if snapshot.health ~= "pass" then
    table.insert(dots, { color = common.ERROR_COLOR, outer = 0, inner = 0 })
    pulsing = true
    return
  end
  for _, profile in ipairs(common.visibleProfiles(snapshot.profiles, config)) do
    local outer, inner = common.windowsUsed(profile, config)
    table.insert(dots, {
      color = common.providerInfo(profile).color,
      outer = outer,
      inner = inner,
      dim = common.problem(profile) ~= nil,
    })
  end
  if #dots == 0 then
    table.insert(dots, { color = common.IDLE_COLOR, outer = 0, inner = 0 })
  end
end

local function render()
  local now = noctalia.nowMs()
  local children = table.create(#dots)
  for _, dot in ipairs(dots) do
    local opacity = dot.dim and 0.4 or 1
    if pulsing then
      opacity = 0.64 + 0.36 * math.cos((now % 3000) / 3000 * 2 * math.pi)
    end
    table.insert(children, common.usageDot(dot.color, dot.outer, dot.inner, opacity, 20))
  end
  local container = barWidget.isVertical() and ui.column or ui.row
  barWidget.render(container({ gap = 5, align = "center", justify = "center" }, children))
end

local function refresh()
  buildDots()
  noctalia.setUpdateInterval(pulsing and 100 or 1000)
  render()
end

noctalia.state.watch("snapshot", function(value)
  snapshot = value
  refresh()
end)

noctalia.state.watch("configRev", function()
  config = common.loadConfig()
  refresh()
end)

function update()
  if pulsing then
    render()
  end
end

function onClick()
  noctalia.layer.hide("preview")
  noctalia.togglePanel(common.PANEL_ID)
end

function onHover(entered)
  if entered then
    noctalia.layer.configure("preview", common.previewPlacement(barWidget.outputName(), config.previewBar))
    noctalia.layer.show("preview")
  else
    noctalia.layer.hide("preview")
  end
end

barWidget.clearTooltip()
refresh()
