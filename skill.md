# 闲鱼运营四件套 (Xianyu Agent Skills)

桌面级闲鱼多号自动化技能包，专为 Marvis Agent 设计。底层保活统一，三个业务模块按需触发或常驻运行。

## 架构

```
xianyu-base（底层基础设施）
    │  CDP 三端口守护 · 反检测注入 · 统一保活
    │
    ├── xianyu-research → 每日竞品采集（100 帖归档，20 天清理）
    ├── xianyu-post     → AI 文案配图发帖（多号错时排期）
    └── xianyu-service  → 三级智能客服（规则引擎 → LLM → 定时兜底）
```

## 安装

1. 将四个子目录放入 Marvis 技能目录 `skills\market\` 下：

```
skills\market\xianyu-base\        → xianyu-base\
skills\market\xianyu-research\    → xianyu-research\
skills\market\xianyu-post\        → xianyu-post\
skills\market\xianyu-service\     → xianyu-service\
```

2. 重启 Marvis 或刷新技能列表。

也可直接使用仓库根目录提供的 `.skill` 包（zip 格式），改名 `.zip` 解压到对应位置。

## 部署前置条件

- Windows 10/11 + Edge 浏览器
- Python 3.11+（daemon 依赖 `playwright`、`aiohttp`）
- 三个闲鱼账号，Edge Profile 独立配置

## 首次部署步骤

### 1. 部署 base 层脚本

将 `xianyu-base/scripts/` 下的文件复制到 `%USERPROFILE%\Coze\`：

| 脚本 | 说明 |
|------|------|
| `cdp_guard.py` | CDP 端口守护进程，每 5 分钟检测三端口在线状态 |
| `inject-stealth.py` | 反检测脚本注入 |
| `xianyu_guard.ps1` | PowerShell 统一保活入口 |

### 2. 部署 service 层脚本

将 `xianyu-service/scripts/` 下全部文件复制到 `%USERPROFILE%\.xianyu_scripts\`。

### 3. 配置 Edge Profile

为三个闲鱼号分别创建独立 Profile，手动登录一次让 Cookie 持久化：

```powershell
start msedge --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\Coze\edge-xianyu-profile-1"
start msedge --remote-debugging-port=9223 --user-data-dir="%USERPROFILE%\Coze\edge-xianyu-profile-2"
start msedge --remote-debugging-port=9224 --user-data-dir="%USERPROFILE%\Coze\edge-xianyu-profile-3"
```

### 4. 配置 LLM（可选，仅 service 需要）

编辑 `%USERPROFILE%\.xianyu_scripts\xianyu_llm_config.json`：

```json
{
  "enabled": true,
  "api_url": "https://api.moonshot.cn/v1/chat/completions",
  "api_key": "你的API_KEY",
  "model": "kimi-k2.6",
  "timeout": 30,
  "max_tokens": 800,
  "system_prompt": "你是科研CRO服务商的客服代表...",
  "extra_params": { "temperature": 1, "top_p": 0.95 }
}
```

兼容 OpenAI 协议，换成 DeepSeek、通义千问等均可。

### 5. 创建计划任务

| 任务 | 脚本 | 频率 |
|------|------|------|
| XianyuGuard | `xianyu_guard.ps1` | 每 5 分钟 |
| AI 客服回复 | 自动读 pending.json → 生成回复 | 每 30 分钟 |

## 使用

- **调研**：对 Marvis 说「闲鱼调研」「采集竞品」
- **发帖**：对 Marvis 说「发帖：<主题>」
- **客服**：部署后自动运行，无需手动触发

## 客服三级回复链路

```
新消息 → 规则引擎（关键词匹配） → 命中则直接回复
                ↓ 未命中
          自定义 LLM（实时生成） → 成功则回复
                ↓ 失败
          pending.json → 定时任务兜底处理
```

## 安全

- 所有数据本地运行，不出电脑
- 仓库发布包不含 API Key，需自行配置 `xianyu_llm_config.json`
- 三号独立 Profile，互不串号
- 不存储密码，仅通过 CDP 复用 Edge 登录态

## 许可

本项目仅供学习交流使用。使用者需自行遵守闲鱼平台规则。
