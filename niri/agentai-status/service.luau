--!nonstrict
-- Headless service: runs the shared GJS status worker (event-driven Herdr
-- subscriptions plus usage limits) and republishes each JSON line as the
-- "snapshot" state value. Noctalia sends SIGTERM to the worker on reload or
-- disable; the worker also stops when its parent process goes away.

local common = require("./common.luau")

local worker = common.assetRoot() .. "/status-worker.js"

local function quote(value)
  return "'" .. string.gsub(value, "'", "'\\''") .. "'"
end

local function fail(message)
  noctalia.log("Agent Status: " .. message)
  noctalia.state.set("snapshot", {
    agents = {},
    errors = { { machine = "Herdr", message = message } },
    workerFailed = true,
  })
end

if not noctalia.fileExists(worker) then
  fail(`status worker not found at {worker}`)
elseif not noctalia.commandExists("gjs") then
  fail("GJS executable not found")
else
  -- Without exec, the shell reports the worker's exit status as a final line.
  local command = `gjs -m {quote(worker)} --detached-stdin; echo "\{\\"workerExit\\":$?}"`
  local started = noctalia.runStream(command, function(line)
    local data = noctalia.json.decode(line)
    if type(data) ~= "table" then
      return
    end
    if data.workerExit ~= nil then
      fail(`Status worker exited with status {data.workerExit}; reload the plugin to retry`)
      return
    end
    if type(data.agents) ~= "table" or type(data.errors) ~= "table" then
      fail("Invalid status worker response")
      return
    end
    noctalia.state.set("snapshot", data)
  end)
  if not started then
    fail("Cannot start the status worker")
  end
end
