"""演示脚本逐场景验证（真实模型 + 真实库）。不对生产代码做任何改动，只发请求。"""

import asyncio
import json
import time

import httpx

BASE = "http://127.0.0.1:8000"


async def turn(client, sid, text, tag):
    ev = ""
    out = {"text": "", "tools": [], "cites": [], "action": None, "slots": None, "error": None}
    t0 = time.perf_counter()
    async with client.stream(
        "POST",
        "/api/v1/chat/stream",
        json={"sessionId": sid, "message": text, "clientMsgId": f"{tag}-{time.time()}"},
    ) as r:
        async for line in r.aiter_lines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                d = json.loads(line[5:])
                if ev == "delta":
                    out["text"] += str(d.get("text") or "")
                elif ev == "tool" and d.get("status") == "end":
                    out["tools"].append(f"{d.get('name')}:{'ok' if d.get('ok') else 'fail'}")
                elif ev == "citation":
                    out["cites"].append(f"[{d.get('index')}]{d.get('title')}")
                elif ev == "action":
                    # 事件负载形如 {"type":"action","action":{...}}，卡片在内层
                    out["action"] = d.get("action") or d
                elif ev == "slots":
                    out["slots"] = d.get("changed")
                elif ev == "error":
                    out["error"] = d.get("message")
    out["ms"] = int((time.perf_counter() - t0) * 1000)
    return out


async def new_session(client):
    return str((await client.post("/api/v1/sessions", json={})).json()["data"]["id"])


async def login(client, phone):
    r = await client.post("/api/v1/auth/login", json={"phone": phone, "password": "Test123456"})
    return r.json()["data"]["token"]


def show(name, t, extra=""):
    print(f"\n### {name}  ({t['ms']}ms)")
    print("A:", (t["text"] or "")[:220].replace("\n", " / "))
    print("tools:", t["tools"], "cites:", t["cites"][:3], "slots:", t["slots"])
    if t["action"]:
        a = t["action"]
        print(
            "action:",
            {
                k: a.get(k)
                for k in ("kind", "ticketNo", "created", "typeLabel", "statusLabel")
                if k in a
            },
        )
    if t["error"]:
        print("error:", t["error"])
    if extra:
        print(extra)


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=120, trust_env=False) as c:
        tokenA = await login(c, "13800000001")
        c.headers["Authorization"] = f"Bearer {tokenA}"

        # 场景 1+2：商品检索 + 多轮指代（同一会话）
        sid = await new_session(c)
        t1 = await turn(c, sid, "1000 以内的降噪耳机有哪些", "d1")
        show("S1 商品检索", t1)
        t2 = await turn(c, sid, "第二个多少钱", "d2")
        show("S2 多轮指代", t2)

        # 场景 3：订单物流
        sid3 = await new_session(c)
        t3 = await turn(c, sid3, "帮我查下订单 20261101001 到哪了", "d3")
        show("S3 订单物流", t3)

        # 场景 4：越权（A 查 B 的订单 20261101023）
        sid4 = await new_session(c)
        t4 = await turn(c, sid4, "帮我查下订单 20261101023 到哪了", "d4")
        show("S4 越权拦截", t4)
        # 游客查单必须不带 token：带了 token 就走"仅本人"分支，正确尾号也会被拒
        async with httpx.AsyncClient(base_url=BASE, timeout=30, trust_env=False) as anon:
            ok_guest = await anon.get("/api/v1/orders/20261101023", params={"phoneTail": "0002"})
            bad_guest = await anon.get("/api/v1/orders/20261101023", params={"phoneTail": "0001"})
        print(
            "游客(正确尾号):",
            ok_guest.status_code,
            ok_guest.json()["code"],
            "| 游客(错误尾号):",
            bad_guest.status_code,
            bad_guest.json()["code"],
        )

        # 场景 5：政策 + 引用
        sid5 = await new_session(c)
        t5 = await turn(c, sid5, "退货运费谁承担", "d5")
        show("S5 政策引用", t5)

        # 场景 6：售后全链路 + 幂等
        sid6 = await new_session(c)
        t6a = await turn(c, sid6, "我要退货，订单 20261101008", "d6a")
        show("S6a 售后待确认", t6a)
        t6b = await turn(c, sid6, "确认提交", "d6b")
        show("S6b 确认建单", t6b)
        t6c = await turn(c, sid6, "确认提交", "d6c")
        show("S6c 重复确认（幂等）", t6c)
        same = (
            t6b["action"]
            and t6c["action"]
            and t6b["action"].get("ticketNo") == t6c["action"].get("ticketNo")
        )
        print("同一工单号?", same)

        # 场景 7：转人工 + 历史刷新
        sid7 = await new_session(c)
        t7 = await turn(c, sid7, "我要转人工，找客服核实一下这个订单", "d7")
        show("S7 转人工", t7)
        hist = await c.get(f"/api/v1/sessions/{sid7}/messages")
        msgs = (
            hist.json()["data"]["items"]
            if isinstance(hist.json()["data"], dict)
            else hist.json()["data"]
        )
        print("刷新后消息数:", len(msgs))

        # 场景 9：看板
        r = await c.get(
            "/api/v1/admin/metrics",
            params={"hours": 1},
            headers={"X-Admin-Token": "local-admin-token"},
        )
        d = r.json()["data"]
        print(
            "\n### 看板 turns=",
            d["turns"]["total"],
            "llm.calls=",
            d["llm"]["calls"],
            f"cost=¥{d['llm']['costCny']:.5f}",
            "intent=",
            [(i["intent"], i["count"]) for i in d["intent"][:4]],
        )


asyncio.run(main())
