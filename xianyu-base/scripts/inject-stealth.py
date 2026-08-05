"""
闲鱼 Edge CDP 反检测注入脚本
通过页面级 WebSocket 注入 Page.addScriptToEvaluateOnNewDocument
"""
import asyncio, json, sys, httpx, websockets

STEALTH_JS = """
// 闲鱼反反爬 - CDP 注入
'use strict';
Object.defineProperty(navigator, 'webdriver', { get: () => false });
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const a = [1,2,3,4,5]; a.refresh=()=>{}; a.item=i=>a[i]; a.namedItem=()=>null; return a;
    }
});
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en-US','en'] });
window.chrome = { runtime:{}, loadTimes(){}, csi(){}, app:{} };
const oq = navigator.permissions.query;
navigator.permissions.query = p => p.name==='notifications' ? Promise.resolve({state:Notification.permission}) : oq(p);
const og = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(p) {
    if(p===37445) return 'Google Inc. (Intel)';
    if(p===37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.5)';
    return og.call(this,p);
};
delete window.__phantom; delete window.callPhantom;
delete window._phantom; delete window.__nightmare;
Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
console.log('[Stealth] OK');
"""

async def inject(port):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"http://127.0.0.1:{port}/json/list")
        pages = resp.json()
    
    target_pages = [p for p in pages if p.get("type") == "page"]
    if not target_pages:
        print("[ERROR] 没有打开的页面")
        return
    
    for page in target_pages:
        ws_url = page["webSocketDebuggerUrl"]
        pid = page["id"]
        title = page.get("title", "?")
        
        try:
            async with websockets.connect(ws_url) as ws:
                cmd = {
                    "id": 1,
                    "method": "Page.addScriptToEvaluateOnNewDocument",
                    "params": {"source": STEALTH_JS}
                }
                await ws.send(json.dumps(cmd))
                resp = await ws.recv()
                result = json.loads(resp)
                if "result" in result:
                    sid = result["result"].get("identifier", "")
                    print(f"[OK] {title} ({pid}) scriptId={sid}")
                else:
                    err = result.get("error", {}).get("message", "unknown")
                    print(f"[FAIL] {title} ({pid}): {err}")
        except Exception as e:
            print(f"[FAIL] {title} ({pid}): {e}")

async def main():
    if len(sys.argv) < 2:
        print("用法: python inject-stealth.py <CDP端口>")
        sys.exit(1)
    await inject(sys.argv[1])

if __name__ == "__main__":
    asyncio.run(main())
