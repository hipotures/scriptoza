--!nonstrict
-- Headless poller: queries rTorrent through rtorrent_rpc.py and publishes one
-- "snapshot" state value that the bar widget and the panel render.

local common = require("./common.luau")

local helper = (noctalia.pluginDir() or ".") .. "/rtorrent_rpc.py"
local config = common.loadConfig()
local polling = false
local pendingPoll = false
local lastPollMs = 0
local modeCache = {}
local salt = math.random(0, 0x7ffffffe)

local function publish(data)
  data.name = config.name
  data.density = config.density
  data.sortBy = config.sortBy
  data.sortDir = config.sortDir
  data.anonymize = config.anonymize
  data.servers = config.servers
  data.activeServer = config.activeServer
  data.salt = salt
  noctalia.state.set("snapshot", data)
end

local function poll()
  if polling then
    pendingPoll = true
    return
  end
  polling = true
  pendingPoll = false
  lastPollMs = noctalia.nowMs()
  config = common.loadConfig()
  local host, port = config.host, config.port
  local key = `{host}:{port}`
  local timeout = math.max(2, math.min(10, config.pollSeconds))
  local argv = { "python3", "-I", helper, "--host", host, "--port", tostring(port), "--timeout", tostring(timeout) }
  if modeCache[key] then
    table.insert(argv, "--mode")
    table.insert(argv, modeCache[key])
  end
  local started = noctalia.runAsync(argv, function(result)
    polling = false
    local data, err = nil, nil
    if result.timedOut then
      err = `Timed out connecting to {host}:{port}`
    elseif result.exitCode ~= 0 then
      err = noctalia.string.trim(result.stderr) ~= "" and string.sub(noctalia.string.trim(result.stderr), 1, 240)
        or `rtorrent_rpc.py exited with {result.exitCode}`
    else
      data = noctalia.json.decode(result.stdout)
      if type(data) ~= "table" then
        err = "Invalid helper response"
      elseif data.error then
        err = tostring(data.error)
      end
    end
    -- A config switch during the request makes this result stale.
    if host ~= config.host or port ~= config.port then
      poll()
      return
    end
    if err then
      modeCache[key] = nil
      publish({ torrents = {}, error = err, host = host, port = port, updatedAt = noctalia.nowMs() })
    else
      modeCache[key] = data.mode
      local torrents = table.create(#data.rows)
      for index, row in ipairs(data.rows) do
        if type(row) == "table" then
          table.insert(torrents, common.normalizeTorrent(row, index - 1))
        end
      end
      publish({ torrents = torrents, host = host, port = port, updatedAt = noctalia.nowMs() })
    end
    if pendingPoll then
      poll()
    end
  end, (timeout + 2) * 1000)
  if not started then
    polling = false
    publish({ torrents = {}, error = "Cannot start python3", host = host, port = port, updatedAt = noctalia.nowMs() })
  end
end

noctalia.setUpdateInterval(250)

noctalia.state.watch("configRev", function()
  config = common.loadConfig()
  poll()
end)

function update()
  if not polling and noctalia.nowMs() - lastPollMs >= config.pollSeconds * 1000 - 50 then
    poll()
  end
end

function onIpc(event)
  if event == "refresh" then
    poll()
  end
end

poll()
