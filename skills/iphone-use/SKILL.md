---
name: iphone-use
description: 默认使用 Midscene 操作真实 iPhone；可通过 ChatGPT 授权启用 aiAct 和 aiAssert，无需 API Key。复用 PUA 连接，同一 report_id 累积 HTML 报告。支持初始化、App 操作、实时屏幕及认证接管。
---

# 用 Midscene 完成 iPhone 任务

用户无需指定 Midscene。先读取 [Midscene 操作与授权](references/midscene.md)，用 `pua_midscene(action="auth_status")` 检查模式：已获 ChatGPT 推理授权时默认用 `act` 执行有明确边界的任务、`assert` 核验结果；没有授权时采用当前聊天模型看图、执行明确动作的流程。登录入口是 `auth_login`，由用户在官方页面完成登录及额度授权；不读取或复制宿主凭据。仅 `act` / `assert` 调用 SDK 内部 AI 接口，明确动作和 `record` 不可冒充 AI 推理或断言。

## READY 与认证

正常任务在本对话首次使用手机时，默认调用 `pua_ready(recover=true, screenshot=false)`；文字任务保留 status / session / tree / viewport / 解锁检查，无需额外截图。已有本对话 READY 且通道未失效则直接复用，不为每步重验。`recover=false` 仅用于用户明确禁止重启或明确要求只读诊断，不能因谨慎主动设置或自动覆盖用户限制。

- `ready=true, state="ready"`：通道已可用。然后调用一次 `pua_midscene(action="screenshot")` 获取视觉控制的首帧和报告 ID，不额外调用 doctor。
- `ready=false, state="recovering"` 或 `state="recovery_required"`：没有 error、MCP isError=false，仍不表示手机可操作。按 [启动与恢复](references/startup.md) 查询同一工作或按用户限制处理。
- READY 返回 `pua_unreachable`、连接拒绝、`not_ready` 或明确服务未启动：这是启动分支，不是整个任务失败。`recover=true` 不会自动冷启动；调用 `pua_setup(action="status")`，复用活动中的 start / recover 工作，或在已配置且没有活动工作时 start 一次，服务就绪后重验 READY。逐步做法见 [启动与恢复](references/startup.md)，缺少配置 / 源码 / 构建时读取 `iphone-use-setup`。

只读、禁止启动 / 重启等用户限制始终保留。恢复后复用 READY 的新观察了解原任务进度，不能重放可能已经生效的业务动作。

READY 关联手机屏幕侧边栏，宿主支持时默认打开或复用本聊天已有面板；重复 setup / 恢复通道、暂停 / 恢复预览沿用同一个 widget。已有面板时直接继续，不为刷新再调用屏幕打开工具；需要重新打开已关闭的面板时调用一次 `pua_screen()`，不要为打开画面重复 READY。用户要求“先打开 widget 让我看”时先打开，再继续初始化与已授权任务；只有明确要求等他确认再操作时才等待。widget 顶部显示机型和 Live 状态，底部的刷新 / 主屏幕 / 截图三个按钮只供用户自己点击，不是模型的工具：不要调用仅供 App 使用的 `pua_screen_frame` 和 `pua_screen_action`，不要为刷新预览增加轮询、截图或 observe。用户点过主屏幕后页面会变，按下一次观察到的实际状态继续。画面留空、光效或 cursor 都不证明 READY、动作成功或任务完成，也不是模型观察。预览问题按 [屏幕通道说明](references/screen.md) 排查，不为它反复恢复控制通道。

App 实际要求密码、PIN、验证码、Face ID / Touch ID，或手机需要用户解锁时，按 [认证接管与恢复](references/authentication.md) 等用户完成。App 认证先 `pua_screen(action="pause")`；`phone_locked` 已自动暂停为 `device_locked`，不要再用显式 pause 覆盖原因。必须调用宿主提问工具（Default 优先 `functions.request_user_input_async`），首个选项固定「已完成继续」，第二个可为「暂时无法完成」。异步返回 / 预选不是用户答复；接管期间暂停手机动作、读取和截图，不索取凭据。实际完成通知后，App 认证或旧版未知暂停先 `pua_screen(action="resume")` 再取新观察；设备解锁则重验 READY，成功时仅自动解除同一次锁屏暂停。READY 的 `preview.paused` / `pause_reason` 说明预览状态；不能把 READY 成功当成 App 认证已完成。根据新状态继续剩余工作。

## 默认执行与报告

已授权模式在 READY 后用 `act, text="具体任务和约束"` 执行，查看返回截图，再用 `assert, text="可观察的完成条件"` 核验；保持同一 report_id。以下单步规则用于未授权的明确动作模式。

READY 后读取 [Midscene 操作参数](references/midscene.md)。先调用 `pua_midscene(action="screenshot")`，保存返回的 `report_id`。同一任务后续每次调用都传这个 ID，新任务使用新 ID。每次只执行一个动作，查看返回截图后再决定下一步。查询页面和断言由当前聊天模型根据截图完成；最终使用 `action="record", text="实际观察及结论", passed=true/false` 记录验收。不得为了得到成功报告而将未确认的结果记为通过。

坐标使用 iPhone 点：截图像素乘以返回的 `image.pixel_to_point`，不能直接使用 Mac widget 坐标。搜索栏、标签栏或键盘后可见的文字可能被遮挡，先滑动到无遮挡区域再点；页面未变化时重新观察，不反复点击同一位置。输入仅追加单行文本，不清空、不自动提交；需要替换时先通过可见控件处理原内容。发送、购买等有外部影响的操作仍需用户任务授权，不能把输入成功当成提交成功。

`ok` 或 `action_complete` 只表示单次操作完成。完整任务需要当前模型确认最终页面和实际结果。失败先查看返回的最新截图，缺失时取一次新的 `screenshot`；不因超时重放动作。用户完成认证后从实际状态继续，不能重放整个任务。报告记录主机决策下的动作与截图，不能当成另一模型独立验收的证据。

最终说明完成结果和未完成项，给出 `report_id` 与 HTML `report` 路径。多个独立进程的记录可累积到同一报告；普通 PUA 调用不计入该报告。保持简短进度，完成所有已授权步骤后再结束。

## 安装、连接和回退

`pua_ready`、`pua_setup`、`pua_apps`、`pua_screen` 继续负责连接、安装、查找 App 和预览，不参与动作规划。未知 bundle ID 用 `pua_apps` 查询，不能猜测。SDK 缺失时按指南安装，无需模型密钥。预览说明见 [屏幕通道](references/screen.md)。

只有用户指定 PUA 或 Midscene 不支持所需操作时，才说明原因并按 [PUA 回退操作](references/pua-fallback.md) 使用原有工具。不要静默改用 PUA，也不要在不确定动作后换工具重做。工具绑定不可用时按 [工具故障与代码调用](references/tool-fallback.md) 调用同一 Midscene 入口，保留同一设备锁和报告 ID。
