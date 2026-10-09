---
name: iphone-use
description: 操作真实 iPhone，默认开启 Midscene 单步动作与报告，不调用内部 AI；可关闭回到 PUA，或另行开启 ChatGPT 授权的 AI 自动执行。支持持久开关、初始化、实时屏幕及认证接管。
---

# 完成 iPhone 任务

每个任务先调用一次 `pua_midscene(action="settings")` 读取持久模式，不需要设备连接、Node 或授权。仅用户要求时附加 `mode` 切换：

面向用户只解释“Midscene 开关”和高级选项“AI 自动执行”，不要求用户选择三个技术模式。以下值仅用于工具路由。

- `off`：使用 [PUA 操作](references/pua-fallback.md)，不查授权，不生成 Midscene 报告。
- `steps`（默认）：当前聊天模型看图决策，Midscene 执行明确动作并记录报告；即使已授权，也不使用 act/assert。
- `ai`：读取 [操作与授权](references/midscene.md)，检查 auth_status，授权后使用 act/assert。未授权时说明单独授权和额外用量，由用户在官方页面完成；不复制宿主凭据。

“开启 Midscene”选 steps；“开启 AI 自动执行”选 ai；“关闭 AI 自动执行”选 steps；“关闭 Midscene”选 off。授权与模式独立，登录不改变模式；关闭保留登录和报告。新安装或升级未设置偏好时使用 steps，不从授权推断开启 AI；已保存的 off 或 ai 保持不变。正在执行时等待完成再切换，不重放不确定动作。

渐进引导只在需求相关时出现：需要回放、排查时介绍单步报告的截图、操作和耗时记录，说明它不新增内部模型请求；需要多步自动执行或视觉核验时再介绍 AI 模式的额外授权和用量。不承诺更快、更省或必然成功。用户拒绝或关闭后不反复建议、不自动重开。

用户明确要求“仅这次”时，保存原模式，临时切换；任务成功、失败或取消后恢复原模式。中断后发现未恢复时，先告知并恢复。普通切换持久保存。

## READY 与认证

正常任务在本对话首次使用手机时，默认调用 `pua_ready(recover=true, screenshot=false)`；文字任务保留 status / session / tree / viewport / 解锁检查，无需额外截图。已有本对话 READY 且通道未失效则直接复用，不为每步重验。`recover=false` 仅用于用户明确禁止重启或明确要求只读诊断，不能因谨慎主动设置或自动覆盖用户限制。

- `ready=true, state="ready"`：通道已可用。off 复用 READY 观察；steps 取一次 Midscene screenshot；ai 按任务调用 act/assert。不额外调用 doctor。
- `ready=false, state="recovering"` 或 `state="recovery_required"`：没有 error、MCP isError=false，仍不表示手机可操作。按 [启动与恢复](references/startup.md) 查询同一工作或按用户限制处理。
- READY 返回 `pua_unreachable`、连接拒绝、`not_ready` 或明确服务未启动：这是启动分支，不是整个任务失败。`recover=true` 不会自动冷启动；调用 `pua_setup(action="status")`，复用活动中的 start / recover 工作，或在已配置且没有活动工作时 start 一次，服务就绪后重验 READY。逐步做法见 [启动与恢复](references/startup.md)，缺少配置 / 源码 / 构建时读取 `iphone-use-setup`。

只读、禁止启动 / 重启等用户限制始终保留。恢复后复用 READY 的新观察了解原任务进度，不能重放可能已经生效的业务动作。

READY 关联手机屏幕侧边栏，宿主支持时默认打开或复用本聊天已有面板；重复 setup / 恢复通道、暂停 / 恢复预览沿用同一个 widget。已有面板时直接继续，不为刷新再调用屏幕打开工具；需要重新打开已关闭的面板时调用一次 `pua_screen()`，不要为打开画面重复 READY。用户要求“先打开 widget 让我看”时先打开，再继续初始化与已授权任务；只有明确要求等他确认再操作时才等待。widget 顶部显示机型和 Live 状态，底部的刷新 / 主屏幕 / 截图三个按钮只供用户自己点击，不是模型的工具：不要调用仅供 App 使用的 `pua_screen_frame` 和 `pua_screen_action`，不要为刷新预览增加轮询、截图或 observe。用户点过主屏幕后页面会变，按下一次观察到的实际状态继续。画面留空、光效或 cursor 都不证明 READY、动作成功或任务完成，也不是模型观察。预览问题按 [屏幕通道说明](references/screen.md) 排查，不为它反复恢复控制通道。

App 实际要求密码、PIN、验证码、Face ID / Touch ID，或手机需要用户解锁时，按 [认证接管与恢复](references/authentication.md) 等用户完成。App 认证先 `pua_screen(action="pause")`；`phone_locked` 已自动暂停为 `device_locked`，不要再用显式 pause 覆盖原因。必须调用宿主提问工具（Default 优先 `functions.request_user_input_async`），首个选项固定「已完成继续」，第二个可为「暂时无法完成」。异步返回 / 预选不是用户答复；接管期间暂停手机动作、读取和截图，不索取凭据。实际完成通知后，App 认证或旧版未知暂停先 `pua_screen(action="resume")` 再取新观察；设备解锁则重验 READY，成功时仅自动解除同一次锁屏暂停。READY 的 `preview.paused` / `pause_reason` 说明预览状态；不能把 READY 成功当成 App 认证已完成。根据新状态继续剩余工作。

## Midscene 执行与报告（仅 steps / ai）

ai 模式且已授权时，在 READY 后用 `act, text="具体任务和约束"` 执行，查看截图，再用 `assert, text="可观察的完成条件"` 核验；保持同一 report_id。以下单步规则仅用于 steps 模式。

READY 后读取 [Midscene 操作参数](references/midscene.md)。先调用 `pua_midscene(action="screenshot")`，保存返回的 `report_id`。同一任务后续每次调用都传这个 ID，新任务使用新 ID。每次只执行一个动作，查看返回截图后再决定下一步。查询页面和断言由当前聊天模型根据截图完成；最终使用 `action="record", text="实际观察及结论", passed=true/false` 记录验收。不得为了得到成功报告而将未确认的结果记为通过。

坐标使用 iPhone 点：截图像素乘以返回的 `image.pixel_to_point`，不能直接使用 Mac widget 坐标。搜索栏、标签栏或键盘后可见的文字可能被遮挡，先滑动到无遮挡区域再点；页面未变化时重新观察，不反复点击同一位置。输入仅追加单行文本，不清空、不自动提交；需要替换时先通过可见控件处理原内容。发送、购买等有外部影响的操作仍需用户任务授权，不能把输入成功当成提交成功。

`ok` 或 `action_complete` 只表示单次操作完成。完整任务需要确认最终页面和实际结果。失败先查看返回的最新截图，缺失时取一次新的 `screenshot`；不因超时重放动作。用户完成认证后从实际状态继续，不能重放整个任务。steps 报告记录宿主决策，不代表独立 AI 验收；ai 模式的 assert 才是真正的 SDK AI 断言。

最终说明完成结果和未完成项，给出 `report_id` 与 HTML `report` 路径。多个独立进程的记录可累积到同一报告；普通 PUA 调用不计入该报告。保持简短进度，完成所有已授权步骤后再结束。

## 安装、连接和回退

`pua_ready`、`pua_setup`、`pua_apps`、`pua_screen` 继续负责连接、安装、查找 App 和预览，不参与动作规划。未知 bundle ID 用 `pua_apps` 查询，不能猜测。SDK 缺失时按指南安装，无需模型密钥。预览说明见 [屏幕通道](references/screen.md)。

off 模式直接使用 [PUA 操作](references/pua-fallback.md)。其他模式下，用户指定 PUA 或 Midscene 不支持所需操作时，说明原因再回退。不要静默切换，也不要在不确定动作后换工具重做。工具绑定不可用时按 [工具故障与代码调用](references/tool-fallback.md) 调用当前模式对应入口，保留设备锁和报告 ID。
