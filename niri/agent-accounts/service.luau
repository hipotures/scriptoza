--!nonstrict
-- Headless poller: reads the Agent Accounts service with GET requests only
-- (/health/ready, then /api/v1/profiles) and publishes one "snapshot" state
-- value. It never triggers checks, usage windows or other provider calls.

local common = require("./common.luau")

local config = common.loadConfig()
local polling = false
local pendingPoll = false
local lastPollMs = 0
local HTTP_STATUS = "\n__HTTP_STATUS__:"

local function publish(data)
  data.url = config.url
  data.servers = config.servers
  data.activeServer = config.activeServer
  data.updatedAt = noctalia.nowMs()
  noctalia.state.set("snapshot", data)
end

-- GET a URL with curl; onDone(status, body, err).
local function get(url, timeout, onDone)
  local argv = {
    "curl", "--silent", "--show-error", "--max-time", tostring(timeout), "--proto", "=http,https",
    "--header", "Accept: application/json", "--write-out", HTTP_STATUS .. "%{http_code}", url,
  }
  local started = noctalia.runAsync(argv, function(result)
    if result.timedOut then
      onDone(nil, nil, "Request timed out")
      return
    end
    local stdout = result.stdout or ""
    local body, status = string.match(stdout, "^(.*)\n__HTTP_STATUS__:(%d+)$")
    if result.exitCode ~= 0 or not status then
      local message = noctalia.string.trim(result.stderr or "")
      onDone(nil, nil, message ~= "" and string.sub(message, 1, 240) or `curl exited with {result.exitCode}`)
      return
    end
    onDone(tonumber(status), body, nil)
  end, (timeout + 2) * 1000)
  if not started then
    onDone(nil, nil, "Cannot start curl")
  end
end

local function healthSummary(status, body)
  local data = body and noctalia.json.decode(body)
  if type(data) == "table" and type(data.status) == "string" then
    local failed = {}
    if type(data.checks) == "table" then
      for name, entries in pairs(data.checks) do
        for _, entry in ipairs(entries) do
          if type(entry) == "table" and entry.status ~= "pass" then
            table.insert(failed, name)
          end
        end
      end
    end
    table.sort(failed)
    return data.status, failed
  end
  return status == 200 and "pass" or "fail", {}
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
  local url = config.url
  local timeout = math.max(3, math.min(15, config.pollSeconds // 2))

  local function finish(data)
    polling = false
    -- A server switch during the request makes this result stale.
    if url ~= config.url then
      poll()
      return
    end
    publish(data)
    if pendingPoll then
      poll()
    end
  end

  get(url .. "health/ready", timeout, function(status, body, err)
    if err then
      finish({ error = err })
      return
    end
    if status == 401 or status == 403 then
      finish({ error = `HTTP {status}: the address requires authentication` })
      return
    end
    local health, failedChecks = healthSummary(status, body)
    get(url .. "api/v1/profiles", timeout, function(pStatus, pBody, pErr)
      local data = { health = health, failedChecks = failedChecks }
      if pErr then
        data.error = pErr
      elseif pStatus ~= 200 then
        data.error = `HTTP {pStatus} from /api/v1/profiles`
      else
        local profiles = noctalia.json.decode(pBody)
        if type(profiles) ~= "table" then
          data.error = "Invalid /api/v1/profiles response"
        else
          data.profiles = profiles
        end
      end
      finish(data)
    end)
  end)
end

noctalia.setUpdateInterval(1000)

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
