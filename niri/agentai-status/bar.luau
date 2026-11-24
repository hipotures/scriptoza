--!nonstrict
-- Bar indicator: one dot per non-idle agent; a ring with a center dot when all
-- agents are idle; an empty ring with no agents; a pulsing yellow ring while
-- waiting for the local Herdr server. Blocked agents blink.

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
    return
  end
  if snapshot.waitingForServer or snapshot.workerFailed then
    table.insert(dots, { kind = "ring", color = common.WAITING_COLOR, state = "waiting" })
    mode = "waiting"
    return
  end
  local sorted = common.sortAgents(snapshot.agents or {})
  for _, agent in ipairs(sorted) do
    if agent.state ~= "idle" and common.STATES[agent.state] then
      table.insert(dots, { kind = "solid", color = common.STATES[agent.state].color, state = agent.state })
      if agent.state == "blocked" then
        mode = "blink"
      end
    end
  end
  if #dots == 0 then
    table.insert(dots, { kind = #sorted > 0 and "ring-dot" or "ring", color = common.IDLE_COLOR, state = "idle" })
  end
end

local function render()
  local now = noctalia.nowMs()
  local children = table.create(#dots)
  for _, dot in ipairs(dots) do
    local opacity = 1
    if dot.state == "waiting" then
      opacity = 0.64 + 0.36 * math.cos((now % 3000) / 3000 * 2 * math.pi)
    elseif dot.state == "blocked" and blinkDim then
      opacity = 0.27
    end
    table.insert(children, common.dot(dot.kind, dot.color, opacity, 12))
  end
  local container = barWidget.isVertical() and ui.column or ui.row
  barWidget.render(container({ gap = 5, align = "center", justify = "center" }, children))
end

local function refresh()
  buildDots()
  barWidget.setVisible(#dots > 0)
  noctalia.setUpdateInterval(mode == "steady" and 1000 or 100)
  render()
end

noctalia.state.watch("snapshot", function(value)
  snapshot = value
  refresh()
end)

function update()
  if mode == "blink" then
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

-- Hover shows the read-only preview layer under the bar; actions stay in the panel.
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
