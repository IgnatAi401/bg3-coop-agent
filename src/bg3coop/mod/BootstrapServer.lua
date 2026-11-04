-- BG3 Co-op Memory: remembers where the party has been, inside the save itself.
--
-- Loaded by the Script Extender at startup, so it records whether or not an agent is
-- connected, and the record goes back with every save load. Every 2 s it marks the
-- 10 m cells around each party member, per map, in a persistent mod variable:
--   Trail = { [region] = { ["x,z"] = 1, ... } }
-- The bridge's injected script only reads it (see server.lua, Exploration).
--
-- It also keeps, for the injected script to read and write:
--   Notes    = the agent's notes about the story (goals, promises, places), which go
--              back with the save like everything else in it
--   Campaign = which playthrough this save belongs to, the same in all its saves

VERSION = 2
local CELL = 10

for _, name in ipairs({ "Trail", "Notes", "Campaign" }) do
    Ext.Vars.RegisterModVariable(ModuleUUID, name, {
        Server = true, Client = false, SyncToClient = false, Persistent = true, WriteableOnServer = true,
    })
end

-- A new game, still in the prologue, gets a fresh id. A save from before this version
-- has none: it gets one from the main character, so all saves of that playthrough agree
-- (the injected script falls back to the same id when this mod is missing).
function EnsureCampaign()
    local vars = Ext.Vars.GetModVariables(ModuleUUID)
    if vars.Campaign then return end
    local rows = Osi.DB_Avatars:Get(nil)
    local avatar = rows and rows[1] and rows[1][1]
    if not avatar then return end
    local fresh = vars.Trail == nil and Osi.GetRegion(avatar) == "TUT_Avernus_C"
    vars.Campaign = fresh and Ext.Utils.GenerateGuid()
        or "avatar-" .. tostring(avatar):match("(%x+%-%x+%-%x+%-%x+%-%x+)$")
end

local cache -- this Lua state's copy; the mod variable is written back only when it grows

function Note()
    local rows = Osi.DB_PartyMembers:Get(nil)
    if not rows then return end
    local vars = Ext.Vars.GetModVariables(ModuleUUID)
    cache = cache or vars.Trail or {}
    local grew = false
    for _, row in ipairs(rows) do
        local u = row[1]
        local x, _, z = Osi.GetPosition(u)
        local lv = Osi.GetRegion(u)
        if x and lv and lv ~= "" then
            local cells = cache[lv] or {}
            cache[lv] = cells
            local cx, cz = math.floor(x / CELL), math.floor(z / CELL)
            for dx = -1, 1 do
                for dz = -1, 1 do
                    local key = (cx + dx) .. "," .. (cz + dz)
                    if not cells[key] then cells[key] = 1; grew = true end
                end
            end
        end
    end
    if grew then vars.Trail = cache end
end

-- A loaded save brings its own record.
Ext.Events.SessionLoaded:Subscribe(function() cache = nil end)

local last = 0
Ext.Events.Tick:Subscribe(function()
    local t = Ext.Utils.MonotonicTime()
    if t - last < 2000 then return end
    last = t
    if tostring(Ext.Utils.GetGameState()) ~= "Running" then return end
    pcall(EnsureCampaign)
    pcall(Note)
end)
