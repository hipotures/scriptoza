--!nonstrict
-- Read-only hover preview shown next to the bar while the pointer is over the
-- widget: one compact block per shown account and the service status.

local common = require("./common.luau")

local WIDTH = 640
local NAME_SIZE = 12
local DETAIL_SIZE = 11

local snapshot = noctalia.state.get("snapshot")
local config = common.loadConfig()

local function line(children)
  return ui.row({ gap = 8, align = "center" }, children)
end

local function message(text, color)
  return line({ ui.label({ text = text, color = color, fontSize = NAME_SIZE, maxLines = 2, flexGrow = 1 }) })
end

local function resetShort(seconds, now)
  if not seconds then
    return "not started"
  end
  if seconds - now < 86400 then
    return os.date("%H:%M", math.floor(seconds))
  end
  return os.date("%m-%d %H:%M", math.floor(seconds))
end

local function accountBlock(profile, now)
  local info = common.providerInfo(profile)
  local account = type(profile.account) == "table" and profile.account or {}
  local title = common.accountName(profile)
  if type(account.plan) == "string" and account.plan ~= "" then
    title ..= ` · {account.plan}`
  end
  local group = common.selectedGroup(profile, config)
  if group then
    title ..= ` · {common.groupLabel(group)}`
  end
  local problem = common.problem(profile)
  local right = problem or common.periodLeft(profile, now) or ""
  local header = line({
    ui.label({ text = info.label, color = info.color, fontWeight = "bold", fontSize = NAME_SIZE }),
    ui.label({ text = title, color = "on_surface", fontWeight = "semibold", fontSize = NAME_SIZE, maxLines = 1, flexGrow = 1 }),
    ui.label({ text = right, color = problem and common.WAITING_COLOR or "on_surface_variant", fontSize = DETAIL_SIZE, maxLines = 1 }),
  })
  local windows = {}
  for _, limit in ipairs(common.limitsOf(profile, config)) do
    local used = tonumber(limit.used_percent) or 0
    table.insert(windows, ui.row({ gap = 6, align = "center", flexGrow = 1 }, {
      ui.label({ text = common.shortWindow(limit.window_minutes), color = "on_surface_variant", fontSize = DETAIL_SIZE }),
      ui.column({ width = 90 }, { common.usageBar(info.color, used, 5) }),
      ui.label({
        text = `{common.percent(used)} used · {resetShort(limit.resets_at, now)}`,
        color = "on_surface_variant",
        fontSize = DETAIL_SIZE,
        maxLines = 1,
      }),
    }))
  end
  if #windows == 0 then
    table.insert(windows, ui.label({ text = "No usage data", color = "on_surface_variant", fontSize = DETAIL_SIZE }))
  end
  return ui.column({ gap = 2, opacity = problem and 0.7 or 1 }, { header, line(windows) })
end

local function rows()
  if type(snapshot) ~= "table" then
    return { message("Checking Agent Accounts…", "on_surface_variant") }
  end
  if snapshot.error then
    return { message(`{snapshot.url}: {snapshot.error}`, common.WAITING_COLOR) }
  end
  local out = {}
  if snapshot.health ~= "pass" then
    local checks = #(snapshot.failedChecks or {}) > 0 and ` ({table.concat(snapshot.failedChecks, ", ")})` or ""
    table.insert(out, message(`Service health: {snapshot.health}{checks}`, common.ERROR_COLOR))
  end
  local now = os.time()
  local profiles = common.visibleProfiles(snapshot.profiles, config)
  for index, profile in ipairs(profiles) do
    if index > 1 then
      table.insert(out, ui.separator({}))
    end
    table.insert(out, accountBlock(profile, now))
  end
  if #profiles == 0 then
    table.insert(out, message("No accounts to show", "on_surface_variant"))
  end
  return out
end

local function render()
  layer.render(ui.column({
    width = WIDTH,
    gap = 6,
    padding = 10,
    radius = 10,
    fill = "surface",
    border = "outline_variant",
    borderWidth = 1,
    align = "stretch",
  }, rows()))
end

noctalia.state.watch("snapshot", function(value)
  snapshot = value
  render()
end)

noctalia.state.watch("configRev", function()
  config = common.loadConfig()
  render()
end)

render()
