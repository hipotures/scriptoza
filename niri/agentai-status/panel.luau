--!nonstrict
-- Agent list attached to the bar widget. Activating a row checks the target
-- with Herdr, focuses the pane in the existing Herdr client, then focuses the
-- client's terminal window in niri by its unique [herdr-client:<ID>] title.

local common = require("./common.luau")

local snapshot = noctalia.state.get("snapshot")
local density = common.loadDensity()
local hoveredKey = nil
local blinkDim = false
local busy = false

local function herdrPath()
  if noctalia.commandExists("herdr") then
    return "herdr"
  end
  return noctalia.expandPath("~/.local/bin/herdr")
end

-- Runs a Herdr command under GNU timeout and decodes its JSON stdout.
local function herdrJson(args, onDone)
  local argv = { "timeout", "--kill-after=1s", "8s", herdrPath() }
  for _, arg in ipairs(args) do
    table.insert(argv, arg)
  end
  local started = noctalia.runAsync(argv, function(result)
    if result.exitCode == 124 or result.timedOut then
      onDone(nil, "Herdr request timed out after 8 seconds")
    elseif result.exitCode ~= 0 then
      local message = noctalia.string.trim(result.stderr)
      onDone(nil, message ~= "" and string.sub(message, 1, 240) or "Herdr request failed")
    else
      local data = noctalia.json.decode(result.stdout)
      if data == nil then
        onDone(nil, "Herdr returned invalid JSON")
      else
        onDone(data, nil)
      end
    end
  end, 10000)
  if not started then
    onDone(nil, "Cannot start herdr")
  end
end

local function findClientWindow(token, onDone)
  local started = noctalia.runAsync({ "niri", "msg", "--json", "windows" }, function(result)
    local windows = result.exitCode == 0 and noctalia.json.decode(result.stdout)
    if type(windows) ~= "table" then
      onDone(nil, "niri did not return its window list")
      return
    end
    local matches = {}
    for _, window in ipairs(windows) do
      if type(window.title) == "string" and string.find(window.title, token, 1, true) then
        table.insert(matches, window)
      end
    end
    if #matches == 0 then
      onDone(nil, `Herdr client window '{token}' was not found`)
    elseif #matches > 1 then
      onDone(nil, `Multiple terminal windows match Herdr client '{token}'`)
    else
      onDone(matches[1], nil)
    end
  end, 5000)
  if not started then
    onDone(nil, "Cannot start niri msg")
  end
end

local function validIdentity(data)
  return type(data) == "table" and type(data.client_id) == "string" and data.client_id ~= ""
    and type(data.window_token) == "string" and data.window_token ~= ""
    and type(data.boot_id) == "string" and data.boot_id ~= ""
end

local function focusAgent(agent)
  if busy then
    return
  end
  local function failed(message)
    busy = false
    noctalia.notifyError(`Unable to focus {agent.location or "the selected agent"}`, message)
  end
  if type(agent.bootId) ~= "string" or agent.bootId == "" then
    failed("The selected agent has no valid Herdr server boot identity")
    return
  end
  if type(agent.serverId) ~= "string" or agent.serverId == "" or type(agent.paneId) ~= "string" or agent.paneId == "" then
    failed("The selected agent has no valid machine and pane identity")
    return
  end
  busy = true
  local target = `{agent.serverId}:{agent.paneId}`
  herdrJson({ "agent", "focus", target, "--check", "--expected-boot", agent.bootId }, function(checked, err)
    if err then
      return failed(err)
    end
    if not validIdentity(checked) then
      return failed("Herdr returned an invalid focus check response")
    end
    if checked.window_token ~= `[herdr-client:{checked.client_id}]` then
      return failed("Herdr returned a mismatched client window token")
    end
    if checked.boot_id ~= agent.bootId then
      return failed("Herdr focus check returned a different server boot")
    end
    findClientWindow(checked.window_token, function(window, windowErr)
      if windowErr then
        return failed(windowErr)
      end
      herdrJson({
        "agent", "focus", target, "--client", checked.client_id, "--expected-boot", checked.boot_id,
      }, function(reply, focusErr)
        if focusErr then
          return failed(focusErr)
        end
        if not validIdentity(reply) then
          return failed("Herdr returned an invalid focus acknowledgement")
        end
        if reply.client_id ~= checked.client_id or reply.window_token ~= checked.window_token
          or reply.boot_id ~= checked.boot_id then
          return failed("Herdr returned a mismatched focus acknowledgement")
        end
        findClientWindow(checked.window_token, function(current, currentErr)
          if currentErr then
            return failed(currentErr)
          end
          if current.id ~= window.id then
            return failed(`Herdr client window '{checked.window_token}' changed during focus`)
          end
          noctalia.runAsync({ "niri", "msg", "action", "focus-window", "--id", tostring(window.id) }, function(result)
            busy = false
            if result.exitCode ~= 0 then
              noctalia.notifyError(`Unable to focus {agent.location}`, noctalia.string.trim(result.stderr))
              return
            end
            panel.close()
          end, 5000)
        end)
      end)
    end)
  end)
end

local function agentRow(agent, profile)
  local info = common.STATES[agent.state] or common.STATES.unknown
  local key = agent.id or agent.location
  local dim = agent.state == "blocked" and blinkDim
  local text = { ui.label({
    text = agent.displayName or agent.location or "?",
    color = info.color,
    fontWeight = "bold",
    fontSize = profile.name,
    maxLines = 1,
    opacity = dim and 0.27 or 1,
  }) }
  if type(agent.sessionTitle) == "string" and agent.sessionTitle ~= "" then
    table.insert(text, ui.label({ text = agent.sessionTitle, fontSize = profile.sub, color = "on_surface_variant", maxLines = 1 }))
  end
  return ui.row({
    key = key,
    gap = profile.gap,
    paddingH = 8,
    paddingV = profile.padV,
    radius = 6,
    align = "center",
    fill = hoveredKey == key and "on_surface/0.08" or nil,
    tooltip = agent.location,
    onHover = function(state)
      hoveredKey = state == "true" and key or (hoveredKey == key and nil or hoveredKey)
      render()
    end,
    onClick = function()
      focusAgent(agent)
    end,
  }, {
    ui.image({ path = common.iconPath(agent.agentType), width = 16, height = 16, fit = "contain" }),
    ui.column({ flexGrow = 1, gap = 1 }, text),
    ui.glyph({ name = info.glyph, size = 16, color = info.color, opacity = dim and 0.27 or 1 }),
  })
end

local function hasBlocked()
  if type(snapshot) ~= "table" then
    return false
  end
  for _, agent in ipairs(snapshot.agents or {}) do
    if agent.state == "blocked" then
      return true
    end
  end
  return false
end

function render()
  local profile = common.PROFILES[density]
  local children = {}
  if type(snapshot) ~= "table" then
    table.insert(children, ui.label({ text = "Checking agents…", color = "on_surface_variant" }))
    table.insert(children, ui.spacer({ flexGrow = 1 }))
  elseif snapshot.waitingForServer and not snapshot.workerFailed then
    table.insert(children, ui.label({ text = "Waiting for the Herdr server to start", color = common.WAITING_COLOR }))
    table.insert(children, ui.spacer({ flexGrow = 1 }))
  else
    local agents = common.sortAgents(snapshot.agents or {})
    local rows = table.create(#agents)
    for _, agent in ipairs(agents) do
      table.insert(rows, agentRow(agent, profile))
    end
    if #rows == 0 then
      table.insert(rows, ui.label({ text = "No agents found", color = "on_surface_variant" }))
    end
    table.insert(children, ui.scroll({ flexGrow = 1, gap = 2, align = "stretch" }, rows))
    for _, err in ipairs(snapshot.errors or {}) do
      local message = snapshot.workerFailed and `{err.machine}: {err.message}` or `{err.machine}: unavailable`
      table.insert(children, ui.label({ text = message, color = common.WAITING_COLOR, maxLines = 3 }))
    end
  end

  if type(snapshot) == "table" and not (snapshot.waitingForServer and not snapshot.workerFailed) then
    table.insert(children, ui.separator({}))
    table.insert(children, ui.row({ gap = 8, align = "center" }, {
      ui.label({
        text = `Last update: {common.clock(snapshot.updatedAt)} · v{common.VERSION}`,
        fontSize = 12,
        color = "on_surface_variant",
        flexGrow = 1,
        maxLines = 1,
      }),
      ui.button({
        glyph = "settings",
        variant = "ghost",
        controlSize = "sm",
        tooltip = `Density: {density}`,
        onClick = function()
          local index = table.find(common.DENSITIES, density) or 1
          density = common.DENSITIES[index % #common.DENSITIES + 1]
          common.saveDensity(density)
          render()
        end,
      }),
    }))
  end

  panel.render(ui.column({ flexGrow = 1, gap = 8, align = "stretch" }, children))
end

noctalia.state.watch("snapshot", function(value)
  snapshot = value
  render()
end)

function update()
  local blink = hasBlocked()
  if blink or blinkDim then
    blinkDim = blink and not blinkDim
    render()
  end
end

function onOpen(_context)
  snapshot = noctalia.state.get("snapshot")
  density = common.loadDensity()
  panel.setWantsSecondTicks(true)
  render()
end

function onClose()
  panel.setWantsSecondTicks(false)
  hoveredKey = nil
end
