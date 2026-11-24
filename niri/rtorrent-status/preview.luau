--!nonstrict
-- Read-only hover preview shown under the bar while the pointer is over the
-- widget: torrent names, states, progress, rates and totals in a dense list.

local common = require("./common.luau")

local WIDTH = 640
local MAX_ROWS = 20
local NAME_SIZE = 12
local DETAIL_SIZE = 11

local snapshot = noctalia.state.get("snapshot")

local function line(name, detail, color)
  return ui.row({ gap = 12, align = "center" }, {
    ui.label({ text = name, color = color, fontWeight = "semibold", fontSize = NAME_SIZE, maxLines = 1, flexGrow = 1 }),
    ui.label({ text = detail, color = "on_surface_variant", fontSize = DETAIL_SIZE, maxLines = 1 }),
  })
end

local function rows()
  if type(snapshot) ~= "table" then
    return { line("rTorrent", "Checking…", "on_surface") }
  end
  local server = `{snapshot.host}:{snapshot.port}`
  if snapshot.error then
    return {
      line(server, "unavailable", common.WAITING_COLOR),
      ui.label({ text = snapshot.error, color = "on_surface_variant", fontSize = DETAIL_SIZE, maxLines = 3 }),
    }
  end
  local sorted = common.sortTorrents(snapshot.torrents or {}, snapshot.sortBy, snapshot.sortDir)
  local summary = common.summarize(sorted)
  local out = {}
  for index, torrent in ipairs(sorted) do
    if index > MAX_ROWS then
      table.insert(out, line(`… {#sorted - MAX_ROWS} more`, "", "on_surface_variant"))
      break
    end
    local name = snapshot.anonymize and common.anonymize(torrent, snapshot.salt or 0) or torrent.name
    local parts = { string.format("%.1f%%", torrent.percent) }
    if torrent.downRate > 0 then
      table.insert(parts, "↓ " .. common.formatRate(torrent.downRate))
    end
    if torrent.upRate > 0 then
      table.insert(parts, "↑ " .. common.formatRate(torrent.upRate))
    end
    if torrent.eta ~= "" then
      table.insert(parts, torrent.eta)
    end
    table.insert(parts, common.STATES[torrent.state].label)
    table.insert(out, line(name, table.concat(parts, " · "), common.STATES[torrent.state].color))
  end
  if #sorted == 0 then
    table.insert(out, line(server, "No torrents", "on_surface_variant"))
  end
  table.insert(out, ui.separator({}))
  table.insert(out, line(
    snapshot.name or "rtorrent",
    `↓ {common.formatRate(summary.totalDownRate)}  ↑ {common.formatRate(summary.totalUpRate)} · {common.clock(snapshot.updatedAt)}`,
    "on_surface"
  ))
  return out
end

local function render()
  layer.render(ui.column({
    width = WIDTH,
    gap = 4,
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

render()
