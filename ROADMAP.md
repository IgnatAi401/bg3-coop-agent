# 路线图

目标：做成公开仓库，面向 Windows 玩家。游戏和 agent 在同一台电脑上，支持 DeepSeek Harness（dsh）、Claude Code、Codex 三个 agent。

## 定下来的方向

- **一个仓库，一个核心，三层薄插件**。游戏连接、Lua 注入和 MCP 服务器只有一份；三个 agent 都通过 MCP 使用它。插件里只放"怎么启动 MCP 服务器"的配置，不写游戏逻辑。
- **游玩守则只维护一份**，写在 MCP 服务器的 `instructions` 里。dsh、Claude Code、Codex 都会读取它，不再单独维护 `play/CLAUDE.md`。
- **默认直连本机** `127.0.0.1:9998`。SSH 隧道只留作开发用的隐藏选项，README 里不提。
- **不发布到 PyPI 或 npm，也不做 exe 和安装程序**。用户自己 clone 仓库，或者让自己的 agent 按说明安装。只要求 Python ≥ 3.10：uvx、`uv tool`、pipx、venv 或 conda 里 pip 装都行，由 agent 看用户电脑上有什么来选；插件用 uvx，是需要 uv 的一键装法。
- **GitHub Release** 里放打包好的 wheel，以及三个 agent 各自的纯净版插件。插件的启动命令指向对应版本的 wheel：
  `uvx --from https://github.com/<用户>/<仓库>/releases/download/vX.Y.Z/bg3coop-X.Y.Z-py3-none-any.whl bg3coop-mcp`

## 仓库结构

```
bg3-coop-agent/
├─ src/bg3coop/          # 核心：game.py、remote_lua.py、lua/、MCP 服务器、setup/doctor 命令
├─ integrations/
│  ├─ dsh/               # npm 包：package.json（dsh.bundle）+ cordis.patch.yml + locale/ + assets/
│  ├─ claude-code/       # .claude-plugin/plugin.json + .mcp.json + assets/
│  └─ codex/             # .codex-plugin/plugin.json + .mcp.json（带超时）+ assets/
├─ .claude-plugin/marketplace.json   # Claude Code 的插件市场
├─ .agents/plugins/marketplace.json  # Codex 的插件市场
├─ scripts/release.py                # 同步版本号、打插件 zip
├─ tests/
├─ docs/                 # 回归测试清单、给 agent 看的安装说明
└─ LICENSE、README.md、README.en.md、CHANGELOG.md
```

## 第 1 阶段：整理核心

- [x] 把 `play/CLAUDE.md` 的游玩守则合并进 MCP `instructions`
- [x] 默认直连本机，SSH 改为隐藏选项
- [x] `bg3coop setup`：从 Steam 的 `libraryfolders.vdf` 找到游戏目录，写 `ScriptExtenderSettings.json`，检查 `DWrite.dll`
- [x] `bg3coop doctor`：检查游戏是否在运行、9998 端口能否连上、Lua 能否注入、各版本是否匹配
- [x] 确认调试端口只在本机监听，不暴露到局域网
- [x] 用 lupa 加假的 `Osi` 接口，给 Lua 逻辑写单元测试；GitHub Actions 在 `windows-latest` 上运行（配置已写，未验证）
- [x] 把 `FIXES.md` 里的回归清单移到 `docs/testing.md`
- [x] 加 LICENSE（MIT）
- [x] 重写调试协议客户端和 Steam 配置解析，复核代码相似片段并移除旧的上游致谢与许可证副本

## 第 2 阶段：游戏内聊天面板

BG3 没有原生文字聊天，所以输入框只能自己做；agent 向人类输出时，优先用原生的显示方式。

- [x] 用 Script Extender 的 IMGUI 做一个小窗，用 `Ext.Events.KeyInput` 监听快捷键开关
- [x] 人类的消息进入客户端队列；任何工具返回时都顺带未读消息，`wait` 收到消息时立刻返回
- [x] `say` 改为写入面板，放宽限流；紧急情况才用弹窗或原生提示
- [x] 实测原生的非模态显示方式（屏幕顶部通知、角色头顶冒字），替代会打断人类的 `OpenMessageBox`（`ShowNotification` 可用，面板关着时用它；`ShowError` 不显示；头顶冒字没找到接口）
- [x] 面板显示 agent 当前状态（在做什么、HP），加快捷按钮：跟上、停下、等我、自由行动
- [x] 面板实时动态：正在运行的工具和秒数、工具之间「思考中 N 秒」（久了提示可能停了）、战斗中轮到 agent 时它有没有收到回合（客户端读 `TurnBased`）、可展开的最近 6 个动作
  - [ ] 没实测：战斗中「轮到我了，还没收到 → 已收到」的切换（实测时附近没有能打的）
- [x] 面板重新设计（client v29）：深色主题、标题栏放角色名、新消息标题栏闪烁并保持「N 条新消息」直到人类看过、聊天/动作记录两页、同一说话人连续消息合并、去掉 HP
  - [ ] 没实测：1080p 等其他分辨率下底部输入框是否被裁（按 2560×1440 量的 90 像素按屏幕高度缩放，最少 86）
- [x] 新增 `ask` 工具：agent 提问，人类点同意/拒绝或直接回复，有超时
- [x] 聊天记录保存在 Python 侧，读档重新注入后恢复
- [x] 需要实测：~~面板打字时是否会触发游戏按键~~（不会）、~~快捷键是否冲突~~（F10 正常）、~~独占全屏下能否显示~~（2026-11-04 用户确认能显示、能回复）
- [x] README 写明：只有 agent 在持续循环时才能看到面板消息（dsh 的 goal/ralph、Claude Code 的 `/loop` 可以帮忙保持循环）
- [x] 面板要等 agent 调用工具才注入，重启游戏或读档后 F10 暂时没反应。不装 mod，在游玩守则里让 agent 接管后先 `say` 打招呼（顺带打开面板），人类说面板不见了时调用一次工具再打招呼；README 写明

## 第 3 阶段：补全玩法

- [x] 物品栏：查看背包、装备、喝药水、用卷轴、把物品交给人类（投掷物还不支持；药水只能自己喝）
- [x] 更换准备的法术：新增 `prepare`，走游戏自己的请求队列（`Ext.System.ServerSpell.PlayerPrepareSpell` / `PlayerUnprepareSpell`，法术书界面用的也是它），上限读游戏存的 `SpellBookPrepares.ClassFallbackPreparedSpellCount`（按职业），不自己按规则算。引擎不查上限（界面查），所以由我们拒绝超额；战斗中拒绝
  - [x] 实测（2026-11-04，影心 牧师11/法师1）：超额被拒绝，一换一后 `spells` 立刻变化，已换回。存档后是否保留没测（不能存档）
- [x] 战斗信息：新增 `combat` 工具，列出先攻顺序（`CombatParticipant.InitiativeRoll`）、各人 HP、状态和专注，自己剩余的移动和动作，以及上回合以来的战斗记录（施法、伤害、倒地、死亡、被控制）；`your_turn` 事件带上这段记录
  - [x] 战斗中实测（2026-11-04，生成的小恶魔）：AI 施法（疾病射线、腐蚀爪）会触发 `UsingSpellOnTarget` 并进记录；伤害、倒地都记下。顺序和界面一致（读客户端 `CombatantsOverlay` 视图模型的 `Combatants[i].CurrentCombatant.EntityUUID` 对照，2026-11-04）
- [x] 战斗截图：轮到 agent 的回合时，`wait`（`your_turn` 事件）或 `combat` 中先到的那个附一张游戏画面（JPEG，宽 1280，质量 60，约 150 KB），每回合一张。`wincap.py` 用 ctypes 直接调 Windows API（GDI 截、GDI+ 编码），在 MCP 进程里完成，不开新进程和窗口；游戏不在前台或最小化时不截，只写原因。`BG3COOP_SCREENSHOTS=0` 关闭（给不能看图的模型）
  - [x] 实测（2026-11-04）：独占全屏 2560×1440 能截到画面、不是黑屏；连截 3 次游戏一直在前台，没被最小化
  - [ ] 没实测：dsh（DeepSeek）收到图片会怎样；正式路径（MCP 服务器在 Windows 本机）只在开发路径（pythonw 计划任务）下跑过同一份截图代码
- [x] 战斗规则：每场战斗开头那条结果附 `combat_basics`（按 bg3.wiki 整理的动作经济、命中与豁免、优劣势、借机攻击、倒地与死亡豁免、专注、常见状态、地表、伤害抗性，状态带游戏里的中文名），bridge 起在战斗中途时随第一个 `your_turn` 补发；`rules` 也带上。守则里原来那几条战斗规则并进去
  - [x] 实测（2026-11-05，奥林）：开战第一条结果带 `combat_basics`，同一场之后不再带，读档后新一场又带
  - [ ] 没实测：bridge 在战斗中途接入时，第一个 `your_turn` 补发
  - [x] 实测：每回合 `say` 一句，聊天面板没刷屏（只打了两三个回合）
  - [ ] 没实测：须知变长后 agent 是否真的少犯错（贴身放远程、乱走吃借机攻击、不扶倒地队友）
- [x] 敌人的抗性和特性：新增 `examine`（等级、AC、属性、伤害抗性/免疫/易伤、状态免疫、被动特性和说明），`combat` 里敌人附带抗性和状态免疫
- [x] 新事件：`downed`（队友或人类倒地）、`controlled` / `control_ended`（自己被沉睡、定身、魅惑等，按状态的 `StatusGroups` 判断）
- [x] 范围法术施放前检查范围内有没有队友：伤害、控制、减益类的范围法术（含卷轴）会波及队友时先拒绝并列出名字，`even_if_allies` 强制施放；按 stats 算圆形、锥形、长条，跳过本身不伤队友的（`not Ally()`、只对敌人、法术塑形、施法者身上的光环），只影响亡灵等类型的只算该类型队友
  - [x] 投掷物：效果法术在 stats、模板和物品实体里都找不到链接，只能读部分模板的 `CreateSurface` 半径（油脂瓶 3 米），读不到按 4 米算；炉光炸弹、加速孢子不拦，圣水只算亡灵和邪魔队友。`throw` 同样有 `even_if_allies`
- [x] 实测 agent 自己对话里的骰子检定由谁来掷：骰子窗口（`ActiveRoll`）弹在人类屏幕上，等人点击，agent 自己会卡住。新增 `roll` 工具：用窗口视图模型的 `UserTriggeredNextPhaseCommand` 掷骰、`ContinueCommand` 继续，人类照样看到骰子；`dialogue` 带 `roll`（技能、DC、状态）。选项上的技能标签原来是没翻译的句柄（`[HFD00683…]`），现在翻译成「[调查]」
  - [x] 失败时用激励骰重掷：`roll(reroll_if_failed=true)`（`RollAgainCommand` → `WaitForReRoll` → 再掷），实测激励骰 3→2
  - [x] 掷前加自己的加值：`dialogue` 的 `roll.your_boosts`，`roll(use_boosts=true)`（`NearbyPartyCharacters[i].BoostModifierList[j]` → `AddModifierCommand:Execute(项)`）。实测神导术加上、状态挂上。别的队友的加值（如人类的诗人激励）不动
- [x] 读取人类鼠标指着的目标：人类指着目标按 `F9`，客户端用 `Ext.UI.GetPickingHelper(1)` 取角色/物品或地面坐标，agent 收到 `[pointing at] ...`（带 id 或 x/y/z），配合下一句话「打这个」「去那里」
  - [x] 实测（现在是鼠标中键）：指角色、物品、地面都对（物品原来认不出，已修）
- [x] `set_agent` 支持中英文名字匹配（起源角色按 ID 里的英文模板名匹配；自建主角只能用游戏里显示的名字）
- [x] 开锁、解除陷阱交给人类：游戏只从人类的界面发起（客户端网络消息唤醒服务器的开锁/拆陷系统），Osiris 没有对应调用，SE 读不到拆陷系统，客户端任务启动不了；往 `ServerLockpicking.PickLockRequests` 写请求两次让游戏闪退。用户定了都请人类做，不自己模拟检定
  - [x] `use` 锁着的门/箱子、`container` 锁着的箱子、`use` 已发现且布置着的陷阱时拒绝，说明请人类右键开锁/解除、队伍里有几个盗贼工具或拆陷工具（没有时说明钥匙或绕路）、有主人的锁开了算犯罪要先 `ask`、拆陷前离陷阱 3 米以上；守则加了一条
  - [ ] 没实测：新提示在游戏里的样子（写完时游戏刚闪退）

### 移动、脱战、复活（尽量走游戏原生流程）

原则：照搬游戏界面触发的 Osiris 事件和剧本 PROC，让游戏自己检查限制、计算效果，不自己模拟。做法来自游戏剧本源码（`Mods/*/Story/RawFiles/Goals/`）和 stats。

- [x] `travel camp`：去营地或离开营地。进营地调用 `PROC_TeleportToFromCamp(角色)`（和「去营地」按钮相同，内部检查 `QRY_Camp_IsPlayerBlockedFromTeleportToCamp`），之前先解除和人类的链接并等它生效；离开调用单角色的 `PROC_Camp_Leave`，因为按钮的离开会把同一用户在营地的所有角色送出去。战斗中不可用（原版规则）
  - [x] 实测：人类的队伍也在营地时，agent 离开不带走他们（误把全队带进营地时顺带验证了）
- [x] `travel waypoint`：列出 agent 自己解锁过的传送点（`DB_WaypointInfo` + `DB_WaypointUnlocked`），传送前查 `QRY_WaypointTeleport_PlayerBlocked` 和 `QRY_GLO_BlockTeleportToWaypoint`，再调 `PROC_WaypointTeleportTo(角色, 触发器)`，之前同样先解除和人类的链接。只列当前地图的传送点：去别的地图要换区域，会带上全队。战斗中不可用
- [x] `travel flee`：战斗中逃跑。只在自己回合；引擎的前置检查在角色的 `FleeCapability` 组件里（`Flags` 列出阻止原因，如 `EnemyTooClose`：`CurrentFleeDistance` 27 米内有敌人，`FleeDistance` 是最近敌人的距离），再查 `DB_CombatFlee_BlockedFor`。然后照引擎的做法发出 `FleeFromCombat(角色, 战斗ID)` 事件并 `LeaveCombat`，剧本（`__Combat`）等角色离开战斗后送到营地（不行就传送点、关卡起点）。实测：敌人 11 米时拒绝并说明，跑到 27 米外后逃到营地，其他人继续打
- [x] ~~人类死亡时的处理写进游玩守则~~：不写成规则，只在守则里告诉 agent 有哪些救人手段（`Target_Help`、复活卷轴、营地守墓人），救不救由它自己判断
- [x] 投掷：新增 `throw` 工具，调用 `UseSpell(自己, "Throw_Throw", 目标, 被扔的东西)`（Larian 剧本里的用法）。能扔背包物品、地上的物品、尸体和角色，能不能扔、伤害和物品效果都由游戏判断；目标可以是角色、物品或坐标（扔向坐标用 `UseSpellAtPosition`，在请求的 `Targets[1].Target2` 填上被扔的东西）
  - [x] 战斗中实测：扣动作、不够近时先走过去（扣移动力）、油脂瓶落地成油面（小恶魔 `INSURFACE`）、数量减一；隐形的敌人不能当目标（对坐标扔可以）。会掷命中骰：对 AC 31 的敌人扔标枪落空（2026-11-04）
- [x] 复活卷轴：`use_item` 读 `Teleportation_*` 类卷轴时，调用 `UseSpell(自己, 法术, 死者, 落点)`（撤回者剧本里的用法）。游戏检查目标（死亡或倒地的可玩角色）和 9 米落点范围，复活后 1 HP、带「复活中」状态
  - [x] 实测成功复活（明萨拉死亡后读回生术卷轴，1 HP 起身，卷轴少一张）。原来去掉 `IgnoreTargetChecks` 后游戏对合法目标也拒绝，改成保留它、由我们按法术条件自己检查（队友、死亡/倒地/石化、没有 `BLOCK_RESURRECTION`、落点 9 米内）。`Target_Help` 扶起倒地队友也实测通过
- [x] 实测：营地、传送点、投掷、逃跑、复活都测过了

### 现有功能改走原生流程

调研结论（2026-11-03 实测）：`Osi.UseSpell` 发起的施法带 `IgnoreSpellRolls`、`IgnoreCastChecks`、`IgnoreTargetChecks`、`IgnoreHasSpell` 四个开关。请求在下一个计时器回调（`Ext.Timer.WaitFor(0)`）时排在 `Ext.System.ServerCastRequest.OsirisCastRequests` 里，可以改它的 `CastOptions` 和 `Item`。

- [x] **施法要掷骰（优先）**：~~施法后在 `WaitFor(0)` 里去掉 `IgnoreSpellRolls`~~（已做，server.lua v8）。实测（2026-11-04）：给敌人 `AddBoosts(AC(20))` 后火焰箭、主手攻击都落空；给 `RollBonus(SavingThrow,20)` 后妖火被豁免（不挂状态、照扣法术位），去掉加值后挂上。骰子是否显示给人类没人看屏幕，没确认
- [x] 施法检查：~~去掉 `IgnoreCastChecks`~~（已做；目标超出距离时角色会自己走过去再施法）。战斗中走过去扣移动力（实测直线约 2.7 米扣 1.3，比直线少，原因不明）。`IgnoreHasSpell` 必须保留，去掉后施法失败（请求里的法术标识不完整）。`IgnoreTargetChecks` 保留：战斗中对站着的 NPC 用「协助」被游戏拒绝（不扣动作，但走过去的移动力扣了）；战斗外同样的施放报成功
- [x] 卷轴改原生：请求填上 `Item = 卷轴` 并加 `DestroySource`，游戏自己施放并消耗卷轴（魔法护甲卷轴实测成功），替换现在的 `TemplateRemoveFrom`
- 扣资源保持手动：去掉开关、或把请求挪到 `NetworkStartRequests`，游戏都不扣法术位（实测）。剧本路径的施法看来本来就不计费，继续由我们按 `UseCosts` 扣
- [x] 开启对话改原生：`talk` 现在取 `DB_Dialogs` 第一行 + `QRY_StartDialog_Fixed`，遇到按条件切换对话的 NPC 可能选错。改为 `QRY_SelectAndStartDialog(NPC, agent)`，就是人类点 NPC 时 `DialogStartRequested` 走的流程（会选对话、检查双方是否有空、解除隐身）。直接调用 QRY 会跳过少数挂在 `DialogStartRequested` 事件上的特殊处理（如石化的债务人）
- [x] 逃跑：没用 `CombatFleeRequest`（往组件里写请求怕出错），改为照搬引擎的事件 + `LeaveCombat`，剧本后备负责落点，见上面 `travel flee`
- [x] 战斗中移动：`CharacterMoveTo` 自己扣移动力（走 2.3 米 9.0→6.7），走开会吃借机攻击（实测被小恶魔打倒）；超出剩余移动力时拒绝
- [x] 拿取和偷窃：`take` 改用 `Osi.Pickup(角色, 物品, 事件)`（和点击拾取一样）。实测：地上的有主物品触发 `MovedBy`、`CharacterStoleItem` 和 `Steal` 犯罪，接着旁白「被抓了个正着」的对话由 agent 自己选（交出赃物后物品回到原主）；容器里的也能拿，发 `CharacterStoleItem`（来源是容器），剧本规定战斗外从容器拿不算目击的偷窃。原来的 `ToInventory` 一声不响、还把主人改成自己。`Osi.Use` 对饮品是喝掉（有主的触发 `UseForbiddenItem`）。`container` 直接读库存，打开有主容器不算犯罪（界面里打开会算），没改
- [x] 结束回合：`end_turn` 同时设 `TurnBased.RequestedEndTurn`（共享回合要所有人都设才往下走）
- [x] 物品的物主：`look`/`container` 标 `owned by`，守则据此避免偷窃
- 已经是原生的，不用改：对话选择（执行界面的 `SelectAnswerCommand`）、喝药水（`Osi.Use`）、装备（`Osi.Equip`）、结束回合（`Osi.EndTurn`）、反应设置（`InterruptPreferences`）、走路（引擎寻路）

## 第 4 阶段：记忆和体验

- [x] 探索记忆：记录走过的区域，`look` 返回还没去过的方向，加上当前区域名和最近的传送点（10 米格子，全队都算；区域名只有地图级，游戏里的小区域名没找到接口）
  - [x] 记忆跟随存档：做了只含 Lua 的小 mod「BG3 Co-op Memory」，启动即记录全队位置，存进存档的 mod 变量；`setup` 打包 .pak 并写进 `modsettings.lsx`，`doctor` 检查。没装时退回到只记到下次读档
  - [x] 实机验证：游戏能加载自己打包的 .pak，记录跟着存档走（读旧档回退、读新档恢复）
  - [ ] 实测：~~没连 agent 时走的路也记下~~（mod 自己记录：不经过 bridge 直接让卡菈克走 30 米，格子 46→55）；不同周目的存档不混；删掉 mod 后读带 mod 的存档会怎样；成就是否受影响（要换存档、动 Mods 文件夹或看屏幕，留给用户）
- [x] `notes` 工具：goal/story/place 存进存档（Memory mod v2 的 `Notes`），persona/preference 存本地、按周目分文件（mod v2 的 `Campaign`，装 v2 前的存档用主角 GUID 当周目编号）；`set_agent` 时一起返回；守则里要求随时记
  - [x] 实机验证 mod v2：`setup` 升级成功，读档回退和周目编号都对
  - [x] 读游戏任务日志：新工具 `quests`。开着的任务 = `DB_QuestIsAccepted` − `DB_QuestIsClosed`；标题和步骤文字从游戏 pak 里的 `quest_prototypes.lsx`（`Ext.IO.LoadFile(..., "data")`）取 handle 再 `Ext.Loca` 翻译；做到哪一步看 `DB_QuestDef_State` 里各步骤对应的剧情标记（全局或任一队友），取文件里最靠后的那步。隐藏任务不列，子任务带 `part_of`
- [x] 每个起源队友一份性格提示，用于角色扮演（`persona.py`，按 `DB_Origins` 里固定的 GUID；只写性格和说话方式，不剧透；`set_agent` 返回 `role_play`，persona 笔记优先）
- [x] `look` 只返回变化部分，节省 token：每样东西一行字（id、名字、关系、HP、距离方向），5 分钟内、同一角色、同一地图、同一半径的下一次 `look` 只列新出现和变化的（移动、受伤、死亡…）、`gone` 和 `unchanged` 计数，人类总列出；`full=true` 全列（实测下城区 1827 字符 → 962，原地再看 236）

### 夜间发现的小问题

- [x] 新开的 bridge 第一次 `wait` 会把游戏里积压的旧事件（最多 200 条，可能是几小时前的）全返回：现在只要 30 秒内的
- [x] 落空、豁免成功、免疫也会触发 `AttackedBy`（伤害 0），战斗记录原来写成 `hit ... damage 0`，改为 `no_damage`
- [x] `spells` 每行的 `kind`（damage、healing、debuff）不能当过滤参数用（只认 attack、heal、control）：两种都认
- [x] 施法被游戏拒绝时的提示从 `the cast failed` 改为说明常见原因
- [x] `spells` 也改成一行一个（`Projectile_FireBolt 火焰箭 (damage; action; 18 m)`），影心的列表 9161 字符 → 4568
- [x] `wait` 只带简短状态（HP、战斗、回合、对话、人类的距离），完整的用 `status`：一次约 600 字符 → 110
- [x] `inventory` 也一行一件（`e13 高等治疗药水 x2 (potion, heals)`，装备 `Helmet: e31 博德安之盔`）：影心默认清单 2147 → 972 字符
- [x] `combat` 的 `order` 也一行一人（`>> e1 影心 (you; HP 33/86; init 9; …)`，`>>` 是当前行动者）：实测 867 → 461 字符
- [x] `immune_to` 里状态组（`SG_Blinded` → Blinded）和单个状态（目盲）重复：单个状态的 `StatusGroups` 已含这个组时不再列组
- [x] bridge 被 SIGTERM 结束时开发隧道不再残留
- [x] 新事件 `noticed`：agent 的被动检定（`RollResult`，`isActiveRoll = 0`，如 `GLO_CONST_HiddenItemCheck`）成功时报告发现了什么、在哪；守则让它去看、提醒人类陷阱
- [x] `wait` 的事件也换成短 id（原来是完整 GUID，以前的事件碰巧都不带 id）
- [x] 新动作开始时，还在跑的旧任务标成 `replaced`（原来一直是 running）；结束 10 分钟以上的任务从表里删掉
- [x] 战斗外的回合制模式（人类按了回合制按钮）：`status`/`wait` 标 `turn_based`，`move` 按剩余移动力检查并说明（原来只报「被挡住」），`end_turn` 可用

### 潜行

- [x] 视野锥：NPC 的 `Sight`（距离）、`FOV`（视角）和朝向（`RotationQuat` 作用在 -Z 上），墙体用 `Ext.Level.RaycastAny` 判断；新工具 `sight` 列出附近人的朝向、视野锥、是否看得见你或某个点，给出没人看着的落脚点（只算 agent 自己看得见的人）
- [x] `sneak`：开关潜行（`Shout_Hide`），站在别人视野锥里时先拒绝；`status` 带 `sneaking`；被发现时 `wait` 收到 `stealth_lost`
- [x] `move(sneak=true)`：出发前用引擎寻路的路线检查会不会经过视野锥，边走边看前方，快进锥就停下
  - [x] 实测（2026-11-04，下城区，阿维斯）：走进视野锥的路线出发前被拒绝；下楼途中走到锥边自动停下、潜行没掉；`even_if_seen` 硬走进去被发现，任务失败并收到 `stealth_lost`
  - [ ] 没测：战斗中隐匿（扣动作/附赠动作）、黑暗和光照对视野的影响（`Darkness.Obscurity`）、视野距离边缘是否正好 16 米、敌对 NPC 发现后的反应
- [x] 守则：什么时候潜行、被发现了怎么办
- [x] 交易：新增 `trade`，走游戏原生交易窗口（`PROC_StartTrade` + `TradeItemCommand`，价格由游戏算）。每次先问人类同意，再问一起交易（窗口照常显示）还是 agent 自己交易（窗口隐藏，游戏藏起的 HUD 放回来，买卖完注入 Esc 关掉）；人类自己在交易时拒绝
  - [ ] 实机让人类点一次两个问题，看隐藏时窗口会不会闪一帧，后台交易那一两秒里人类能否照常操作
- 扒窃：不做（2026-11-04 决定）。原生入口是剧本的 `RequestPickpocket` → `StartPickpocket(玩家, NPC, 1)`，扒窃窗口只对人类选中的角色弹出，服务器端没有能直接调用的偷窃函数。已禁止 `container`/`take` 绕过检定翻活人口袋

### 最终测试发现的问题（2026-11-04，哀伤之邸）

按顺序做：先小问题，再 `look` 的可见性和条数，最后寻路（可见性的后备做法也要用寻路）。

- [x] 小问题（2026-11-04，client v25、server v55）
  - [x] `said` 去重：现在只和上一句比，对话框先出「A」「B」、History 后补「米瑞亚: A」时 A 记两次。改成每段对话记住所有说过的句子（按去掉说话人的文字比），保留带名字的那条
  - [x] 自己选的回答在 `said` 里显示成「Saber: …」：`choose` 记下选的文字，History 里出现时说话人改成 agent
  - [x] agent 的动作（`use`、`talk`、`cast`）之后几秒内开始的对话算 agent 的（坐长椅触发的心灵绘图被判成人类的，`choose` 拒绝）
  - [x] `use` 的结果：除了物体状态，还要看自己是否被传送（位置跳很远）、是否开始对话或战斗、附近是否冒出新东西（如秘密阶梯）。现在这些都报「no visible change」
  - [x] 实机验证对话（2026-11-04，和米瑞亚）：去重、回答显示成「影心: …」、屏幕上那句不重复，都正常
  - [x] 实机验证 `use` 触发对话和传送（2026-11-04 读档重走哀伤之邸）：长椅 → `dialogue: true`、`yours: true`，心灵绘图能 `choose`；秘密阶梯 → `moved_m` 1600。`appeared` 实机没碰到合适的场景（阶梯是对话结束后才出现的），只有离线测试
- [x] `look` 的可见性改成「人类屏幕上能不能看到」（2026-11-04，server v62）
  - 规则（用户实测）：只和是否封闭有关。门窗全关的房间里面看不到；只要有门或窗开着，离多远都能看到里面。和室内室外、角色视线无关。潜行的人仍按角色视线
  - 做法 A 不行：客户端显示组件（`Visual.VisualFlags`/`CullFlags`）是静态配置，40 米内加载的物体都有，看不出这一帧有没有被剔除。游戏的房间状态在 `eoc::room_portal::RoomStateComponent` 里，SE 没映射，读不了
  - 改用房间触发器（`ServerRoomTrigger`，盒子或多边形柱体）：目标在某个房间里、人类和 agent 都不在里面、房间墙边 1.5 米内的门窗（`IsDoor` 或名字带窗/window/shutter）全都 `IsOpened = 0` 时算看不见；找不到门窗的房间算开着。不用寻路
  - 实测（哀伤之邸）：关上门厅里外两扇双开门，门厅里的米瑞亚、莫兰、威尔伯和 29 件物品从 `look` 消失，重新打开后完全恢复
  - [ ] 没实测：带窗户的房间、多层建筑、人类在屋外看关着的房子；让用户看屏幕确认判断和画面一致

- [x] `look` 按条数而不是固定距离控制上下文（2026-11-04，server v61）
  - 默认半径和察觉距离都改成 40 米，从近到远按重要程度加，到约 30 条为止：人（敌人、能对话的、商人、队友）> 门、楼梯、梯子、容器、可拾取物 > 其他可用物体 > 家具、蜡烛、火把、「物体」「铰链」。排序用「距离 + 每低一档加 12 米」
  - 剩下的放进 `farther`，按方向和距离段一行（「NW 25-40 m: 2 people, 6 containers」）；同名的小东西 3 个以上合并（「e11 铁制大烛台 x6 (usable, 3.4-9.2 m, nearest NW)」，带最近那个的 id）
  - 保留「只列变化」；人类和战斗中的敌人总列出
  - [ ] 没实测：室外物品多的地方（实测只在哀伤之邸室内，30 条正好装下）、40 米是否合适
- [x] 寻路：出发前先问游戏能不能到（2026-11-04，server v57）
  - 用法（实测）：`BeginPathfindingImmediate(实体, 坐标)` 后直接 `FindPath`，同步返回，1–70 ms；`FindPath` 之前改 `CloseEnoughMax`（路线终点离目标的平面距离上限，设大了就停在能到的最近点）、`CheckLockedDoors = false`（穿过锁着的门）、`CanUseLadders = true`。第一次 `GoalFound=false` 是因为目标点不在可走的格子上：物体自己占着格子、门的中心在墙里、高度不对都会失败，所以同时试 `FindValidPosition` 找的站位和那个位置的其他楼层高度。`ErrorCause` 没用（成功也是 3，脚下没地面是 5）
  - [x] `move`/`use`/`talk`（还有 `trade`）出发前算路线：到不了就立刻失败，说明原因（锁着的门并给出是哪扇 `blocked_by`、要梯子、要跳跃或在墙里），`nearest` 给出最近能走到的点
  - [x] 按方向走时在那个方向上挑一个真正走得到、不用绕远路的最远点；那边全是墙或悬崖就直接报错
  - [x] 走向物体时按计划的终点坐标走（`CharacterMoveToPosition`），不再 `CharacterMoveTo(物体)`。`regroup` 后「走过去又被拉回来」的原因是链接跟随：停下后游戏把影心带回人类身边。现在走路前还和人类链着就先解除，结果里 `unchained` 提醒用完 `regroup`
  - [x] `explore.unexplored` 只列走得到的方向；绕路比直线远 5 米以上时附上实际路程（「N (25 m, 41 m on foot)」）。同一位置一分钟内用缓存
  - [x] 实测（2026-11-04，server v66）：长椅走到差 1.0 米、门差 1.1 米。招牌挂在门上方 4 米，原来报走不到，改成附近 3 米内没有地面时走到它正下方。游戏走路自己会爬梯子（8 米，不开梯子要绕 85 米），规划时改为总是 `CanUseLadders`，去掉「需要梯子」的报错。移动力不能交给游戏：脚本走路不受移动力限制（剩 0.6 米照样走完 4.6 米），所以出发前仍要检查；需要的移动力改用寻路最后一个节点的 `Distance`（回合制下鼠标显示的那个数，爬梯子不算），实测 5.92 对实际 6.0
- [x] 地图理解：让 agent 知道往哪走（2026-11-04，server v60、client v26）
  - [x] 边界点：`explore.unexplored` 改成最近的至多 3 个「走得到、紧挨没去过区域」的点（坐标可直接 `move`，带方向、直线距离、路程、经过的门、上下几米）。16 个方向 × 25/50 米问寻路（`SearchHorizon` 8000 封顶），路线上第一个没去过的格子就是边界点，相距 12 米内的合并。路线按位置缓存一分钟，每次 look 最多问 120 毫秒（还没找到就到 240），没问完的下次接着问
  - [x] 出口标注：`look` 里门、梯子、楼梯、传送门、活板门（按名字和模板认出楼梯等）标出走不到的原因（锁门说明是哪扇）、`leads up/down N m`（同一位置的另一层地面）和 `unexplored beyond`（门后 6 米的格子没去过，或某个边界点的路线经过这扇门）
  - [x] 任务方向：客户端地图的视图模型 `CurrentPlayer.WorldMap.Markers` 里 `Type = QuestMarker` 的就是任务标记（世界坐标、高度、任务标题），地图不打开也有。`quests` 返回全部 `markers`（距离、方向、坐标），`look` 的 `explore.quest_marker` 给最近的一个
  - [x] 实测（2026-11-04）：梯子的 `leads`（落脚点在梯子旁边 1 米，改为也看周围一圈，「多节树根」`leads up 5 m`）；队友走到边界点后那个点消失、换成更远的
  - [x] 实测锁门（2026-11-04，铁栅栏，server v67）：标 `locked`；边界点的路线挨着锁门出发时误写「through 铁栅栏」，改为锁着的门不算经过
  - [ ] 没实测：锁着的门后面的楼梯、梯子标「can't get there」（附近没找到这种地方）
- [ ] 闪退：米瑞亚对话里 `choose` 时闪退一次（转储：`bg3_dx11.exe` 内空指针读取，无符号），读档同样操作没复现。怀疑 client v22 每 30ms 读对话框，没证实。再闪退时对比关掉轮询的情况

### 战斗实测发现的问题（2026-11-04，奥林，硬核难度）

修复都在 server v71，离线测试覆盖；第二场实测（同日，v71–74）确认了大部分，见最后一项和下一节。

- [x] 回合开始时强制喂数据：轮到 agent 后，不管它调的是哪个工具，第一个结果都带 `your_turn`（完整战况）和截图，每回合一次（`turn_check` 按回合计数判断，读档后计数重来也不会漏）
- [x] 开战时自动读一遍所有敌人：`combat` 的敌人行带等级、AC、HP、抗性/免疫、状态、专注；被动特性（`enemy_traits`）每场战斗第一次列出时给一次，随第一回合的 `your_turn` 一起到
- [x] 战斗中持续记录：agent 回合结束时给所有人拍快照，下回合 `changes_since_your_last_turn` 逐人列出 HP 变化、新上/到期的状态、倒地/死亡/站起来、加入（召唤物、援兵）和离开战斗的人
- [x] 人物死亡要知道：倒地后死亡豁免失败死掉，Osiris 不再发 `Died`。改为每次 `wait` 轮询和倒地状态移除时检查队伍，新死的报 `died`（人类带 `human: true`），每人只报一次；`status.human` 有 `downed`/`dead`
- [x] 回合之外发生的事记全：上面的死亡检查也写进 `since_your_last_turn`，其余变化由快照对比补全
- [x] `combat` 的 `order` 里倒地或死亡的人类整行消失：队伍里倒地或死亡的人不管游戏还算不算在战斗里都列出，标 DOWNED / DEAD
- [x] `cast` 对无效目标不拦：目标已死亡、法术条件写着 `not Dead()` 或是治疗法术时拒绝，不花资源；复活、交谈亡魂、操纵死尸照常（实机核对了这几个法术的条件）
- [x] 以自己为中心的范围法术（Shout）：传了 `target` 时丢掉并在结果里说明，结果列出半径内的人（`around_you`）；治疗类在半径内没有受伤的队友（含自己）时拒绝，并报出队友多远；`spells` 写「no target: around you within N m」。治疗看法术效果里有没有 `RegainHitPoints`：实机发现黎明曙光（伤害技能）的 VerbalIntent 也是 Healing
- [x] 召唤物的控制：`spells`/`move`/`cast`/`end_turn`/`stop` 带 `summon`（短 id 或名字）就由召唤物来做，资源扣在召唤物身上；召唤物的回合开始时 `wait` 报 `summon_turn`；`combat` 有 `your_summons`（是不是它的回合、剩余资源）。召唤物从召唤者的 `SummonContainer` 读
  - 不再需要 `set_agent` 切过去，所以 persona 错位的问题没了；「已结束回合」改为每个角色分开记，召唤物结束回合不会让 agent 自己显示 `my_turn: true`
- [x] 战斗记录里召唤物造成的伤害记成召唤者：`AttackedBy` 的第二个参数是召唤者，第三个才是动手的；现在写「使徒 (your summon)」
- [x] 核实：`status.human.dist` 和 `cast` 结果里的 `pos`：实机比对 `Osi.GetPosition` 和实体坐标一致，不是旧值。`cast` 结果里的 `pos` 是施法者自己的位置（影心没动，所以一直不变），容易误读，已从 `cast` 结果里去掉
- [x] 核实：施放异界誓盟时影心自己走了 3.8 米：`cast` 结果在被游戏挪动时给出 `moved_m`。原因后来查明（下一节 d）：召唤法术不能以角色为目标
- [x] 实机战斗验证（第二场）：`your_turn` 和截图每回合第一个结果带一次、`changes_since_your_last_turn`、召唤物用 `summon` 施法和结束回合、召唤物的伤害记在它名下、召唤物结束回合不影响 agent 的 `my_turn`、Shout 对不受伤的队伍拒绝、`spells` 的 around you 半径都正常
  - [ ] 还没碰到：人类倒地后死亡的 `died`、对死人施法被拒

### 第二场战斗实测发现的问题（2026-11-04，奥林，硬核难度）

server v72–76，离线测试覆盖（`uv run pytest` 174 个、Python 3.10 168 个 + 6 个跳过）。v76 已注入，只在非战斗时核对了游戏数据，战斗中的部分见最后一项。

- [x] 召唤物找不到：`SummonContainer.Characters` 是空的（炽焰法球在 `Items` 里），`IsSummon.Owner` 指向召唤物自己。改为再用 `Osi.CharacterGetOwner(u) == agent` 找（v72 实机能找到）
- [x] Shout 用 `UseSpell(me, spell, me)` 只作用于施法者：群体治愈真言没奶到 17 米外的 Saber。改成在施法者脚下 `UseSpellAtPosition`，v74 实机奶到了 Saber 和卡菈克
- [x] 治疗类 Shout 的「受伤」：HP 低于 90% 才算（之前 85/86 也算）
- [x] 状态名去重，`combat` 每行最多 12 个：「难度：硬核」重复两次挤掉了奥林的「不可撼动」。头像上不显示的状态（`DisablePortraitIndicator`：难度：硬核、蝌蚪能力的移位）不再列出
- [x] `status` 有 `summon_turn`（正在行动的召唤物名字）
- [x] a. 按位置施放的法术（Shout、炽焰法球）不触发 `UsingSpellOnTarget`，战斗记录里少了「you cast」：在 `CastedSpell` 里补记，Shout 写上半径内的人；之后再来的按目标事件并进同一行
- [x] b. 敌人状态只有名字：`combat` 加 `status_effects`，敌人状态的简短说明（状态的 Description），每场战斗每种一次
- [x] c. 同类敌人（巴尔之镰×6）特性每人一行：同一组特性合成一行「巴尔之镰 x6 (e3, e4, ...): ...」，之后再列出的同类不再重复
- [ ] d. 施放炽焰法球（目标 13 米外的敌人，射程 18）影心自己走了 4.2 米（实机仍会走，见下）：召唤法术（炽焰法球、异界誓盟、信仰守卫）带 `CannotTargetCharacter`，条件是 `not Character()` 和 `CanStand`，以角色为目标是无效目标。`target` 给角色时改为施放在目标身前 1.5 米的空地上（离施法者近的一侧、在射程内），结果 `note` 说明
- [x] e. `changes_since_your_last_turn` 里一闪而过的状态：跳过 `DisableCombatlog` 的（巨武器大师：附赠攻击）和只解锁一个动作的（`Boosts` 只有 `UnlockSpell`：武艺：徒手打击）
- [x] f. 卡菈克的伤害很多是 `damage 1`：一次攻击按伤害类型各发一次 `AttackedBy`（推测是砍伤加火焰）。同一人打同一人 300 毫秒内的合成一行、伤害相加（实机没核对参数，离线测试按这个假设）
- [x] g. 召唤物被游戏挪动时 `why_moved` 写召唤物的名字，不写 you
- [x] 实机战斗验证（第三场，v76，奥林战打赢）：湮灭波、群体治愈真言在脚下放能打到 / 奶到半径内所有人（7 米外的 Saber 从 1 奶到 50）；「you cast 湮灭波」记录带范围内的人；`status_effects`（不可撼动、庇护术等）和同类敌人特性一行都在第一回合的 `your_turn` 里；奥林身上一次湮灭波记成一行 `damage 2`（光耀 1 + 雷鸣 1，合并正确）
  - [ ] 精魂守卫没用上，没验证
- [x] d 修好了（server v86）：落点和视线无关（召唤物在射程内能站人的地方都能放），是 `Osi.UseSpellAtPosition` 的请求会让施法者先挪位置（实测 1.0 米、0.45 米，第二次吃了奥林的借机攻击倒地；人类从界面放不会动）。召唤类法术的施法请求加 `NoMovement`。实测：施法前后位置不变，法球照常放出
  - [x] 施法时挨打：游戏先报失败、攻击后到，等 0.4 秒再出结果，写明谁打了你、什么都没扣、可以再试（v88）
  - [ ] 别的法术也会被游戏拉着先走到射程内（守则里写了 `moved_m`）；要不要全部加 `NoMovement` 或 `AvoidAoO`，没定
- [x] 跳跃（v88–91）：v86 把带 `CannotTargetCharacter` 的跳跃也加了 `NoMovement`，游戏一直拒绝，改为 `IsJump` 不算召唤；去掉 `IgnoreCastChecks` 时游戏会先走一段再跳（9 米移动力用光），改为跳跃保留施法检查选项，距离（法术射程 + 力量每高 10 两点加 1 米，负重减半）和落点地面自己查；结果报 `jumped_m`。实测：直接跳 6 米，扣附赠动作和 3 米移动力
- [x] 借机攻击预警（v89–90）：战斗中 `move`、跳跃、目标超出射程（游戏会先走过去）时，终点离开敌人近战范围（中心距 2.5 米）、敌人有反应且没失能、自己没撤离，就先拒绝一次并列出敌人；同一位置、同一终点、同一批敌人再调一次就放行（远程被贴身有时只能吃一下再撤，v92），`even_if_provoking` 一次就放行；守则写了跳出近战范围也会被打断、什么都不扣、可以再跳
  - [x] 实测（卡菈克贴着奥林、受威胁）：`move`、跳跃、近战打 9.6 米外的希拉都先拒绝，提示奥林会借机攻击，没动没扣资源；超射程走过去的终点是按直线估算的
- [ ] 命中率、优劣势：游戏只在人类瞄准时算（客户端 `CurrentPlayer.UIData.HitChanceDesc`：TotalHitChance、BaseHitChance、Advantages、Disadvantages、Modifiers），SE 没开放计算函数。用户决定先不做；要做就自己按规则估算，用人类瞄准时的数据核对
- [x] 影心开战后才被拉进战斗时，`combat_started` 不发（`CombatStarted` 那一刻她还不在战斗里）：`events` 每次轮询看 agent 是否进了新的一场（`CombatGetGuidFor`），是就补发并像开战一样重置战斗记录；同一场不重复发（server v77）
- [x] 隐身的敌人（巴尔之镰藏起来）在 `changes_since_your_last_turn` 里写成「out of the fight」：还活着、还在战斗里的写「hidden (still in the fight)」；`order` 里照旧不列看不见的人（v77）
- [x] 治疗类 Shout 结果里的 `around_you` 也列出敌人，看着像奶了敌人：治疗类只列队友（v77）
- [x] 游玩守则补基础规则（只写确定的）：身边有敌人（受威胁）时远程攻击和法术攻击掷骰有劣势、离开近战范围引发借机攻击（撤离可免）、豁免类法术不看 AC、庇护术不能直接指定但范围法术能打、同时只能专注一个法术、恐惧时不能移动且攻击劣势。起因：agent 走到奥林身边放灼热射线，自己猜了倒地规则还猜错。倒地对远程的影响、高地加值没写，要实机核对后再补

## 第 5 阶段：插件和公开

- [ ] 配置 GitHub 远程仓库，验证 Actions 在 `windows-latest` 上能通过（开发到一定进度再做）
- [x] dsh 插件按官方包清单整理（`dsh.manifestVersion`、`engines.dsh`、`icon`、`locale/*.json` 显示名）。dsh 插件管理器只收 pnpm 能装的 spec，不收 zip，所以 Release 里放 npm tarball `dsh-bg3coop-X.Y.Z.tgz`，用 `dsh plugin add <地址>` 或插件页「添加插件」安装。本机临时 DSH_HOME 实测 tgz 能装上、自动启用、合成配置里有 `mcp-bg3coop`
  - [x] 本地写好 `integrations/dsh/`：`package.json` + `cordis.patch.yml`（插入一个 `@deepseek-ai/dsh-mcp-client`，`toolCallTimeoutMs` 180 秒）。当时的 dsh-mcp-client 不读服务器 `instructions`，所以加了 `rules` 工具返回守则（0.2.x 已会读，`rules` 留给旧版）。安装说明里留了手动改 profile 补丁文件的后备做法
  - [ ] Windows 实测：桌面版插件页装 Release 地址；dsh 清理过的环境变量里 `uvx` 能否启动
- [x] Claude Code 插件，加上 `marketplace.json`（`/plugin marketplace add <用户>/<仓库>` 就能装）：`integrations/claude-code/` + 根目录 `.claude-plugin/marketplace.json`。启动命令 `uvx --from <Release 里的 wheel> bg3coop-mcp`，本机用打好的 wheel 实测能启动、列出 33 个工具
  - [ ] 仓库公开后实测 `/plugin marketplace add` 和安装
- [x] Codex 接入：最少提供 `codex mcp add` 命令；插件格式按当时的官方文档定：README 和安装说明给 `codex mcp add bg3 -- uvx ...`，并提示加 `tool_timeout_sec = 180`（`ask` 最多等 120 秒）。插件按官方文档整理：`codex plugin marketplace add <用户>/<仓库>` + `codex plugin add bg3coop@bg3-coop-agent`。新的可移植格式（根目录 `plugin.json` + `mcp.json`）不能写超时，所以用官方仍支持的 `.codex-plugin/plugin.json` + `.mcp.json`，在里面写 `tool_timeout_sec = 180`、`startup_timeout_sec = 120`（本机 Codex 0.166 临时 CODEX_HOME 实测生效）
  - [ ] 仓库公开后实测从 GitHub 添加市场和安装
- [x] `docs/install-for-agents.md`：写给 agent 看的安装步骤，用户对自己的 agent 说一句"按这个装"就行
- [x] GitHub Actions：打 tag 后自动构建 wheel 和三个插件，附到 Release 上（`release.yml`，未验证）。版本号只改 `pyproject.toml`，`scripts/release.py sync` 同步插件、README 和安装说明里的版本和 wheel 地址，`check` 在发版时核对 tag，`pack` 打 Claude Code 插件 zip 和 dsh 的 tgz（Codex 只从市场装）
- [x] README.en.md，写明测试过的游戏版本和 Script Extender 版本（游戏 4.1.1.7631656 DX11、SE v33，中英 README 都写了）
- [x] 安装不绑死 uv：Python 下限放宽到 3.10（3.10/3.11 离线测试通过），`docs/install-for-agents.md` 改成「要求 + 装好后的入口 + 验收标准」，让 agent 按电脑上已有的 uv/pipx/Python/conda 选装法；Windows 上 venv + pip 装 wheel 实测 `doctor` 全 OK、两种 MCP 启动方式都列出 33 个工具
- [x] 版本检查：`doctor` 和 MCP 服务器（后台查一次，第一次工具返回带 `update`）对比 GitHub 最新 Release，查不到就跳过。插件和 wheel 永远同版本发布（写进 `AGENTS.md`）
  - [ ] 仓库公开、有 Release 后实测 GitHub API 能查到版本
- [ ] 公开前多跑几轮实机测试，留意之前出现过的那次闪退

## 以后再说

- 多个 agent 各控制一名队友（游戏侧的 `C.agent` 要改成列表）
