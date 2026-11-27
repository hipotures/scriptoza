--!nonstrict
-- Account list attached to the bar widget. It is read-only towards the Agent
-- Accounts service; the footer gear opens local settings (connection, free
-- accounts, account order, Antigravity quota group).

local common = require("./common.luau")

local snapshot = noctalia.state.get("snapshot")
local config = common.loadConfig()
local settingsOpen = false
local serverEditor = nil
local editorText = ""
local editorRev = 0

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
  local children = { ui.label({ text = title, flexGrow = 1, color = "on_surface", maxLines = 1 }) }
  for _, control in ipairs(controls) do
    table.insert(children, control)
  end
  return ui.row({ gap = 4, align = "center" }, children)
end

local function setServers(servers, active)
  serverEditor = nil
  common.updateConfig({ servers = servers, activeServer = active })
end

local function serverSection()
  local servers, active = config.servers, config.activeServer
  local controls = {}
  if #servers > 1 then
    table.insert(controls, pill("‹", false, function()
      setServers(servers, (active - 1 + #servers) % #servers)
    end, "Previous address"))
  end
  table.insert(controls, pill(config.url, serverEditor == "edit", function()
    serverEditor = serverEditor ~= "edit" and "edit" or nil
    editorText = config.url
    editorRev += 1
    render()
  end, "Edit address"))
  if #servers > 1 then
    table.insert(controls, pill("›", false, function()
      setServers(servers, (active + 1) % #servers)
    end, "Next address"))
  end
  table.insert(controls, pill("+", serverEditor == "add", function()
    serverEditor = serverEditor ~= "add" and "add" or nil
    editorText = ""
    editorRev += 1
    render()
  end, "Add address"))
  if #servers > 1 then
    table.insert(controls, pill("✕", false, function()
      local next = {}
      for index, server in ipairs(servers) do
        if index ~= active + 1 then
          table.insert(next, server)
        end
      end
      setServers(next, math.min(active, #next - 1))
    end, "Remove address"))
  end
  local rows = { ui.label({ text = "Connection", color = "on_surface" }), ui.row({ gap = 4, align = "center" }, controls) }

  if serverEditor then
    local function submit()
      local parsed = common.normalizeServer(editorText)
      if not parsed then
        noctalia.notifyError("Agent Accounts", `Invalid address '{editorText}'`)
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
        placeholder = "http://host:8080/",
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
  return rows
end

local function accountSection()
  local rows = {}
  local all = common.visibleProfiles(type(snapshot) == "table" and snapshot.profiles or {}, {
    showFree = true,
    order = config.order,
    groups = config.groups,
  })
  if #all == 0 then
    return rows
  end
  local ids = table.create(#all)
  for _, profile in ipairs(all) do
    table.insert(ids, profile.id)
  end
  local function move(index, step)
    local target = index + step
    if target < 1 or target > #ids then
      return
    end
    ids[index], ids[target] = ids[target], ids[index]
    common.updateConfig({ order = ids })
  end
  table.insert(rows, ui.label({ text = "Account order", color = "on_surface" }))
  for index, profile in ipairs(all) do
    local info = common.providerInfo(profile)
    local controls = {
      pill("▲", false, function() move(index, -1) end, "Move up"),
      pill("▼", false, function() move(index, 1) end, "Move down"),
      ui.label({ text = info.label, color = info.color, fontWeight = "bold", fontSize = 11 }),
      ui.label({
        text = common.accountName(profile),
        fontSize = 12,
        color = common.isFree(profile) and not config.showFree and "on_surface_variant" or "on_surface",
        maxLines = 1,
        flexGrow = 1,
      }),
    }
    local groups = common.groupsOf(profile)
    if #groups > 1 then
      local selected = common.selectedGroup(profile, config)
      for _, group in ipairs(groups) do
        table.insert(controls, pill(common.groupLabel(group), group == selected, function()
          local next = table.clone(config.groups)
          next[profile.id] = group
          common.updateConfig({ groups = next })
        end, `Show the {group} quota`))
      end
    end
    table.insert(rows, ui.row({ gap = 4, align = "center" }, controls))
  end
  return rows
end

local function settingsSection()
  local rows = { ui.separator({}) }
  for _, row in ipairs(serverSection()) do
    table.insert(rows, row)
  end
  table.insert(rows, settingsRow("Show free accounts", {
    ui.toggle({
      checked = config.showFree,
      onChange = function(value)
        common.updateConfig({ showFree = value == "true" })
      end,
    }),
  }))
  local barControls = {
    pill("Auto", config.previewBar == "auto", function()
      common.updateConfig({ previewBar = "auto" })
    end, `Bar holding the widget ({common.barPosition("auto")})`),
  }
  local bars = noctalia.getSetting("bar.order")
  if type(bars) == "table" then
    for _, name in ipairs(bars) do
      local position = noctalia.getSetting(`bar.{name}.position`)
      table.insert(barControls, pill(`{name} ({position or "?"})`, config.previewBar == name, function()
        common.updateConfig({ previewBar = name })
      end, "Show the hover preview at this bar"))
    end
  end
  table.insert(rows, settingsRow("Preview bar", barControls))
  for _, row in ipairs(accountSection()) do
    table.insert(rows, row)
  end
  return ui.column({ gap = 6 }, rows)
end

local function limitRows(profile, color)
  local rows = {}
  for _, limit in ipairs(common.limitsOf(profile, config)) do
    local used = math.max(0, math.min(100, tonumber(limit.used_percent) or 0))
    local reset = limit.resets_at and `Resets {common.dateTime(limit.resets_at)}` or "Not started"
    table.insert(rows, ui.column({ gap = 3 }, {
      ui.row({ gap = 8, align = "center" }, {
        ui.label({ text = common.windowLabel(limit.window_minutes), color = "on_surface", fontWeight = "semibold", fontSize = 13, flexGrow = 1 }),
        ui.label({
          text = `{common.percent(used)} used · {common.percent(100 - used)} left`,
          color = limit.exhausted == true and common.ERROR_COLOR or "on_surface_variant",
          fontSize = 12,
        }),
      }),
      common.usageBar(color, used, 6),
      ui.label({ text = reset, color = "on_surface_variant", fontSize = 11 }),
    }))
  end
  if #rows == 0 then
    table.insert(rows, ui.label({ text = "No usage data", color = "on_surface_variant", fontSize = 12 }))
  end
  return rows
end

local function accountCard(profile, now)
  local info = common.providerInfo(profile)
  local account = type(profile.account) == "table" and profile.account or {}
  local group = common.selectedGroup(profile, config)
  local kind = info.label
  if group then
    kind ..= ` · {string.upper(common.groupLabel(group))}`
  end
  local subtitle = {
    ui.label({ text = common.accountName(profile), color = "on_surface", fontWeight = "bold", fontSize = 13, maxLines = 1 }),
  }
  if type(account.plan) == "string" and account.plan ~= "" then
    table.insert(subtitle, ui.label({ text = `· {account.plan}`, color = "on_surface_variant", fontSize = 12, maxLines = 1 }))
  end
  local children = {
    ui.row({ gap = 8, align = "center" }, {
      ui.label({ text = kind, color = info.color, fontWeight = "bold", fontSize = 12, flexGrow = 1, maxLines = 1 }),
      ui.label({ text = common.periodLeft(profile, now) or "", color = "on_surface_variant", fontSize = 12 }),
    }),
    ui.row({ gap = 4, align = "center" }, subtitle),
  }
  local problem = common.problem(profile)
  if problem then
    table.insert(children, ui.label({ text = problem, color = common.WAITING_COLOR, fontSize = 12, maxLines = 3 }))
  end
  for _, row in ipairs(limitRows(profile, info.color)) do
    table.insert(children, row)
  end
  table.insert(children, ui.label({
    text = `Last successful check {common.dateTime(profile.last_success)}`,
    color = "on_surface_variant",
    fontSize = 11,
  }))
  return ui.column({
    key = profile.id,
    gap = 6,
    padding = 10,
    radius = 8,
    fill = "on_surface/0.04",
    opacity = profile.enabled == false and 0.6 or 1,
  }, children)
end

local function statusText()
  if type(snapshot) ~= "table" then
    return "Connecting…", "on_surface_variant"
  elseif snapshot.error then
    return "Unreachable", common.WAITING_COLOR
  elseif snapshot.health ~= "pass" then
    local checks = #(snapshot.failedChecks or {}) > 0 and ` ({table.concat(snapshot.failedChecks, ", ")})` or ""
    return `Health: {snapshot.health}{checks}`, common.ERROR_COLOR
  end
  return "Service healthy", "#57e389"
end

function render()
  local children = {}
  if type(snapshot) ~= "table" then
    table.insert(children, ui.label({ text = "Checking Agent Accounts…", color = "on_surface_variant" }))
    table.insert(children, ui.spacer({ flexGrow = 1 }))
  elseif snapshot.error then
    table.insert(children, ui.label({ text = `{snapshot.url}: {snapshot.error}`, color = common.WAITING_COLOR, maxLines = 4 }))
    table.insert(children, ui.spacer({ flexGrow = 1 }))
  else
    local now = os.time()
    local cards = {}
    for _, profile in ipairs(common.visibleProfiles(snapshot.profiles, config)) do
      table.insert(cards, accountCard(profile, now))
    end
    if #cards == 0 then
      table.insert(cards, ui.label({ text = "No accounts to show", color = "on_surface_variant" }))
    end
    table.insert(children, ui.scroll({ flexGrow = 1, gap = 8, align = "stretch" }, cards))
  end

  if settingsOpen then
    table.insert(children, settingsSection())
  end

  local status, statusColor = statusText()
  table.insert(children, ui.separator({}))
  table.insert(children, ui.row({ gap = 8, align = "center" }, {
    ui.box({ width = 8, height = 8, radius = 4, fill = statusColor }),
    ui.label({
      text = `{status} · {common.clock(snapshot and snapshot.updatedAt)} · v{common.VERSION}`,
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

noctalia.state.watch("configRev", function()
  config = common.loadConfig()
  render()
end)

function onOpen(_context)
  snapshot = noctalia.state.get("snapshot")
  config = common.loadConfig()
  render()
end

function onClose()
  settingsOpen = false
  serverEditor = nil
end
