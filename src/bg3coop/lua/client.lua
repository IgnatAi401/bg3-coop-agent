-- BG3COOP client side: reads and answers the dialogue on screen. Injected into
-- the client Lua state, like server.lua. Noesis access is read-mostly and every
-- read is wrapped in pcall: a bad UI read must never take the game down.
--
-- Noesis objects throw when indexed with a name they do not have, and
-- collections only take numeric indexes (`#coll`, `coll[1]`; `.Count` throws),
-- so every lookup happens inside a closure passed to pcall.
--
-- Dialogue view models: <Dialogue widget DC>.Data.Dialogues, one per running
-- dialogue, keyed by DialogInstanceID (the server's DialogState.DialogId).
--   BodyText          current line
--   History.Items     spoken lines, "Speaker: text"
--   AvailableSpeakers [1] is the character who answers
--   Answers           BodyText, Enabled, AnswerTags
-- Answering: <DC>.SelectAnswerCommand:Execute(answer view model).

BG3COOP_C = BG3COOP_C or {}
local C = BG3COOP_C
C.VERSION = 26
C.ops = {}

local function get(f)
    local ok, v = pcall(f)
    if ok then return v end
    return nil
end

local function items(coll)
    local out = {}
    local n = coll and get(function() return #coll end) or 0
    for i = 1, n do
        local v = get(function() return coll[i] end)
        if v ~= nil then out[#out + 1] = v end
    end
    return out
end

local function widgetDC()
    local kids = get(function() return Ext.UI.GetRoot():Find("ContentRoot").Children end)
    for _, w in ipairs(items(kids)) do
        if get(function() return w.Name end) == "Dialogue" then
            return get(function() return w.DataContext end)
        end
    end
    return nil
end

local function clean(s)
    if type(s) ~= "string" then return nil end
    s = s:gsub("<[^>]->", ""):gsub("%s+", " "):gsub("^%s+", ""):gsub("%s+$", "")
    if s == "" then return nil end
    return s
end

-- The dialogue with this instance id, or the one the selected character is in.
local function findDialogue(dc, instance)
    instance = tonumber(instance)
    local shown
    for _, d in ipairs(items(get(function() return dc.Data.Dialogues end))) do
        local id = get(function() return d.DialogInstanceID end)
        if instance and id == instance then return d end
        if not shown and get(function() return d.ShowAnswers end) then shown = d end
    end
    if instance then return nil end
    return get(function() return dc.CurrentPlayer.SelectedCharacter.PlayerCharacterProperties.ActiveDialogue end)
        or shown
end

-- Some tags come as a translated-string handle (hfd00683fg1522g...), which the
-- game's text table turns into the shown word ("Investigation" / "调查").
local function translated(s)
    if not s:lower():match("^h%x+g%x+g%x+g%x+g%x+$") then return s end
    local ok, v = pcall(Ext.Loca.GetTranslatedString, s:lower())
    if ok and type(v) == "string" and v ~= "" then return v end
    return s
end

local function tagText(t)
    for _, k in ipairs({ "Text", "Name", "Tag", "DisplayName" }) do
        local v = get(function() return t[k] end)
        if type(v) == "string" and v ~= "" then return translated(v) end
    end
    return nil
end

local function answerList(d)
    local out = {}
    for _, vm in ipairs(items(get(function() return d.Answers end))) do
        local text = clean(get(function() return vm.BodyText end))
        if text then
            local tags = {}
            for _, t in ipairs(items(get(function() return vm.AnswerTags end))) do
                local s = clean(tagText(t))
                if s then tags[#tags + 1] = s:upper() end
            end
            if #tags > 0 then text = "[" .. table.concat(tags, "][") .. "] " .. text end
            out[#out + 1] = { n = #out + 1, text = text,
                disabled = (get(function() return vm.Enabled end) == false) or nil, vm = vm }
        end
    end
    return out
end

-- Last spoken line, split into speaker and text.
local function lastLine(d)
    local hist = items(get(function() return d.History.Items end))
    local last = hist[#hist]
    local raw = clean(last and get(function() return last.BodyText end)) or clean(get(function() return d.BodyText end))
    if not raw then return nil, nil end
    -- byte-wise patterns cannot hold the full-width colon, so look for both literally
    for _, sep in ipairs({ ":", "：" }) do
        local at = raw:find(sep, 1, true)
        if at and at > 1 and at <= 60 then
            local text = raw:sub(at + #sep):gsub("^%s+", "")
            if text ~= "" then return raw:sub(1, at - 1), text end
        end
    end
    return nil, raw
end

local function answerer(d)
    local first = items(get(function() return d.AvailableSpeakers end))[1]
    return first and get(function() return first.EntityUUID end)
end

-- Every spoken line, recorded from the tick handler, so lines the human clicks past (or a
-- one-line remark that ends at once) are not lost between two dialogue reads.
-- C.said = { {inst=, text="Speaker: line"}... } (unread).
-- C.saidDlg[inst] = { n = History items recorded, lines = { [key] = {entry=, named=, hist=} } }:
-- every line of that dialogue so far. The same line comes from BodyText (often without
-- "Speaker: ") and from History (with it), not always right after each other, so a line is
-- recorded once and the copy that names the speaker is kept. Two History items with the
-- same text are said twice and both count.
-- C.chosen[inst] = { key=, as= }: the answer the agent picked. History names the human's
-- character as its speaker; the line is shown as the agent's.
local SAID_EVERY_MS = 30
local SAID_KEEP = 200
C.said = C.said or {}
C.saidDlg = C.saidDlg or {}
C.chosen = C.chosen or {}
C.saidLast, C.saidSeen = nil, nil -- the state of client v22 and older

-- The line without its "Speaker: " part: History has it, BodyText often does not. A line
-- may hold a colon of its own ("the burdens: grief, anger..."), so outside History the
-- part before it is a speaker only when it is one of `speakers` (seen in History).
local function bare(raw, speakers)
    for _, sep in ipairs({ ":", "：" }) do
        local at = raw:find(sep, 1, true)
        if at and at > 1 and at <= 60 and (not speakers or speakers[raw:sub(1, at - 1)]) then
            return (raw:sub(at + #sep):gsub("^%s+", "")), true, raw:sub(1, at - 1)
        end
    end
    return raw, false
end

-- What two copies of a line have in common: no spacing or quotes around it.
local QUOTES = { '"', "'", "“", "”", "「", "」", "『", "』" }
local function lineKey(text)
    local s = text:gsub("%s+", " ")
    local again = true
    while again do
        again = false
        s = s:gsub("^ ", ""):gsub(" $", "")
        for _, q in ipairs(QUOTES) do
            if s:sub(1, #q) == q then s = s:sub(#q + 1); again = true end
            if #s >= #q and s:sub(-#q) == q then s = s:sub(1, -#q - 1); again = true end
        end
    end
    return s
end

local function record(inst, raw, fromHistory)
    raw = clean(raw)
    if not raw then return end
    local dlg = C.saidDlg[inst]
    if not dlg then dlg = { n = 0, lines = {} }; C.saidDlg[inst] = dlg end
    dlg.speakers = dlg.speakers or {} -- a table kept from client v23
    local text, named, who = bare(raw, not fromHistory and dlg.speakers or nil)
    if who and fromHistory then dlg.speakers[who] = true end
    local key = lineKey(text)
    local mine = C.chosen[inst]
    if mine and mine.key == key and mine.as then
        raw, named = mine.as .. ": " .. text, true
        if fromHistory then C.chosen[inst] = nil end
    end
    local seen = dlg.lines[key]
    if seen and not (fromHistory and seen.hist) then
        -- the same line again; keep the copy that names the speaker
        if named and not seen.named then seen.entry.text, seen.named = raw, true end
        seen.hist = seen.hist or fromHistory
        return
    end
    local entry = { inst = inst, text = raw }
    dlg.lines[key] = { entry = entry, named = named, hist = fromHistory }
    C.said[#C.said + 1] = entry
    while #C.said > SAID_KEEP do table.remove(C.said, 1) end
end

function C.recordDialogue()
    local now = Ext.Utils.MonotonicTime()
    if C.saidAt and now - C.saidAt < SAID_EVERY_MS then return end
    C.saidAt = now
    local dc = widgetDC()
    if not dc then return end
    local live = {}
    for _, d in ipairs(items(get(function() return dc.Data.Dialogues end))) do
        local inst = get(function() return d.DialogInstanceID end) or 0
        live[inst] = true
        local hist = items(get(function() return d.History.Items end))
        local dlg = C.saidDlg[inst]
        for i = (dlg and dlg.n or 0) + 1, #hist do
            record(inst, get(function() return hist[i].BodyText end), true)
        end
        if C.saidDlg[inst] then C.saidDlg[inst].n = #hist end
        record(inst, get(function() return d.BodyText end), false)
    end
    for inst in pairs(C.saidDlg) do
        if not live[inst] then C.saidDlg[inst] = nil end
    end
    for inst in pairs(C.chosen) do
        if not live[inst] then C.chosen[inst] = nil end
    end
end

-- Unread lines (of one dialogue, or all), oldest first; they count as read.
local function takeSaid(inst)
    local out, keep = {}, {}
    for _, l in ipairs(C.said) do
        if inst == nil or l.inst == inst then out[#out + 1] = l.text else keep[#keep + 1] = l end
    end
    C.said = keep
    return out
end

function C.ops.dialogue(args)
    C.saidAt = nil -- read the screen now, not at the next tick
    pcall(C.recordDialogue)
    local dc = widgetDC()
    local d = dc and findDialogue(dc, args.instance)
    if not d then return { open = false, said = takeSaid(tonumber(args.instance)) } end
    local said = takeSaid(get(function() return d.DialogInstanceID end))
    local speaker, line = lastLine(d)
    local shown = {}
    for _, a in ipairs(answerList(d)) do shown[#shown + 1] = { n = a.n, text = a.text, disabled = a.disabled } end
    local showAnswers = get(function() return d.ShowAnswers end)
    if showAnswers == false then shown = {} end
    return { open = true, instance = get(function() return d.DialogInstanceID end),
        speaker = speaker, line = line, answers = shown, answerer = answerer(d),
        waiting = #shown == 0 or nil, said = said }
end

function C.ops.choose(args)
    local dc = widgetDC()
    local d = dc and findDialogue(dc, args.instance)
    if not d then error("no dialogue on screen") end
    if get(function() return d.ShowAnswers end) == false then error("no answers are shown yet; read dialogue again") end
    local list = answerList(d)
    local want = tonumber(args.n)
    local pick
    for _, a in ipairs(list) do if a.n == want then pick = a end end
    if not pick then error("no answer number " .. tostring(args.n) .. " (there are " .. #list .. ")") end
    if pick.disabled then error("that answer is greyed out") end
    if args.expect and args.expect ~= "" and not pick.text:lower():find(tostring(args.expect):lower(), 1, true) then
        error("answer " .. want .. " is now '" .. pick.text .. "'; the options changed, read them again")
    end
    local cmd = get(function() return dc.SelectAnswerCommand end)
    if not cmd then error("the dialogue cannot be answered right now") end
    if get(function() return cmd:CanExecute(pick.vm) end) == false then
        error("the game does not accept an answer right now")
    end
    local ok, err = pcall(function() cmd:Execute(pick.vm) end)
    if not ok then error("answer failed: " .. tostring(err)) end
    if args.as then
        local raw = clean(get(function() return pick.vm.BodyText end))
        local inst = get(function() return d.DialogInstanceID end)
        if raw and inst then C.chosen[inst] = { key = lineKey(raw), as = tostring(args.as) } end
    end
    return { chose = pick.text }
end

-- ---------------------------------------------------------------- dice rolls
-- A skill check in a dialogue opens the ActiveRoll widget and waits for a click on the
-- dice. Its view model (gui::DCActiveRoll) has RollState WaitForStart -> StartRoll ->
-- ResultReady, SkillOrAbility (a string handle), TargetNumber (what the die must show;
-- the DC is Roll.DifficultyCheck), RolledNumber1,
-- ResultNumber (with bonuses), Success; UserTriggeredNextPhaseCommand throws the dice, ContinueCommand
-- closes the result and the dialogue goes on. The human sees the dice either way.
-- After a failure RollAgainCommand spends one of the party's InspirationPoints and goes
-- to WaitForReRoll, where UserTriggeredNextPhaseCommand throws again.

local function rollDC()
    local kids = get(function() return Ext.UI.GetRoot():Find("ContentRoot").Children end)
    for _, w in ipairs(items(kids)) do
        if get(function() return w.Name end) == "ActiveRoll"
            and tostring(get(function() return w.Visibility end)) == "Visible" then
            return get(function() return w.DataContext end)
        end
    end
    return nil
end

local ROLL_STATE = { WaitForStart = "waiting", WaitForReRoll = "waiting", StartRoll = "rolling",
    ResultReady = "done" }

local function rollInfo(r)
    local state = tostring(get(function() return r.RollState end))
    local skill = get(function() return r.SkillOrAbility end)
    -- TargetNumber is what the die must show (the DC minus the bonuses); the DC is Roll.DifficultyCheck
    local out = { state = ROLL_STATE[state] or state, need = get(function() return r.TargetNumber end),
        dc = get(function() return r.Roll.DifficultyCheck end) or get(function() return r.TargetNumber end),
        skill = type(skill) == "string" and translated(skill) or nil,
        context = tostring(get(function() return r.RollContext end)) }
    if out.state == "done" then
        out.natural = get(function() return r.RolledNumber1 end)
        -- ResultNumber has the bonuses (Guidance...) added; FinalResult is the die
        out.total = get(function() return r.ResultNumber end) or get(function() return r.FinalResult end)
        out.success = get(function() return r.Success end) == true
    end
    out.inspiration = get(function() return r.InspirationPoints end)
    return out
end

-- Bonuses the roll window offers before the throw (Guidance, Bardic Inspiration...):
-- NearbyPartyCharacters[i].BoostModifierList[j], whose BoostModifier is the spell; adding
-- one is AddModifierCommand:Execute(that entry).
local function rollBoosts(r)
    local out = {}
    for _, pc in ipairs(items(get(function() return r.NearbyPartyCharacters end))) do
        local owner = get(function() return pc.Owner.EntityUUID end)
        for _, m in ipairs(items(get(function() return pc.BoostModifierList end))) do
            local name = get(function() return m.BoostModifier.Name end)
            out[#out + 1] = { vm = m, owner = owner, spell = get(function() return m.BoostModifier.PrototypeID end),
                name = type(name) == "string" and translated(name) or nil,
                selected = get(function() return m.IsSelected end) == true }
        end
    end
    return out
end

function C.ops.roll_state()
    local r = rollDC()
    if not r then return { open = false } end
    local info = rollInfo(r)
    if info.state == "waiting" then
        local list = {}
        for _, b in ipairs(rollBoosts(r)) do
            list[#list + 1] = { name = b.name, spell = b.spell, owner = b.owner, selected = b.selected or nil }
        end
        info.boosts = list
    end
    return info
end

-- Add the bonuses that belong to `owner` (the agent), before the throw.
function C.ops.roll_boost(args)
    local r = rollDC()
    if not r then error("no dice roll is on screen") end
    local cmd = get(function() return r.AddModifierCommand end)
    local added = {}
    for _, b in ipairs(rollBoosts(r)) do
        if b.owner == args.owner and not b.selected and cmd then
            if pcall(function() cmd:Execute(b.vm) end) then added[#added + 1] = b.name or b.spell end
        end
    end
    return { added = added }
end

-- step: "throw" the dice (only while waiting), "reroll" a failure with inspiration, or
-- "continue" after the result
local ROLL_STEP = { throw = "UserTriggeredNextPhaseCommand", reroll = "RollAgainCommand",
    continue = "ContinueCommand" }

function C.ops.roll(args)
    local r = rollDC()
    if not r then error("no dice roll is on screen") end
    local info = rollInfo(r)
    local step = args.step or "throw"
    local name = ROLL_STEP[step]
    if not name then error("step must be throw, reroll or continue") end
    if step == "throw" and info.state ~= "waiting" then return info end
    if step == "reroll" and not (info.state == "done" and not info.success and (info.inspiration or 0) > 0) then
        return info
    end
    local cmd = get(function() return r[name] end)
    if not cmd then error("the dice cannot be used right now") end
    local ok, err = pcall(function() cmd:Execute(nil) end)
    if not ok then error("roll failed: " .. tostring(err)) end
    return info
end

-- ---------------------------------------------------------------- trading
-- The server opens the game's own trade window for the agent's character (PROC_StartTrade,
-- what the Trade button runs); it shows on the human's screen. Its view model (gui::DCTrade):
--   CurrentTradingCharacter.EntityUUID  whose trade it is; Trader.EntityUUID the merchant
--   Mode                 Trade (buy and sell at once) or Barter
--   TraderInventory.Slots[i].Object     goods: EntityUUID, Name (handle), Count, TradePrice (for the
--                        whole stack, worked out by the game), ItemType (Gold for coins)
--   PartyCharacterInventories[i]        OwnerObject.EntityUUID, TradeInventories[j].Slots: our side
--   TradePartyGold, TraderInventoryGold
--   TradeItemCommand:Execute(object)    a double click in Trade mode: buys or sells it
-- A stack opens the SplitItem popup: CurrentPlayer.UIData.SplitItemData.TargetCount, then its
-- ApplySplitCommand. Esc closes the window (its close button sends a string the Lua side
-- cannot pass). When the human is not watching, the window and the popup are collapsed on
-- every tick (the game shows them again after a popup) and the HUD the game hid is shown again.

local function widget(name)
    local kids = get(function() return Ext.UI.GetRoot():Find("ContentRoot").Children end)
    for _, w in ipairs(items(kids)) do
        if get(function() return w.Name end) == name then return w end
    end
    return nil
end

local function bareId(s)
    s = tostring(s or "")
    return (s:match("(%x+%-%x+%-%x+%-%x+%-%x+)$") or s):lower()
end

local function goodsRow(o)
    local name = get(function() return o.Name end)
    local count = get(function() return o.Count end) or 1
    local price = get(function() return o.TradePrice end)
    return { id = get(function() return o.EntityUUID end), name = type(name) == "string" and translated(name) or "?",
        count = count, price = price }
end

local function isGold(o) return tostring(get(function() return o.ItemType end)) == "Gold" end

-- Our side: only the agent's own bag, never what the human or others carry.
local function mineSlots(dc, me)
    local out = {}
    for _, e in ipairs(items(get(function() return dc.PartyCharacterInventories end))) do
        if bareId(get(function() return e.OwnerObject.EntityUUID end)) == me then
            for _, inv in ipairs(items(get(function() return e.TradeInventories end))) do
                for _, s in ipairs(items(get(function() return inv.Slots end))) do
                    local o = get(function() return s.Object end)
                    if o then out[#out + 1] = o end
                end
            end
        end
    end
    return out
end

local function goods(dc)
    local out = {}
    for _, s in ipairs(items(get(function() return dc.TraderInventory.Slots end))) do
        local o = get(function() return s.Object end)
        if o then out[#out + 1] = o end
    end
    return out
end

local function tradeDC()
    local w = widget("Trade")
    return w and get(function() return w.DataContext end), w
end

function C.ops.trade_view(args)
    local dc = tradeDC()
    if not dc then return { open = false } end
    local me = bareId(args.me)
    local out = { open = true, mine = bareId(get(function() return dc.CurrentTradingCharacter.EntityUUID end)) == me,
        trader = get(function() return dc.Trader.EntityUUID end), mode = tostring(get(function() return dc.Mode end)),
        party_gold = get(function() return dc.TradePartyGold end),
        trader_gold = get(function() return dc.TraderInventoryGold end), goods = {},
        loading = get(function() return dc.IsWaitingForInventoriesCreation end) == true or nil }
    if not out.mine then return out end
    for _, o in ipairs(goods(dc)) do
        if not isGold(o) then out.goods[#out.goods + 1] = goodsRow(o) end
    end
    if args.yours then
        out.yours = {}
        for _, o in ipairs(mineSlots(dc, me)) do
            local worn = tostring(get(function() return o.Equipped end) or "NotEquipped") ~= "NotEquipped"
            if not isGold(o) and not worn then out.yours[#out.yours + 1] = goodsRow(o) end
        end
    end
    return out
end

-- Hide the window (and its popups) from the human until it closes, or show it again.
-- Trading also makes the game hide the HUD (hotbar, portraits, minimap...): what was visible
-- before the trade is put back, so a trade in the background leaves the human's screen as it was.
local TRADE_WIDGETS = { Trade = true, SplitItem = true }

local function hudKey(i, w) return i .. ":" .. tostring(get(function() return w.Name end)) end

function C.ops.trade_hide(args)
    if not args.on then C.tradeHide = nil return true end
    local hud = {}
    local kids = get(function() return Ext.UI.GetRoot():Find("ContentRoot").Children end)
    for i, w in ipairs(items(kids)) do
        if not TRADE_WIDGETS[get(function() return w.Name end)]
            and tostring(get(function() return w.Visibility end)) == "Visible" then
            hud[hudKey(i, w)] = true
        end
    end
    C.tradeHide = { since = Ext.Utils.MonotonicTime(), seen = widget("Trade") ~= nil, hud = hud }
    C.hideTrade()
    return true
end

function C.hideTrade()
    local hud = C.tradeHide and C.tradeHide.hud or {}
    local kids = get(function() return Ext.UI.GetRoot():Find("ContentRoot").Children end)
    for i, w in ipairs(items(kids)) do
        local vis = tostring(get(function() return w.Visibility end))
        if TRADE_WIDGETS[get(function() return w.Name end)] then
            if vis == "Visible" then pcall(function() w.Visibility = "Collapsed" end) end
        elseif vis == "Hidden" and hud[hudKey(i, w)] then
            pcall(function() w.Visibility = "Visible" end)
        end
    end
end

-- The split popup, answered with the count the agent asked for.
function C.answerSplit()
    local want = C.splitWant
    if not want then return end
    local w = widget("SplitItem")
    local dc = w and get(function() return w.DataContext end)
    local data = dc and get(function() return dc.CurrentPlayer.UIData.SplitItemData end)
    if not data then return end
    C.splitWant = nil
    local max = get(function() return data.ItemCount end) or want
    pcall(function() data.TargetCount = math.max(1, math.min(want, max)) end)
    pcall(function() dc.ApplySplitCommand:Execute() end)
end

-- Buy (side "buy": from the merchant) or sell (side "sell": from the agent's bag) `count` of an item.
function C.ops.trade_item(args)
    local dc = tradeDC()
    if not dc then error("the trade window is closed") end
    local me = bareId(args.me)
    if bareId(get(function() return dc.CurrentTradingCharacter.EntityUUID end)) ~= me then
        error("the trade window on screen is not yours")
    end
    local want = bareId(args.id)
    local pool = args.side == "sell" and mineSlots(dc, me) or goods(dc)
    local obj
    for _, o in ipairs(pool) do
        if bareId(get(function() return o.EntityUUID end)) == want then obj = o end
    end
    if not obj then
        error(args.side == "sell" and "that is not in your bag in the trade window" or "the merchant does not have that")
    end
    local row = goodsRow(obj)
    local count = math.max(1, math.min(tonumber(args.count) or 1, row.count or 1))
    if (row.count or 1) > 1 then C.splitWant = count end
    local ok, err = pcall(function() dc.TradeItemCommand:Execute(obj) end)
    if not ok then C.splitWant = nil; error("the trade window did not take it: " .. tostring(err)) end
    return { name = row.name, count = count, stack = row.count, price = row.price }
end

-- Close the window as Esc does. Only while it is open: Esc on the open world opens the game menu.
function C.ops.trade_close()
    C.splitWant = nil
    if not widget("Trade") then
        C.tradeHide = nil
        return { closed = true }
    end
    pcall(Ext.Input.InjectKeyPress, "ESCAPE")
    return { closed = false }
end

-- ---------------------------------------------------------------- chat panel
-- BG3 has no text chat, so the human types to the agent in a small IMGUI window.
-- Quick buttons and Yes/No answers to `ask` go the same way. What the human sends waits in
-- C.inbox until the bridge takes it (chat_take);
-- the bridge keeps the history and hands it back after a save load (chat_restore).

C.HOTKEY = "F10"
-- "This one": a middle click sends what the human's mouse points at to the agent. Holding the middle
-- button and dragging turns the camera, so only a short press that stays put counts.
C.CLICK_MS = 300
C.CLICK_PX = 6
C.MAX_LINES = 100
C.inbox = C.inbox or {}  -- strings the human typed, {ask = id, answer = "yes"/"no"} clicks, {point = ...} marks
C.asks = {}              -- open questions: id -> buttons to remove once answered

local COLORS = { human = { 1.0, 0.85, 0.55, 1.0 }, agent = { 0.6, 0.9, 1.0, 1.0 }, note = { 0.65, 0.65, 0.65, 1.0 } }

-- What the human reads, in the game's language: Simplified Chinese, or English for any other.
local TEXT = {
    en = {
        title = "BG3 Co-op", hint = "Message the agent, Enter to send", send = "Send", yes = "Yes", no = "No",
        buttons = { "Follow me", "Stop", "Wait for me", "Free roam" },
        pointed = "> (pointing at something: the agent sees what)", spot = "> (pointing at a spot)",
        intro = "The agent reads what you type here. %s shows or hides this panel. Middle-click something to "
            .. "show it to the agent (\"attack this\", \"go there\").",
    },
    zh = {
        title = "BG3 合作", hint = "给 agent 发消息，回车发送", send = "发送", yes = "是", no = "否",
        buttons = { "跟上我", "停下", "等我", "自由行动" },
        pointed = "> （指了一个东西，agent 会看到是什么）", spot = "> （指了一个地点）",
        intro = "agent 会读你在这里打的字。%s 显示或隐藏这个面板。用鼠标中键点一下东西，就能指给 agent 看"
            .. "（「打这个」「去那里」）。",
    },
}

-- "zh" when the game runs in Simplified Chinese ("Chinese"; Traditional is another name), else "en".
function C.lang()
    if not C.langCode then
        local ok, l = pcall(function() return Ext.Utils.GetGlobalSwitches().Language end)
        C.langCode = ok and tostring(l) == "Chinese" and "zh" or "en"
    end
    return C.langCode
end

local function T(key) return TEXT[C.lang()][key] end

-- Quick buttons: what the agent receives when the human clicks one (the agent reads English).
local QUICK = {
    "[button] Follow me: come back to my character and stay close",
    "[button] Stop what you are doing",
    "[button] Wait for me here",
    "[button] Explore on your own",
}

local function colored(el, kind)
    pcall(function()
        el.TextWrapPos = 0
        el:SetColor("Text", COLORS[kind] or COLORS.note)
    end)
    return el
end

local function prune(p)
    local kids = get(function() return p.log.Children end)
    local n = kids and #kids or 0
    for i = 1, n - C.MAX_LINES + 1 do
        local old = get(function() return kids[i] end)
        if old then pcall(function() old:Destroy() end) end
    end
end

-- Scroll the log to the newest line. ImGui clamps a scroll request to the content height of the
-- frame before, so a line added this frame (or text that wraps once laid out) would be left just
-- below the edge: keep asking for a short while, until the layout has caught up.
C.SCROLL_MS = 400

local function scrollDown(p)
    if p then p.scrollUntil = Ext.Utils.MonotonicTime() + C.SCROLL_MS end
end

local function addLine(kind, text)
    local p = C.panel
    if not p then return end
    prune(p)
    pcall(function() colored(p.log:AddText(text), kind) end)
    scrollDown(p)
end

-- The human's own lines as the panel shows them, for the bridge's copy of the history.
C.echo = C.echo or {}

local function echo(line)
    C.echo[#C.echo + 1] = line
    addLine("human", line)
end

local function push(text, shown)
    C.inbox[#C.inbox + 1] = text
    echo("> " .. (shown or text))
end

local function send()
    local p = C.panel
    local text = clean(get(function() return p.input.Text end))
    pcall(function() p.input.Text = "" end)
    if text then push(text:sub(1, 500)) end
end

local function buildPanel()
    if C.panel then pcall(function() C.panel.win:Destroy() end) end
    C.asks = {}
    local w = Ext.IMGUI.NewWindow(T("title") .. " (" .. C.HOTKEY .. ")")
    w.Closeable = true
    w.NoFocusOnAppearing = true
    w:SetSize({ 440, 320 }, "FirstUseEver")
    local status = colored(w:AddText(""), "note")
    for i, msg in ipairs(QUICK) do
        local label = T("buttons")[i]
        local b = w:AddButton(label)
        if i > 1 then b.SameLine = true end
        b.OnClick = function() push(msg, "[" .. label .. "]") end
    end
    local log = w:AddChildWindow("log")
    log.Size = { 0, -36 }
    local input = w:AddInputText("##msg", "")
    input.Hint = T("hint")
    input.EnterReturnsTrue = true
    input.OnChange = function() send() end
    local button = w:AddButton(T("send"))
    button.SameLine = true
    button.OnClick = function() send() end
    C.panel = { win = w, log = log, input = input, status = status }
end

local function ensurePanel()
    if not C.panel then buildPanel() end
    return C.panel
end

local function r1(x) return math.floor(x * 10 + 0.5) / 10 end

-- What is under the human's mouse: a character or item ({ id }), else the spot on the ground ({ pos }).
function C.pointedAt()
    local ph = get(function() return Ext.UI.GetPickingHelper(1) end)
    if not ph then return nil end
    for _, h in ipairs(items(get(function() return ph.Inner.Inner end))) do
        -- characters and items have an id; scenery and the ground do not (items do not have a
        -- ClientItem component to check for, their client component is ecl::Item)
        local e = get(function() return h.GameObject end)
        local u = e and get(function() return e.Uuid.EntityUuid end)
        if u then return { id = u } end
    end
    local p = get(function() return ph.Inner.Position end)
    local ok = p and get(function() return math.abs(p[1]) + math.abs(p[3]) > 0.01 and math.abs(p[1]) < 1e5 end)
    if ok then return { pos = { r1(p[1]), r1(p[2]), r1(p[3]) } } end
    return nil
end

local function mark(at)
    if not at then return end
    C.inbox[#C.inbox + 1] = { point = at }
    echo(at.id and T("pointed") or T("spot"))
end

local function cursor()
    return get(function()
        local c = Ext.UI.GetPickingHelper(1).WindowCursorPos
        return { c[1], c[2] }
    end)
end

local function middle(b) local s = tostring(b) return s == "2" or s == "Middle" end

function C.onMouse(e)
    if not middle(get(function() return e.Button end)) then return end
    local t = Ext.Utils.MonotonicTime()
    if get(function() return e.Pressed end) then
        C.press = { t = t, xy = cursor(), at = C.pointedAt() } -- before a drag turns the camera
        return
    end
    local p = C.press
    C.press = nil
    if not p or t - p.t > C.CLICK_MS then return end
    local xy = cursor()
    if xy and p.xy and math.abs(xy[1] - p.xy[1]) + math.abs(xy[2] - p.xy[2]) > C.CLICK_PX then return end
    mark(p.at)
end

function C.onKey(e)
    if e.Event ~= "KeyDown" or e.Repeat or tostring(e.Key) ~= C.HOTKEY then return end
    local p = ensurePanel()
    p.win.Open = not p.win.Open
    if p.win.Open then scrollDown(p) end
end

-- The agent wrote something: bring the panel up, hidden or collapsed, so the human sees it.
local function reveal(p)
    pcall(function() p.win.Open = true end)
    pcall(function() p.win:SetCollapsed(false) end)
end

function C.onTick()
    pcall(C.recordDialogue)
    if C.splitWant then pcall(C.answerSplit) end
    local h = C.tradeHide
    if h then
        pcall(C.hideTrade)
        -- stop hiding once the window has come and gone, or if it never came
        if widget("Trade") then h.seen = true
        elseif h.seen or Ext.Utils.MonotonicTime() - h.since > 15000 then C.tradeHide = nil end
    end
    local p = C.panel
    if p and p.scrollUntil then
        if Ext.Utils.MonotonicTime() > p.scrollUntil then p.scrollUntil = nil end
        pcall(function() p.log:SetScroll({ 0, 1e7 }) end)
    end
end

-- A newer script replacing an older one in the same Lua state: rebuild the panel so its
-- callbacks run the new code (the bridge restores the history right after).
if C.panel then pcall(function() C.panel.win:Destroy() end) C.panel = nil end
if C.keySub then pcall(function() Ext.Events.KeyInput:Unsubscribe(C.keySub) end) end
C.keySub = Ext.Events.KeyInput:Subscribe(function(e) C.onKey(e) end)
if C.tickSub then pcall(function() Ext.Events.Tick:Unsubscribe(C.tickSub) end) end
C.tickSub = Ext.Events.Tick:Subscribe(function() C.onTick() end)
if C.mouseSub then pcall(function() Ext.Events.MouseButtonInput:Unsubscribe(C.mouseSub) end) end
C.mouseSub = Ext.Events.MouseButtonInput:Subscribe(function(e) C.onMouse(e) end)

-- A line for the panel (kind agent or note). It brings up a hidden or collapsed panel.
function C.ops.chat_post(args)
    local text = tostring(args.text or "")
    if text == "" then error("text required") end
    local p = ensurePanel()
    reveal(p)
    addLine(args.kind or "agent", text)
    return true
end

-- A question with Yes/No buttons. Typing a reply works too; the bridge closes it either way.
function C.ops.chat_ask(args)
    local id = tonumber(args.id)
    local text = tostring(args.text or "")
    if not id or text == "" then error("id and text required") end
    local p = ensurePanel()
    reveal(p)
    prune(p)
    pcall(function()
        local g = p.log:AddGroup("ask" .. id)
        colored(g:AddText(text), "agent")
        local yes = g:AddButton(T("yes") .. "##" .. id)
        local no = g:AddButton(T("no") .. "##" .. id)
        no.SameLine = true
        local function answer(a)
            C.inbox[#C.inbox + 1] = { ask = id, answer = a }
            for _, b in ipairs({ yes, no }) do b.Disabled = true end
        end
        yes.OnClick = function() answer("yes") end
        no.OnClick = function() answer("no") end
        C.asks[id] = { group = g, buttons = { yes, no } }
    end)
    scrollDown(p)
    return true
end

-- The question got its answer (or timed out): drop the buttons, show what happened.
function C.ops.chat_ask_close(args)
    local a = C.asks[tonumber(args.id)]
    if not a then return false end
    C.asks[tonumber(args.id)] = nil
    for _, b in ipairs(a.buttons) do pcall(function() b:Destroy() end) end
    if args.text and args.text ~= "" then
        pcall(function() colored(a.group:AddText(tostring(args.text)), args.kind or "human") end)
    end
    scrollDown(C.panel)
    return true
end

-- Hand over what the human sent; `status` refreshes the line at the top of the panel.
function C.ops.chat_take(args)
    if args.status and C.panel then
        pcall(function() C.panel.status.Label = tostring(args.status) end)
    end
    local msgs, shown = C.inbox, C.echo
    C.inbox, C.echo = {}, {}
    return { messages = msgs, shown = shown, lang = C.lang() }
end

-- History from the bridge after a save load: [{kind, text}], oldest first.
function C.ops.chat_restore(args)
    local p = ensurePanel()
    pcall(function() p.log:RemoveAllChildren() end)
    local lines = args.lines or {}
    if #lines == 0 then
        addLine("note", T("intro"):format(C.HOTKEY))
    end
    for _, l in ipairs(lines) do addLine(l.kind, l.text) end
    return true
end

------------------------------------------------------------------------
-- Quest markers: the world map's view model (CurrentPlayer.WorldMap.Markers, filled
-- whether or not the map is open) lists every marker on this map. Its own Type
-- property (from GetAllProperties: `.Type` gives the Noesis class name) is
-- "QuestMarker" for quest targets; WorldPos is world {x, z}, Height the y, Name a
-- loca handle, QuestViews[i].Quest / .MainItem the quest and the main quest (Title
-- handles). Found 2026-11-04.
------------------------------------------------------------------------

function C.ops.quest_markers()
    local kids = get(function() return Ext.UI.GetRoot():Find("ContentRoot").Children end)
    local markers
    for _, w in ipairs(items(kids)) do
        markers = markers or get(function() return w.DataContext.CurrentPlayer.WorldMap.Markers end)
    end
    local out = {}
    for _, m in ipairs(items(markers)) do
        local p = get(function() return m:GetAllProperties() end) or {}
        if p.Type == "QuestMarker" then
            local wp = get(function() return m.WorldPos end)
            local row = { name = type(p.Name) == "string" and translated(p.Name) or "?",
                pos = wp and { wp[1], tonumber(p.Height) or 0, wp[2] }, quests = {} }
            for _, qv in ipairs(items(get(function() return m.QuestViews end))) do
                local title = get(function() return qv.Quest.Title end)
                local main = get(function() return qv.MainItem.Title end)
                if type(title) == "string" then
                    local q = { title = translated(title) }
                    if type(main) == "string" and main ~= title then q.part_of = translated(main) end
                    row.quests[#row.quests + 1] = q
                end
            end
            if row.pos then out[#out + 1] = row end
        end
    end
    return { markers = out }
end

function C.ops.ping() return { version = C.VERSION } end
function C.ops.lang() return C.lang() end

function C.rpc(json)
    local ok, req = pcall(Ext.Json.Parse, json)
    if not ok or type(req) ~= "table" then
        return Ext.Json.Stringify({ ok = false, error = "bad request" })
    end
    local fn = C.ops[req.op]
    if not fn then return Ext.Json.Stringify({ ok = false, error = "unknown op " .. tostring(req.op) }) end
    local ok2, res = pcall(fn, req.args or {})
    if ok2 then return Ext.Json.Stringify({ ok = true, result = res }) end
    local msg = tostring(res):gsub("^.-:%d+: ", "")
    return Ext.Json.Stringify({ ok = false, error = msg })
end

return "BG3COOP client v" .. C.VERSION
