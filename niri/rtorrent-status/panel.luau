--!nonstrict
-- Torrent list attached to the bar widget, with an inline settings section
-- (server list, size, sort, anonymize) toggled by the footer gear.

local common = require("./common.luau")

local snapshot = noctalia.state.get("snapshot")
local settingsOpen = false
local serverEditor = nil
local editorText = ""
local editorRev = 0
local hoveredKey = nil
local blinkDim = false

local function currentServers()
  if type(snapshot) == "table" and type(snapshot.servers) == "table" and #snapshot.servers > 0 then
    return snapshot.servers, snapshot.activeServer or 0
  end
  local config = common.loadConfig()
  return config.servers, config.activeServer
end

local function hasErrors()
  if type(snapshot) ~= "table" then
    return false
  end
  for _, torrent in ipairs(snapshot.torrents or {}) do
    if torrent.state == "error" then
      return true
    end
  end
  return false
end

local function setServers(servers, active)
  serverEditor = nil
  common.saveServers(servers, active)
end

local function pill(text, active, onClick, tooltip)
  return ui.button({
    text = text,
    variant = active and "primary" or "ghost",
    controlSize = "sm",
    fontSize = 12,
    tooltip = tooltip,
    onClick = onClick,
  })
end

local function settingsRow(title, controls)
  local children = { ui.label({ text = title, flexGrow = 1, color = "on_surface" }) }
  for _, control in ipairs(controls) do
    table.insert(children, control)
  end
  return ui.row({ gap = 4, align = "center" }, children)
end

local function settingsSection()
  local servers, active = currentServers()
  local current = servers[active + 1] or servers[1]
  local spec = `{current.host}:{current.port}`
  local serverControls = {}
  if #servers > 1 then
    table.insert(serverControls, pill("‹", false, function()
      setServers(servers, (active - 1 + #servers) % #servers)
    end, "Previous server"))
  end
  table.insert(serverControls, pill(spec, serverEditor == "edit", function()
    serverEditor = serverEditor ~= "edit" and "edit" or nil
    editorText = spec
    editorRev += 1
    render()
  end, "Edit server"))
  if #servers > 1 then
    table.insert(serverControls, pill("›", false, function()
      setServers(servers, (active + 1) % #servers)
    end, "Next server"))
  end
  table.insert(serverControls, pill("+", serverEditor == "add", function()
    serverEditor = serverEditor ~= "add" and "add" or nil
    editorText = ""
    editorRev += 1
    render()
  end, "Add server"))
  if #servers > 1 then
    table.insert(serverControls, pill("✕", false, function()
      local next = {}
      for index, server in ipairs(servers) do
        if index ~= active + 1 then
          table.insert(next, server)
        end
      end
      setServers(next, math.min(active, #next - 1))
    end, "Remove server"))
  end

  local rows = { ui.separator({}), settingsRow("Server", serverControls) }

  if serverEditor then
    local function submit()
      local parsed = common.parseServerSpec(editorText)
      if not parsed then
        noctalia.notifyError("rTorrent Status", `Invalid server '{editorText}', expected host:port`)
        return
      end
      local next = table.clone(servers)
      local index = active
      if serverEditor == "add" then
        table.insert(next, parsed)
        index = #next - 1
      else
        next[active + 1] = parsed
      end
      setServers(next, index)
    end
    table.insert(rows, ui.row({ gap = 4, align = "center" }, {
      ui.input({
        key = `server-editor-{editorRev}`,
        value = editorText,
        placeholder = "host:port",
        controlSize = "sm",
        focus = true,
        flexGrow = 1,
        onChange = function(value)
          editorText = value
        end,
        onSubmit = function(value)
          editorText = value
          submit()
        end,
      }),
      pill("Save", true, submit),
      pill("✕", false, function()
        serverEditor = nil
        render()
      end, "Cancel"),
    }))
  end

  local density = snapshot and snapshot.density or "large"
  local sizeControls = {}
  for _, value in ipairs(common.DENSITIES) do
    table.insert(sizeControls, pill(common.DENSITY_LABELS[value], value == density, function()
      common.updateConfig({ density = value })
    end))
  end
  table.insert(rows, settingsRow("Size", sizeControls))

  local sortBy = snapshot and snapshot.sortBy or "state"
  local sortDir = snapshot and snapshot.sortDir or "asc"
  local fields = common.SORT_FIELDS
  local fieldIndex = math.max(1, common.indexOf(fields, sortBy))
  local function shift(step)
    local nextField = fields[(fieldIndex - 1 + step + #fields) % #fields + 1]
    common.updateConfig({ sortBy = nextField, sortDir = sortDir })
  end
  table.insert(rows, settingsRow("Sort", {
    pill("‹", false, function() shift(-1) end, "Previous sort field"),
    pill(common.SORT_LABELS[sortBy] or sortBy, true, function() shift(1) end, "Next sort field"),
    pill("›", false, function() shift(1) end, "Next sort field"),
    pill(sortDir == "desc" and "↓ Desc" or "↑ Asc", false, function()
      common.updateConfig({ sortBy = sortBy, sortDir = sortDir == "asc" and "desc" or "asc" })
    end, "Sort direction"),
  }))

  table.insert(rows, settingsRow("Anonymize", {
    ui.toggle({
      checked = snapshot ~= nil and snapshot.anonymize == true,
      onChange = function(value)
        common.updateConfig({ anonymize = value == "true" })
      end,
    }),
  }))
  return ui.column({ gap = 6 }, rows)
end

local function torrentRow(torrent, profile, anonymize, salt)
  local info = common.STATES[torrent.state]
  local name = anonymize and common.anonymize(torrent, salt) or torrent.name
  local key = torrent.hash ~= "" and torrent.hash or tostring(torrent.queueIndex)
  local dim = torrent.state == "error" and blinkDim
  return ui.row({
    key = key,
    gap = profile.gap,
    paddingH = 8,
    paddingV = profile.padV,
    radius = 6,
    align = "center",
    fill = hoveredKey == key and "on_surface/0.08" or nil,
    tooltip = common.tooltip(torrent),
    onHover = function(state)
      hoveredKey = state == "true" and key or (hoveredKey == key and nil or hoveredKey)
      render()
    end,
  }, {
    ui.column({ flexGrow = 1, gap = 1 }, {
      ui.label({ text = name, color = info.color, fontWeight = "bold", fontSize = profile.name, maxLines = 1, opacity = dim and 0.27 or 1 }),
      ui.label({ text = common.subtitle(torrent), color = "on_surface_variant", fontSize = profile.sub, maxLines = 1 }),
    }),
    ui.glyph({ name = info.glyph, size = 16, color = info.color, opacity = dim and 0.27 or 1 }),
  })
end

function render()
  local children = {}
  local profile = common.PROFILES[snapshot and snapshot.density or "large"] or common.PROFILES.large
  local summary = { totalDownRate = 0, totalUpRate = 0 }

  if type(snapshot) ~= "table" then
    table.insert(children, ui.label({ text = "Checking rTorrent…", color = "on_surface_variant" }))
    table.insert(children, ui.spacer({ flexGrow = 1 }))
  elseif snapshot.error then
    table.insert(children, ui.label({
      text = `{snapshot.host}:{snapshot.port}: {snapshot.error}`,
      color = common.WAITING_COLOR,
      maxLines = 3,
    }))
    table.insert(children, ui.spacer({ flexGrow = 1 }))
  else
    local sorted = common.sortTorrents(snapshot.torrents or {}, snapshot.sortBy, snapshot.sortDir)
    summary = common.summarize(sorted)
    local rows = table.create(#sorted)
    for _, torrent in ipairs(sorted) do
      table.insert(rows, torrentRow(torrent, profile, snapshot.anonymize, snapshot.salt or 0))
    end
    if #rows == 0 then
      table.insert(rows, ui.label({ text = "No torrents", color = "on_surface_variant" }))
    end
    table.insert(children, ui.scroll({ flexGrow = 1, gap = 2, align = "stretch" }, rows))
  end

  if settingsOpen then
    table.insert(children, settingsSection())
  end

  local time = common.clock(snapshot and snapshot.updatedAt)
  table.insert(children, ui.separator({}))
  table.insert(children, ui.row({ gap = 8, align = "center" }, {
    ui.label({
      text = `↓ {common.formatRate(summary.totalDownRate)}  ↑ {common.formatRate(summary.totalUpRate)} · {time} · v{common.VERSION}`,
      fontSize = 12,
      color = "on_surface_variant",
      flexGrow = 1,
      maxLines = 1,
    }),
    ui.button({
      glyph = "settings",
      variant = settingsOpen and "secondary" or "ghost",
      controlSize = "sm",
      tooltip = settingsOpen and "Close settings" or "Open settings",
      onClick = function()
        settingsOpen = not settingsOpen
        if not settingsOpen then
          serverEditor = nil
        end
        render()
      end,
    }),
  }))

  panel.render(ui.column({ flexGrow = 1, gap = 8, align = "stretch" }, children))
end

noctalia.state.watch("snapshot", function(value)
  snapshot = value
  render()
end)

function update()
  local blink = hasErrors()
  if blink or blinkDim then
    blinkDim = blink and not blinkDim
    render()
  end
end

function onOpen(_context)
  snapshot = noctalia.state.get("snapshot")
  panel.setWantsSecondTicks(true)
  render()
end

function onClose()
  panel.setWantsSecondTicks(false)
  settingsOpen = false
  serverEditor = nil
  hoveredKey = nil
end
