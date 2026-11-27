--!nonstrict
-- Bar indicator: a ring with the number of non-idle agents inside, both colored by the most urgent
-- state among them (blocked, working, done, unknown, offline); a grey ring with the number of idle agents when
-- none are running (empty without agents); an empty pulsing yellow ring while waiting for the local Herdr server. A blocked state blinks.

local common = require("./common.luau")

local snapshot = noctalia.state.get("snapshot")
local label = { text = "", color = common.IDLE_COLOR, state = "idle" }
local mode = "steady"
local blinkDim = false
local lastBlinkMs = 0

local function buildLabel()
  mode = "steady"
  label = { text = "", color = common.IDLE_COLOR, state = "idle" }
  if type(snapshot) ~= "table" then
    return
  end
  if snapshot.waitingForServer or snapshot.workerFailed then
    label = { text = "", color = common.WAITING_COLOR, state = "waiting" }
    mode = "waiting"
    return
  end
  local count = 0
  local idle = 0
  for _, agent in ipairs(common.sortAgents(snapshot.agents or {})) do
    if agent.state == "idle" then
      idle += 1
    end
    if agent.state ~= "idle" and common.STATES[agent.state] then
      if count == 0 then
        label = { color = common.STATES[agent.state].color, state = agent.state }
      end
      count += 1
    end
  end
  if count > 0 then
    label.text = tostring(count)
    if label.state == "blocked" then
      mode = "blink"
    end
  elseif idle > 0 then
    label.text = tostring(idle)
  end
end

local function render()
  local now = noctalia.nowMs()
  local opacity = 1
  if label.state == "waiting" then
    opacity = 0.64 + 0.36 * math.cos((now % 3000) / 3000 * 2 * math.pi)
  elseif label.state == "blocked" and blinkDim then
    opacity = 0.27
  end
  local size = 17
  local children = {}
  if label.text ~= "" then
    local fontSize = #label.text > 1 and 9 or 11
    children = { ui.label({ text = label.text, color = label.color, fontWeight = "bold", fontSize = fontSize, maxLines = 1 }) }
  end
  barWidget.render(ui.row({
    width = size,
    height = size,
    radius = size / 2,
    border = label.color,
    borderWidth = 1.6,
    align = "center",
    justify = "center",
    opacity = opacity,
  }, children))
end

local function refresh()
  buildLabel()
  barWidget.setVisible(type(snapshot) == "table")
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
