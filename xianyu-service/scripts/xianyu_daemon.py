"""闲鱼守护进程：双层回复架构
- 休眠期: 每30分钟扫描一次新消息
- 活跃期: 2秒轮询 / 45秒回复 / 最多8轮 / 5分钟静默退出
- 规则引擎兜不住 → 写 pending.json 等 Marvis 接手
"""
import asyncio, json, re, sys, random, traceback, aiohttp
from datetime import datetime, timedelta
from pathlib import Path
from playwright.async_api import async_playwright, Page

CDP_URL = "http://127.0.0.1:9222"
IM_URL = "https://www.goofish.com/im"
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "xianyu_state.json"
PENDING_FILE = SCRIPT_DIR / "xianyu_pending.json"
LLM_CONFIG_FILE = SCRIPT_DIR / "xianyu_llm_config.json"

MINE = ["马维斯", "亲，我现在不在", "通知消息", "[语音]", "[图片]", "[商品]"]
# 自己发出的消息特征关键词（规则引擎模板 + AI 回复的可能内容）
MINE_PATTERNS = [
    "省重点实验室", "承接各类生物实验", "我们承接", "实验需要帮忙",
    "科研CRO", "有什么实验", "有什么需要", "实验技术服务", "实验代做",
    "动物外包", "分子细胞", "需要帮忙的吗", "有需要随时", "实验方面",
    "需要什么实验", "实验均可承接",
]

# ==================== 规则引擎 ====================

GREETING_WORDS = ["你好", "您好", "嗨", "hi", "hello", "在吗", "在不在", "晚上好", "早上好", "下午好", "在不"]
PRICE_WORDS = ["价格", "多少钱", "收费", "报价", "费用", "怎么算", "什么价", "价位", "便宜", "贵"]
TECH_WORDS = {
    "cck8": "CCK-8",
    "cck-8": "CCK-8",
    "wb": "Western Blot",
    "western": "Western Blot",
    "pcr": "PCR",
    "qpcr": "qPCR",
    "elisa": "ELISA",
    "流式": "流式细胞术",
    "组化": "组织化学染色",
    "免疫": "免疫组化",
    "ihc": "免疫组化",
    "transwell": "Transwell",
    "mtt": "MTT",
    "edu": "EdU",
    "tunel": "TUNEL",
    "双荧光素酶": "双荧光素酶报告基因",
    "sirna": "siRNA",
    "crispr": "CRISPR",
    "质粒": "质粒构建",
    "转染": "细胞转染",
    "克隆": "分子克隆",
    "测序": "测序",
    "生信": "生信分析",
    "meta": "Meta分析",
}
ANIMAL_WORDS = ["动物", "小鼠", "大鼠", "兔子", "裸鼠", "成瘤", "给药", "饲养", "造模", "模型", "balb", "c57", "sd大鼠", "豚鼠"]
BARGAIN_WORDS = ["便宜点", "优惠", "打折", "能少吗", "最低", "太贵", "别人家"]
PROGRESS_WORDS = ["进度", "什么时候", "多久", "结果", "好了吗", "完成", "数据"]

GREETING_REPLIES = [
    "你好，省重点实验室科研CRO，有什么实验需要帮忙？",
    "您好，请问需要什么实验技术服务？",
    "你好，我们承接各类生物实验，有需要吗？",
]
PRICE_REPLIES = [
    "具体要看实验项目和样本量，方便说说您的需求吗？我给您报价。",
    "不同实验价格不一样，您需要做哪些指标？我算一下。",
    "得看具体项目和样本数定价，方便描述一下实验方案吗？",
]
ANIMAL_REPLIES = [
    "动物实验我们可以做，请说说具体模型和方案？",
    "动物外包我们实验室承接，需要什么模型？多少只？",
]
BARGAIN_REPLIES = [
    "价格已经是很实在的实验室直出价了，但如果您量大可以再商量。",
    "我们实验室直接服务的，没有中间商，这个价格已经很优惠了。",
]
PROGRESS_REPLIES = [
    "我帮您查一下进度，稍等。",
    "我去核实一下实验进度，马上回复您。",
]
DEFAULT_REPLY = "您好，省重点实验室科研CRO服务，实验代做/动物外包/分子细胞实验均可承接，请问有什么需要？"
CONFUSED_REPLY = "不好意思没太理解您的意思，方便具体说一下需要的实验类型吗？"

def generate_reply(msgs, round_num):
    """规则引擎：根据消息内容和轮次生成回复"""
    full = "".join(msgs).lower()

    # 第一轮打招呼
    if round_num == 1 and any(w in full for w in GREETING_WORDS):
        return random.choice(GREETING_REPLIES)

    # 询价
    if any(w in full for w in PRICE_WORDS):
        return random.choice(PRICE_REPLIES)

    # 讨价还价
    if any(w in full for w in BARGAIN_WORDS):
        return random.choice(BARGAIN_REPLIES)

    # 催进度
    if any(w in full for w in PROGRESS_WORDS):
        return random.choice(PROGRESS_REPLIES)

    # 动物实验
    if any(w in full for w in ANIMAL_WORDS):
        return random.choice(ANIMAL_REPLIES)

    # 技术关键词识别
    found_tech = []
    for kw, name in TECH_WORDS.items():
        if kw in full:
            found_tech.append(name)
    if found_tech:
        tech_list = "、".join(found_tech[:3])
        replies = [
            f"{tech_list}我们可以做，请问样本类型和数量大概多少？",
            f"您好，{tech_list}我们实验室常规承接，方便说说详细方案吗？",
        ]
        return random.choice(replies)

    # 短消息（1-2个字）可能是确认/好的之类
    if len(full) <= 3:
        return random.choice([
            "好的，有需要随时联系我。",
            "没问题，还有什么需要吗？",
        ])

    # 兜底：写 pending.json 等 Marvis 处理
    return None  # 返回 None 表示规则引擎兜不住

# ==================== 工具函数 ====================

def strip_time(text: str) -> str:
    return re.sub(r'(\d+分钟前|\d+小时前|\d+天前|刚刚)$', '', text)

def log(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    return {"mode": "idle", "seen": [], "completed": [], "active_fp": None, "round": 0, "last_msg": None, "last_scan": None}

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

# ==================== 大模型调用 ====================

def load_llm_config():
    """加载 LLM 配置，文件不存在或格式错误返回 None"""
    if not LLM_CONFIG_FILE.exists():
        return None
    try:
        cfg = json.loads(LLM_CONFIG_FILE.read_text(encoding="utf-8"))
        if cfg.get("enabled") and cfg.get("api_url") and cfg.get("api_key"):
            return cfg
        return None
    except:
        return None

async def call_llm(buyer_msgs, config):
    """调用自定义大模型生成回复，成功返回文本，失败返回 None"""
    # 构建对话消息
    messages = [{"role": "system", "content": config["system_prompt"]}]
    # 只取最近3条买家消息作为上下文
    for msg in buyer_msgs[-3:]:
        messages.append({"role": "user", "content": msg})

    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": config.get("max_tokens", 300)
    }
    # 合并用户自定义额外参数（如 top_p 等）
    if config.get("extra_params"):
        payload.update(config["extra_params"])
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=config.get("timeout", 15))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(config["api_url"], json=payload, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    msg = data["choices"][0]["message"]
                    reply = (msg.get("content") or msg.get("reasoning_content") or "").strip()
                    # 清理常见前缀
                    for prefix in ["回复：", "回复:", "客服：", "客服:"]:
                        if reply.startswith(prefix):
                            reply = reply[len(prefix):].strip()
                    if reply:
                        return reply
                log(f"LLM 返回异常: HTTP {resp.status}")
                return None
    except asyncio.TimeoutError:
        log("LLM 调用超时")
        return None
    except Exception as e:
        log(f"LLM 调用失败: {e}")
        return None

NAV_ITEMS = {"发闲置", "APP", "反馈", "客服", "回顶部", "消息", "聊天", "通知"}

async def check_connection_lost(page: Page) -> bool:
    """检测「连接中断」弹窗，若有则点重连并等待恢复"""
    try:
        modal = await page.query_selector('.ant-modal')
        if modal:
            text = (await modal.text_content() or "").strip()
            if "连接中断" in text:
                log("检测到「连接中断」弹窗，尝试重连...")
                # 点击重连按钮
                btns = await modal.query_selector_all('.ant-btn')
                for b in btns:
                    btn_text = (await b.text_content() or "").strip()
                    if "重连" in btn_text or "连" in btn_text:
                        await b.click()
                        await page.wait_for_timeout(5000)
                        break
                return True
    except:
        pass
    return False

async def get_conversations(page: Page, unread_only: bool = True):
    """获取所有会话项，返回 [(元素, 指纹, has_unread)]
    unread_only=True 时只返回有未读标记的会话
    
    适配闲鱼新版 DOM：会话项使用 sidebar-item-wrap 类名，
    通过内容过滤区分导航项和真实会话"""
    result = []
    
    # 新版选择器：sidebar-item-wrap
    items = await page.query_selector_all('[class*="sidebar-item-wrap"]')
    
    for item in items:
        try:
            # 跳过骨架屏
            skeleton = await item.query_selector('.ant-skeleton')
            if skeleton:
                continue
            
            full_text = (await item.text_content() or "").strip()
            if not full_text or len(full_text) < 3:
                continue
            
            # 跳过导航项（发闲置/APP/反馈/客服/回顶部）
            first_word = full_text.split()[0] if full_text.split() else full_text[:4]
            if first_word in NAV_ITEMS or full_text in NAV_ITEMS:
                continue
            
            # 跳过自己发的消息特征
            if any(p in full_text for p in MINE):
                continue
            
            # 检测未读标记（红点/badge/数字/ant-badge）
            has_unread = False
            for sel in ['[class*="unread"]', '[class*="badge"]', '[class*="dot"]',
                        '[class*="red"]', '[class*="count"]', '[class*="tip"]',
                        '.ant-badge', '.unread', '.badge', '.dot']:
                try:
                    el = await item.query_selector(sel)
                    if el:
                        t = (await el.text_content() or "").strip()
                        # ant-badge 如果内容为空但有数字 sup 子元素也算未读
                        if t:
                            has_unread = True
                            break
                        # 检查 sup 子元素（ant-badge 的数字）
                        sup = await el.query_selector('sup')
                        if sup:
                            sup_text = (await sup.text_content() or "").strip()
                            if sup_text:
                                has_unread = True
                                break
                except:
                    continue
            
            if unread_only and not has_unread:
                continue
            
            # 提取买家名指纹
            fp = None
            for sel in ['[class*="nick"]', '[class*="name"]', '[class*="title"]', 'h3', 'h4', 'strong']:
                try:
                    el = await item.query_selector(sel)
                    if el:
                        t = (await el.text_content() or "").strip()
                        t = strip_time(t)
                        if t and 2 <= len(t) <= 30 and not any(p in t for p in MINE):
                            fp = t
                            break
                except:
                    continue
            
            if not fp:
                # 取全文第一行作为指纹（买家名通常在开头）
                lines = [l.strip() for l in full_text.split('\n') if l.strip()]
                for line in lines:
                    cleaned = strip_time(line[:20].strip())
                    if cleaned and 2 <= len(cleaned) <= 25 and cleaned not in NAV_ITEMS:
                        fp = cleaned
                        break
            
            if fp and len(fp) >= 2:
                result.append((item, fp, has_unread))
        except:
            continue
    
    return result

async def extract_buyer_messages(page: Page):
    """提取当前对话中最新的买家消息（严格过滤自己发的）"""
    bubbles = await page.query_selector_all('[class*="bubble"], [class*="msg"], [class*="message"]')
    msgs = []
    for b in bubbles[-10:]:
        try:
            # 1. 检查 CSS 类名是否表明是自己发的
            class_attr = await b.get_attribute("class") or ""
            class_lower = class_attr.lower()
            self_indicators = ["self", "right", "mine", "sent", "send", "owner"]
            is_self = any(ind in class_lower for ind in self_indicators)
            if is_self:
                continue

            t = (await b.text_content()).strip()
            if not t or len(t) <= 1:
                continue

            # 2. 文本匹配：是否包含自己发的特征
            if any(p in t for p in MINE):
                continue
            if any(p in t for p in MINE_PATTERNS):
                continue

            msgs.append(t)
        except:
            continue
    return msgs

async def send_message(page: Page, text: str):
    """向当前对话发送消息"""
    input_box = await page.query_selector('textarea')
    if not input_box:
        input_box = await page.query_selector('[contenteditable="true"]')
    if not input_box:
        input_box = await page.query_selector('[class*="input"], [class*="editor"]')
    if input_box:
        await input_box.click()
        await page.wait_for_timeout(200)
        await page.keyboard.type(text, delay=80)
        await page.wait_for_timeout(400)
        await page.keyboard.press("Enter")
        return True
    return False

# ==================== 主循环 ====================

async def main():
    state = load_state()
    log(f"守护进程启动 | 模式: {state['mode']} | 已见: {len(state['seen'])} | 已完成: {len(state['completed'])}")

    async with async_playwright() as p:
        # 连接 CDP
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            log("CDP 连接失败！请确认 Edge 已打开 goofish.com/im 并登录")
            save_state({"mode": "idle", "seen": [], "completed": [], "active_fp": None, "round": 0, "last_msg": None, "last_scan": None})
            return

        page = browser.contexts[0].pages[-1]
        if IM_URL not in page.url:
            await page.goto(IM_URL)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

        while True:
            try:
                # 检查页面是否还活着
                await page.title()

                # 检测并处理连接中断弹窗
                await check_connection_lost(page)

                if state["mode"] == "idle":
                    # === 休眠期：每30秒扫描一次未读消息 ===
                    now = datetime.now()
                    last_scan = state.get("last_scan")
                    should_scan = False

                    if last_scan:
                        last = datetime.strptime(last_scan, "%Y-%m-%d %H:%M:%S")
                        if (now - last) >= timedelta(seconds=30):
                            should_scan = True
                    else:
                        should_scan = True

                    if should_scan:
                        await page.goto(IM_URL)
                        await page.wait_for_load_state("networkidle")
                        await page.wait_for_timeout(2000)

                        convs = await get_conversations(page, unread_only=True)

                        state["last_scan"] = now.strftime("%Y-%m-%d %H:%M:%S")

                        if convs:
                            item, fp, has_unread = convs[0]
                            log(f"发现未读消息: {fp}")
                            state["active_fp"] = fp
                            state["round"] = 0
                            state["last_msg"] = now.strftime("%Y-%m-%d %H:%M:%S")
                            state["mode"] = "active"
                            save_state(state)
                            continue  # 立即进入活跃期

                        save_state(state)

                    await asyncio.sleep(3)
                    continue

                elif state["mode"] == "active":
                    # === 活跃期：处理一个未读会话，回一条就退出 ===
                    fp = state["active_fp"]
                    now = datetime.now()

                    # 导航到列表页找这个会话
                    if IM_URL not in page.url:
                        await page.goto(IM_URL)
                        await page.wait_for_load_state("networkidle")
                        await page.wait_for_timeout(2000)

                    # 用 unread_only=False 获取全部会话来找匹配
                    convs = await get_conversations(page, unread_only=False)
                    matched = None
                    for item, conv_fp, _ in convs:
                        if conv_fp == fp:
                            matched = item
                            break

                    if not matched:
                        log(f"找不到活跃会话: {fp}，回退休眠期")
                        state["completed"].append(fp)
                        state["active_fp"] = None
                        state["mode"] = "idle"
                        save_state(state)
                        continue

                    # 点击进入对话
                    await matched.click()
                    await page.wait_for_timeout(1500)

                    # 提取买家消息
                    buyer_msgs = await extract_buyer_messages(page)
                    if not buyer_msgs:
                        log(f"未提取到买家消息，跳过: {fp}")
                        state["completed"].append(fp)
                        state["active_fp"] = None
                        state["mode"] = "idle"
                        save_state(state)
                        continue

                    log(f"买家({fp}): {buyer_msgs[-1][:40]}")

                    # 规则引擎生成回复
                    reply = generate_reply(buyer_msgs, 1)

                    if reply is None:
                        # 规则引擎兜不住 → 尝试调用自定义大模型实时生成回复
                        llm_cfg = load_llm_config()
                        if llm_cfg:
                            log(f"规则引擎兜不住，尝试调用大模型 ({llm_cfg['model']})")
                            llm_reply = await call_llm(buyer_msgs, llm_cfg)
                            if llm_reply:
                                reply = llm_reply
                                log(f"大模型回复: {reply[:50]}...")
                            else:
                                log("大模型调用失败，写入 pending.json 兜底")
                        else:
                            log("大模型未配置或未启用，写入 pending.json 等定时任务")

                        # LLM 也失败了或未配置 → 写 pending.json 兜底
                        if reply is None:
                            pending = {}
                            if PENDING_FILE.exists():
                                try:
                                    pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
                                except:
                                    pass
                            pending[fp] = {
                                "messages": buyer_msgs,
                                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S")
                            }
                            PENDING_FILE.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
                            state["completed"].append(fp)
                            state["active_fp"] = None
                            state["mode"] = "idle"
                            state["round"] = 0
                            save_state(state)
                            continue

                    # 发送回复
                    delay = random.uniform(1.0, 3.0)
                    await page.wait_for_timeout(int(delay * 1000))
                    success = await send_message(page, reply)

                    if success:
                        log(f"已回复({len(reply)}字): {reply[:50]}...")
                    else:
                        log("发送失败：找不到输入框")

                    # 回复完立即退出活跃，等下一条未读消息再触发
                    state["completed"].append(fp)
                    state["active_fp"] = None
                    state["mode"] = "idle"
                    state["round"] = 0
                    save_state(state)

                # === Marvis 回复投递 ===
                marvis_replies_file = SCRIPT_DIR / "xianyu_marvis_replies.json"
                if marvis_replies_file.exists():
                    try:
                        mr = json.loads(marvis_replies_file.read_text(encoding="utf-8"))
                        if mr:
                            log(f"收到 Marvis 回复 {len(mr)} 条，开始投递...")
                            await page.goto(IM_URL)
                            await page.wait_for_load_state("networkidle")
                            await page.wait_for_timeout(2000)
                            convs = await get_conversations(page, unread_only=False)
                            sent = 0
                            for fp, reply_text in mr.items():
                                matched = None
                                for item, conv_fp, _ in convs:
                                    if conv_fp == fp:
                                        matched = item
                                        break
                                if matched:
                                    await matched.click()
                                    await page.wait_for_timeout(1500)
                                    await page.wait_for_timeout(random.randint(1000, 3000))
                                    if await send_message(page, reply_text):
                                        sent += 1
                                        log(f"Marvis回复已投递: {reply_text[:40]}...")
                                    await page.wait_for_timeout(2000)
                            if sent > 0:
                                log(f"Marvis 回复投递完成: {sent}/{len(mr)}")
                            # 清空
                            marvis_replies_file.write_text("{}", encoding="utf-8")
                    except:
                        pass

                await asyncio.sleep(2)

            except Exception as e:
                log(f"循环异常: {e}")
                traceback.print_exc()
                save_state(state)
                await asyncio.sleep(10)
                # 尝试恢复
                try:
                    browser = await p.chromium.connect_over_cdp(CDP_URL)
                    page = browser.contexts[0].pages[-1]
                except:
                    log("恢复连接失败，退出守护进程")
                    sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("收到中断信号，守护进程退出")
    except Exception as e:
        log(f"守护进程崩溃: {e}")
        traceback.print_exc()
