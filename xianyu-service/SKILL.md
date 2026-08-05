---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 7d3f5a384d3ea7935c416546d8d2e517_0b06b692907a11f18e22525400f8a581
    ReservedCode1: +KR6MMPLNbLCLJZA1LICqxsITvAhhNhy7RJdTRDo/ZUP3LlUHYxU6pys0hhBBGPYbf7817kD8vTejrAjwBl25JwV0ulYUBgYO3A6jou3PcZiyGjfyOfDzvEksNSHuTg/kFIgu41+NRbqyOAgHANqBaXpWtXsmfWBu6piUtAMTHpsZecV06BVEZihqXs=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 7d3f5a384d3ea7935c416546d8d2e517_0b06b692907a11f18e22525400f8a581
    ReservedCode2: +KR6MMPLNbLCLJZA1LICqxsITvAhhNhy7RJdTRDo/ZUP3LlUHYxU6pys0hhBBGPYbf7817kD8vTejrAjwBl25JwV0ulYUBgYO3A6jou3PcZiyGjfyOfDzvEksNSHuTg/kFIgu41+NRbqyOAgHANqBaXpWtXsmfWBu6piUtAMTHpsZecV06BVEZihqXs=
---



# 闲鱼智能客服

## 架构概览

三级回复链路，从上到下逐级降级：

```
买家消息 → 规则引擎（daemon 实时）→ 匹配命中 → 直接回复
              ↓ 兜不住
         Kimi 大模型（daemon 实时调用）→ 成功 → 回复
              ↓ 也失败
         写入 pending.json → 每30分钟定时任务 → Marvis AI 生成回复 → 写入 marvis_replies.json → daemon 投递
```

## 核心脚本

| 脚本 | 路径 | 职责 |
|------|------|------|
| `xianyu_daemon.py` | `scripts/` | 主守护进程：CDP 连 Edge，休眠期扫描未读 → 活跃期回复，含规则引擎 + LLM 调用 + Marvis 回复投递 |
| `xianyu_send.py` | `scripts/` | 发送队列工具：读取 `send_queue.json` 通过 CDP 批量发送消息 |
| `xianyu_llm_config.json` | `scripts/` | 大模型配置（enabled/api_url/api_key/model/timeout/max_tokens/system_prompt/extra_params） |

> **保活由 xianyu-base 统一负责**：CDP 端口守护（cdp_guard.py）、反检测注入（inject-stealth.py）、统一保活脚本（xianyu_guard.ps1）均属于 xianyu-base 层，本技能不重复包含。

## 部署路径

```
C:\Users\邓少杰\.xianyu_scripts\
├── xianyu_daemon.py          # 客服守护进程
├── xianyu_send.py            # 发送队列
├── xianyu_llm_config.json    # LLM 配置
├── xianyu_state.json         # 守护进程状态（自动生成）
├── xianyu_pending.json       # 待 AI 处理的兜底消息
└── xianyu_marvis_replies.json # Marvis 生成的回复，daemon 负责投递
```

首次部署时需将 `scripts/` 下全部文件复制到 `C:\Users\邓少杰\.xianyu_scripts\`。

## 定时任务配置

### 任务1：AI 客服自动回复（每30分钟）

```
动作：读取 pending.json → 调大模型生成回复 → 写入 marvis_replies.json → 清空 pending.json
触发：每30分钟
提示词：读取 C:\Users\邓少杰\.xianyu_scripts\xianyu_pending.json，对每个待处理客户的消息生成口语化回复（1-3句话），写入 C:\Users\邓少杰\.xianyu_scripts\xianyu_marvis_replies.json，然后清空 pending.json
```

> **保活由 xianyu-base 统一负责**，见 xianyu-base 的计划任务 XianyuGuard。

## 账号-端口-会话目录映射

| 号 | CDP | Edge Profile | 会话目录 |
|---|-----|-------------|---------|
| 1 | 9222 | `C:\Users\邓少杰\Coze\edge-xianyu-profile-1` | `C:\Users\邓少杰\Coze\xianyu-sessions\号1\` |
| 2 | 9223 | `C:\Users\邓少杰\Coze\edge-xianyu-profile-2` | `C:\Users\邓少杰\Coze\xianyu-sessions\号2\` |
| 3 | 9224 | `C:\Users\邓少杰\Coze\edge-xianyu-profile-3` | `C:\Users\邓少杰\Coze\xianyu-sessions\号3\` |

## daemon 工作流程

### 休眠期（idle）
- 每30秒扫描一次 IM 列表页
- 有未读消息 → 切换到活跃期
- 无未读 → 继续休眠

### 活跃期（active）
1. 点击进入有未读的会话
2. 提取最近10条买家消息（过滤自己发的）
3. 规则引擎匹配 → 命中则直接回复
4. 规则引擎兜不住 → 实时调用 Kimi 大模型
5. Kimi 也失败 → 写入 `pending.json` 等定时任务兜底
6. 回复完立即退出活跃期

### Marvis 回复投递
- 每轮循环检查 `marvis_replies.json`
- 有内容则遍历投递到对应会话
- 投递完成后清空文件

## LLM 配置（xianyu_llm_config.json）

```json
{
  "enabled": true,
  "api_url": "https://api.moonshot.cn/v1/chat/completions",
  "api_key": "sk-xxx",
  "model": "kimi-k2.6",
  "timeout": 30,
  "max_tokens": 800,
  "system_prompt": "你是科研CRO服务商的客服代表...",
  "extra_params": {"temperature": 1, "top_p": 0.95}
}
```

- 热加载：daemon 每次调用前重新读取，修改配置无需重启
- 切换模型：改 `api_url` / `api_key` / `model` 即可
- 禁用大模型：`enabled: false` → 规则引擎兜不住直接走 pending.json

---

## browser-agent 模式：CDP 直接回复

> 当需要让 Marvis 通过 browser-agent 直接操作闲鱼 IM 时使用此流程。

### 前置：CDP 自检（shell_executor）

```
Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Where-Object State -eq Listen
```
- 在线 → 继续
- 不在线 → 按 xianyu-base 自检流程拉起 Edge + 注入 + 确认登录态

### 主流程：一次派发 browser-agent

将以下完整指令写入 `current_task`：

```
通过 CDP {port} 连 Edge，打开 goofish.com/im。

扫描未读消息的方法（重要）：
闲鱼使用 Ant Design Badge 组件标记未读。用以下方式判断：
1. 查询每个会话项的 SUP.ant-scroll-number.ant-badge-count 元素
2. 该元素的 title 属性非空 = 有未读（title 值为未读数）
3. 该元素不存在或无 title = 已读，跳过

过滤规则：
- 忽略系统通知（通知消息、闲鱼官方、交易物流、广告）
- 仅处理真人买家且有未读标记的会话

对每个真人未读会话：
1. 点开会话，读取完整对话历史（包括之前的多轮消息）
2. 理解上下文后生成回复：
   - 口语化、简短、像真人聊天，1~3 句话
   - 涉及报价：先引导对方描述详细需求，不给死数字
   - 能力范围外：如实说做不了，不硬编
   - 禁止带微信号/手机号
   - 禁止连续两轮回复内容高度相似（每轮必须换措辞）
   - 每条回复前等待 30~60 秒模拟真人延迟
   - 客户消息太模糊时用兜底话术：
     "你好，请问具体想做什么功能？"
     "在的，有需求可以直接说"
     "你说一下需求我看看能不能做"
     （同一天兜底话术不超过 3 次）
3. 消息发送引擎（React 兼容，强制按此流程）：

   【阶段A：输入消息】
   a. 定位输入框：document.querySelector('[contenteditable="true"]') 或 textarea/input
   b. 聚焦输入框：element.focus()
   c. 写入文本：element.textContent = '{回复内容}' 或 element.value = '{回复内容}'
   d. 触发 React onChange：element.dispatchEvent(new Event('input', {bubbles:true}))

   【阶段B：发送消息 - 策略1（键盘事件链，首选）】
   e. 完整键盘事件链，每个事件必须设置 isTrusted 无法伪造，但需设置完整属性：
      - keydown: key='Enter', code='Enter', keyCode=13, which=13, bubbles=true, cancelable=true
      - keypress: key='Enter', code='Enter', keyCode=13, which=13, charCode=13, bubbles=true
      - keyup: key='Enter', code='Enter', keyCode=13, which=13, bubbles=true
   f. 三事件按顺序触发，间隔 50ms

   【阶段C：发送消息 - 策略2（点击发送按钮，备选）】
   g. 若策略1失败，查找发送按钮：document.querySelector('button[type="submit"]') 或包含"发送"文本的按钮
   h. 点击发送按钮

   【阶段D：发送确认（强制）- 三重验证，缺一不可】

   【前置：记录发送前状态】
   i. 发送前先记录：
      - 消息气泡数量：document.querySelectorAll('[class*="message"]').length（或聊天列表容器内子元素数）
      - 最后一条气泡文本内容
      - 输入框当前值

   【验证1：输入框已清空】
   j. 等待 2 秒后，检查输入框（contenteditable/textarea/input）是否已清空
      - 已清空 → 继续验证2
      - 未清空 → 消息未发送，直接走重试

   【验证2：气泡数量增加】
   k. 检查气泡数量是否 > 发送前记录的数量
      - 增加 → 继续验证3
      - 未增加 → 可能未发送，等待 2 秒再查一次；仍未增加 → 走重试

   【验证3：最新气泡包含目标文本】
   l. 取最后一个消息气泡元素，检查其 textContent 是否包含回复关键词
      - 包含 → 发送成功，进入阶段E
      - 不包含 → 走重试

   【禁止使用 body.innerText.includes】
   - body.innerText 范围太大，会匹配到输入框残留文字或页面其他区域，导致误判
   - 必须精确定位到消息气泡容器内的最后一个气泡元素进行验证

   【重试流程】
   m. 首次失败 → 换策略（策略1失败走策略2，策略2失败走策略1）
   n. 两次策略均失败 → 标记 send_failed=true，本轮跳过此客户，通知用户手动处理

   【阶段E：记录与截图】
   l. 发送成功后截图保存，文件名格式：{号N}_{客户ID}_{时间}.png
   m. 更新客户会话状态文件（含本轮回复内容、时间戳、round_count+1）

   状态文件写入时机：仅在阶段D确认发送成功后写入。严禁在验证通过前写入状态文件。

汇总报告：共扫描 X 个会话，Y 个真人未读，Z 条已回复（含发送确认状态）。如 0 条待回复，直接截图说明。
```

---

## 会话目录

```
C:\Users\邓少杰\Coze\xianyu-sessions\
├── 号1\
│   ├── _global.json          # {"last_check_time": "..."}
│   └── {客户ID}.json         # 客户会话状态
├── 号2\ ...
└── 号3\ ...
```

目录不存在时自动创建，写入初始 `_global.json`：`{"last_check_time": "2026-01-01 00:00:00"}`

---

## 客户会话状态文件

```json
{
  "customer_id": "闲鱼用户ID",
  "customer_name": "昵称",
  "last_message_time": "2026-08-05 10:30:00",
  "last_check_time": "2026-08-05 10:30:00",
  "round_count": 3,
  "stage": "需求了解",
  "last_reply_text": "上次回复的内容摘要（用于避免重复话术）",
  "negative_feedback": false,
  "history": [],
  "status": "active"
}
```

**stage 流转**：需求了解 → 报价评估 → 成交推进 → 已成交 / 已流失

---

## 回复质量约束（强制）

| 约束 | 说明 |
|------|------|
| 话术去重 | 每轮回复前检查 `last_reply_text`，禁止与上一轮内容高度相似 |
| 负面反馈检测 | 客户出现"机器人""刷屏""不要发了""只会这一句"等词 → `negative_feedback` 标记为 true，本轮不回复，人工介入 |
| 兜底话术限额 | 同一天兜底话术最多 3 次，超出后本轮跳过该客户 |
| 禁止引流 | 回复中禁止带微信号/手机号/QQ 等 |

---

## 会话轮次与生命周期

| 参数 | 值 |
|------|-----|
| 单次会话轮次上限 | 8 轮 |
| 静默规则 | 连续 24 小时无新消息 → status 改为 dormant |
| 流失标记 | dormant 超过 7 天 → status 改为 lost |
| 成交归档 | 达成交易后 status 改为 closed |

---

## 异常处理

| 情况 | 处理 |
|------|------|
| 触发验证码 | 停止自动化，通知用户手动处理 |
| 消息量突增 | 降频至正常 50%，观察 24h |
| 账号被限 | 冷却 24h，手动登录确认状态 |
| CDP 连接中断 | 由 xianyu-base 的 XianyuGuard 自动检测恢复 |
| daemon 崩溃 | 由 xianyu-base 的 XianyuGuard 自动拉起 |

## 消息发送实战复盘（2026-08-05，三次失败→成功）

> 本章是经过实战验证的血泪教训，任何修改发送流程前必须先读本章。

### 失败案例时间线

| 轮次 | 时间 | 发送方式 | 验证方式 | 结果 | 根因 |
|------|------|----------|----------|------|------|
| 1 | 09:47 | fill + dispatchEvent Enter | 无验证 | 未发送 | React 合成事件吞掉普通 KeyboardEvent |
| 2 | 10:00 | fill + keydown/keypress/keyup Enter 链 | body.innerText.includes | 未发送但误报成功 | 验证匹配到输入框残留文字，气泡中无此消息 |
| 3 | 10:10 | fill + press Enter | 三重验证 | 成功 | — |

### 三条铁律（强制遵守）

**铁律1：发送方式只用 press Enter，禁止点击发送按钮**
- `press Enter`（CDP Input.dispatchKeyEvent）能正确触发 React 合成事件 → 闲鱼 IM 正常发送
- 点击发送按钮 → 闲鱼 IM 生成草稿而非发送（React 条件渲染，按钮可能未绑定正确 handler）
- 禁止使用 `dispatchEvent(new KeyboardEvent(...))` → React 合成事件不走原生 DOM 事件流

**铁律2：验证必须三重，缺一不可**
- 验证1：输入框清空（发送成功的最可靠信号，清空 = 消息已被服务端接收并移出输入框）
- 验证2：气泡数量增加（量化指标，不受文本内容影响）
- 验证3：最新气泡包含目标文本（最终确认，精确定位到消息列表容器内最后元素）
- 禁止使用 `body.innerText.includes`（范围太大，会匹配输入框残留/页面其他区域）

**铁律3：状态文件只在三重验证全部通过后写入**
- 写入时机 = 三重验证全部 true 之后，严禁提前写入
- 若验证失败，标记 send_failed=true 并通知用户，不写入 history

### 闲鱼 IM 技术特征速查

| 特征 | 说明 |
|------|------|
| 框架 | React，受控组件 |
| 输入框 | contenteditable div，class 含 `sendbox` |
| 发送触发 | press Enter（Input.dispatchKeyEvent） |
| 消息气泡容器 | class 含 `message` 的列表项 |
| 发送按钮 | 点击后产生草稿，不发送 |
| 未读标记 | Ant Design Badge：`SUP.ant-scroll-number.ant-badge-count` title 属性 |

## 规则引擎关键词库

### 招呼词
你好、您好、嗨、hi、hello、在吗、在不在、晚上好、早上好、下午好、在不

### 询价词
价格、多少钱、收费、报价、费用、怎么算、什么价、价位、便宜、贵

### 技术关键词（→ 技术回复模板）
cck8、wb、western、pcr、qpcr、elisa、流式、组化、免疫、ihc、transwell、mtt、edu、tunel、双荧光素酶、sirna、crispr、质粒、转染、克隆、测序、生信、meta

### 动物实验词
动物、小鼠、大鼠、兔子、裸鼠、成瘤、给药、饲养、造模、模型、balb、c57、sd大鼠、豚鼠

### 讨价还价词
便宜点、优惠、打折、能少吗、最低、太贵、别人家

### 催进度词
进度、什么时候、多久、结果、好了吗、完成、数据

## 自己发消息特征（MINE_PATTERNS）

daemon 用此列表过滤自己发出的消息气泡，避免误判为买家新消息：

```
省重点实验室、承接各类生物实验、我们承接、实验需要帮忙、
科研CRO、有什么实验、有什么需要、实验技术服务、实验代做、
动物外包、分子细胞、需要帮忙的吗、有需要随时、实验方面、
需要什么实验、实验均可承接
```
*（内容由AI生成，仅供参考）*
