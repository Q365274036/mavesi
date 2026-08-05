---
name: xianyu-base
description: 闲鱼底层基础层：CDP端口守护、Edge启动、反检测注入、登录态保活、多账号配置、防封号规则。三个业务技能（research/post/service）共享此层。
---

# 闲鱼基础层

## 架构定位

```
xianyu-base（底层保活 + CDP 管理）
    ├── xianyu-research（每日竞品采集）
    ├── xianyu-post（AI 生成文案配图发帖）
    └── xianyu-service（智能客服：规则引擎 → LLM → pending 兜底）
```

所有上层技能的第一步：检测 CDP 端口 → 不在线则按本技能拉起。

---

## 核心脚本

| 脚本 | 部署路径 | 职责 |
|------|---------|------|
| `scripts/cdp_guard.py` | `C:\Users\邓少杰\Coze\cdp_guard.py` | CDP 三端口守护进程：每5分钟检测9222/9223/9224，不在线则拉起 Edge + 注入反检测 |
| `scripts/inject-stealth.py` | `C:\Users\邓少杰\Coze\inject-stealth.py` | 反检测注入：隐藏 webdriver、伪装 WebGL、覆盖 plugins 等 |
| `scripts/xianyu_guard.ps1` | `C:\Users\邓少杰\.xianyu_scripts\xianyu_guard.ps1` | 统一保活脚本：三端口 CDP + CDP 守护 + 客服 daemon 全覆盖 |

---

## 账号-端口-Profile 映射

| 号 | CDP | Edge Profile | 说明 |
|---|-----|-------------|------|
| 1 | 9222 | `C:\Users\邓少杰\Coze\edge-xianyu-profile-1` | 主号，Skill定制/CRO服务 |
| 2 | 9223 | `C:\Users\邓少杰\Coze\edge-xianyu-profile-2` | 独立账号，自动化脚本 |
| 3 | 9224 | `C:\Users\邓少杰\Coze\edge-xianyu-profile-3` | 独立账号，数据分析 |

三个独立闲鱼账号（不同手机号），各自独立 Profile，互不串号。

---

## 部署清单

首次部署或迁移时需部署以下文件：

```
C:\Users\邓少杰\Coze\
├── cdp_guard.py              # CDP 三端口守护（从 scripts/ 复制）
├── inject-stealth.py         # 反检测注入（从 scripts/ 复制）

C:\Users\邓少杰\.xianyu_scripts\
└── xianyu_guard.ps1          # 统一保活脚本（从 scripts/ 复制）
```

---

## 计划任务

| 任务名 | 脚本 | 频率 | 职责 |
|--------|------|------|------|
| XianyuGuard | `C:\Users\邓少杰\.xianyu_scripts\xianyu_guard.ps1` | 每 5 分钟 | 三端口 CDP + CDP 守护 + 客服 daemon 保活 |

---

## CDP 守护进程（cdp_guard.py）

```powershell
# 手动启动（常驻后台）
python C:\Users\邓少杰\Coze\cdp_guard.py
```

逻辑：
1. 每 5 分钟检测 9222/9223/9224 端口
2. 某端口不在线 → 启动 Edge（指定 Profile）+ 等待 5s + 注入反检测
3. 循环永驻，日志写入 `C:\Users\邓少杰\Coze\xianyu-daemon.log`

---

## 各任务前 CDP 自检（所有上层技能的第一步）

**用 shell_executor 做端口检测，不走大模型**：

```powershell
Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Where-Object State -eq Listen
```

- 在线 → 继续业务操作
- 不在线 → 执行拉起流程：

```powershell
# 1. 启动 Edge
start msedge --remote-debugging-port={port} --user-data-dir="C:\Users\邓少杰\Coze\edge-xianyu-profile-{N}" --disable-blink-features=AutomationControlled --no-first-run --no-default-browser-check
# 2. 等待加载
Start-Sleep -Seconds 5
# 3. 注入反检测
python C:\Users\邓少杰\Coze\inject-stealth.py {port}
```

---

## 反检测注入

`python C:\Users\邓少杰\Coze\inject-stealth.py <CDP端口>`

注入项：
1. 隐藏 `navigator.webdriver`
2. 修改 `chrome.runtime` 检测
3. 覆盖 navigator.plugins / mimeTypes
4. 覆盖 WebGL renderer/vendor 字符串
5. 覆盖 screen.colorDepth / pixelDepth
6. 清理 phantom/nightmare 痕迹

---

## 登录态确认

Browser-agent 访问 goofish.com，3 秒后检查：
- 有"发闲置"按钮 → 已登录，继续
- 有账号选择弹窗 → 按端口选对应号

### 账号选择处理

| CDP 端口 | 对应账号 | 选择策略 |
|----------|----------|----------|
| 9222 | 号1 | 选第一个账号 |
| 9223 | 号2 | 选第二个账号 |
| 9224 | 号3 | 选第三个账号 |

---

## 保活策略

| 操作 | 频率 | 动作 |
|------|------|------|
| CDP 端口检测 | 每 5 分钟 | cdp_guard.py 自动检测拉起 |
| Cookie 刷新 | 每 4 小时 | 浏览首页 → 随机点击商品 → 等待 30s |
| 进程保活 | 每 5 分钟 | 计划任务 XianyuGuard 执行 guard.ps1 |

---

## 防封号规则

### 操作节奏
- 每次点击后随机等待 2~8 秒
- 页面滚动随机幅度 (200~800px)
- 打字速度模拟人类 (100~300ms/字)

### 行为模式
- 发帖前先模拟 3 分钟浏览
- 避免连续相同操作路径

### 降频熔断
- 单号 1 小时操作 < 30 次
- 触发验证码 → 立即停止 → 通知用户
- 异常降频 50%，观察 24h

---

## 多号操作核心规则

1. 同 IP 下多个号禁止同时操作
2. 发帖至少错开 30 分钟以上
3. 消息回复也避开重叠时段

---

## 页面操作原子能力

| 操作 | 方式 |
|------|------|
| 访问 URL | Page.navigate |
| 点击 | 查询 DOM → DispatchMouseEvent |
| 输入文字 | 逐字 InsertText |
| 截图 | Page.captureScreenshot |
| 等待 | 随机等待 |
| 滚动 | Input.dispatchMouseEvent(wheel) |
| 提取文本 | Runtime.evaluate |
