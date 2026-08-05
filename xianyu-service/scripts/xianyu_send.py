"""xianyu_send.py — 读取 send_queue.json 并通过 CDP 发送闲鱼消息"""
import asyncio, json, sys, re, random
from pathlib import Path
from playwright.async_api import async_playwright

CDP_URL = "http://127.0.0.1:9222"
IM_URL = "https://www.goofish.com/im"
SCRIPT_DIR = Path(__file__).parent
QUEUE_FILE = SCRIPT_DIR / "send_queue.json"

NAV_ITEMS = {"发闲置", "APP", "反馈", "客服", "回顶部", "消息", "聊天", "通知"}
MINE = ["马维斯", "亲，我现在不在", "通知消息", "[语音]", "[图片]", "[商品]"]

def strip_time(text: str) -> str:
    return re.sub(r'(\d+分钟前|\d+小时前|\d+天前|刚刚)$', '', text)

async def get_all_conversations(page):
    """获取所有真实会话列表，返回 [(元素, 指纹)]"""
    result = []
    items = await page.query_selector_all('[class*="sidebar-item-wrap"]')
    for item in items:
        try:
            skeleton = await item.query_selector('.ant-skeleton')
            if skeleton:
                continue
            full_text = (await item.text_content() or "").strip()
            if not full_text or len(full_text) < 3:
                continue
            first_word = full_text.split()[0] if full_text.split() else full_text[:4]
            if first_word in NAV_ITEMS or full_text in NAV_ITEMS:
                continue
            if any(p in full_text for p in MINE):
                continue
            # 提取买家名指纹
            fp = None
            for sel in ['[class*="nick"]', '[class*="name"]', '[class*="title"]', 'h3', 'h4', 'strong']:
                try:
                    el = await item.query_selector(sel)
                    if el:
                        t = (await el.text_content() or "").strip()
                        t = strip_time(t)
                        if t and 2 <= len(t) <= 30:
                            fp = t
                            break
                except:
                    continue
            if not fp:
                lines = [l.strip() for l in full_text.split('\n') if l.strip()]
                for line in lines:
                    cleaned = strip_time(line[:20].strip())
                    if cleaned and 2 <= len(cleaned) <= 25 and cleaned not in NAV_ITEMS:
                        fp = cleaned
                        break
            if fp and len(fp) >= 2:
                result.append((item, fp))
        except:
            continue
    return result

async def send_message(page, text: str):
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

async def main():
    if not QUEUE_FILE.exists():
        print("send_queue.json 不存在，无需发送")
        return

    queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8-sig"))
    if not queue:
        print("send_queue.json 为空，无需发送")
        return

    print(f"待发送 {len(queue)} 条消息")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"CDP 连接失败: {e}")
            sys.exit(1)

        page = browser.contexts[0].pages[-1]
        if IM_URL not in page.url:
            await page.goto(IM_URL)
            await page.wait_for_load_state("networkidle")
            await page.wait_for_timeout(3000)

        sent_count = 0
        failed = []

        for conv_key, reply_text in queue.items():
            # 从 conv_key 中提取买家名（取前几个字）
            # conv_key 格式: "买家名消息内容"，如 "加油呀小老弟好的"
            # 尝试匹配已知买家名
            buyer_name = None
            msg_keyword = None
            known_names = ["加油呀小老弟"]
            for name in known_names:
                if conv_key.startswith(name):
                    buyer_name = name
                    msg_keyword = conv_key[len(name):].strip()
                    break

            if not buyer_name:
                # 取前6个字作为候选
                buyer_name = conv_key[:6]
                msg_keyword = conv_key[6:].strip()

            print(f"\n处理: [{buyer_name}] 关键词=[{msg_keyword}]")

            # 刷新会话列表
            if IM_URL not in page.url:
                await page.goto(IM_URL)
                await page.wait_for_load_state("networkidle")
                await page.wait_for_timeout(2000)

            convs = await get_all_conversations(page)

            # 找到匹配的会话
            matched = []
            for item, fp in convs:
                if buyer_name in fp:
                    matched.append((item, fp))

            if not matched:
                print(f"  未找到匹配会话: {buyer_name}")
                failed.append(conv_key)
                continue

            # 逐个尝试匹配的会话，检查是否包含消息关键词
            target = None
            for item, fp in matched:
                await item.click()
                await page.wait_for_timeout(1500)

                # 检查页面内容是否包含消息关键词
                page_text = (await page.text_content() or "").lower()
                if msg_keyword and msg_keyword.lower() in page_text:
                    target = item
                    print(f"  匹配到会话: {fp}（含关键词）")
                    break
                elif len(matched) == 1:
                    target = item
                    print(f"  唯一匹配会话: {fp}")
                    break

            if not target:
                # 如果都没匹配到关键词，用第一个
                target = matched[0][0]
                await target.click()
                await page.wait_for_timeout(1500)
                print(f"  关键词未精确匹配，使用第一个会话: {matched[0][1]}")

            # 随机延迟后发送
            delay = random.uniform(1.0, 3.0)
            await page.wait_for_timeout(int(delay * 1000))

            success = await send_message(page, reply_text)
            if success:
                sent_count += 1
                print(f"  已发送({len(reply_text)}字): {reply_text[:50]}")
            else:
                print(f"  发送失败：找不到输入框")
                failed.append(conv_key)

            await page.wait_for_timeout(2000)

        # 清空已发送的条目
        if sent_count > 0:
            remaining = {k: v for k, v in queue.items() if k in failed}
            QUEUE_FILE.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"\n发送完成: {sent_count}/{len(queue)} 条成功")
        if failed:
            print(f"失败: {failed}")

if __name__ == "__main__":
    asyncio.run(main())
