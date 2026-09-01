"""微文收纳 · 扩展 WebSocket 通道（捕获数据 → 入库 / 会话 → 续跑）"""
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import db, service, syncer

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    # 扩展同步批次统计：batch_id -> {task_id, label, synced, existing, failed}
    batches: dict[str, dict] = {}
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"kind": "error", "error": "bad json"})
                continue

            kind = msg.get("kind")
            payload = msg.get("payload") or {}

            if kind in ("sync.article", "sync.batch"):
                items = payload if kind == "sync.batch" else [payload]
                results = []
                for item in items:
                    batch_id = item.get("batch_id") or ""
                    batch_label = item.get("batch_label") or "扩展同步"
                    try:
                        if batch_id:
                            # 批次任务：第一条消息建任务，累计统计
                            if batch_id not in batches:
                                tid = db.create_manual_task(
                                    batch_id, batch_label,
                                    biz=item.get("biz") or "",
                                )
                                batches[batch_id] = {
                                    "task_id": tid, "label": batch_label,
                                    "synced": 0, "existing": 0, "failed": 0,
                                }
                            b = batches[batch_id]
                            res = service.sync_article_payload(item)
                            if res.get("ok"):
                                if res.get("created"):
                                    b["synced"] += 1
                                else:
                                    b["existing"] += 1
                            else:
                                b["failed"] += 1
                                res = {**res, "batch_id": batch_id}
                            results.append(res)
                        else:
                            results.append(service.sync_article_payload(item))
                    except Exception as e:  # noqa: BLE001
                        if batch_id in batches:
                            batches[batch_id]["failed"] += 1
                        results.append({"ok": False, "error": str(e)})
                # 收尾：本次消息涉及到的批次标记 done（单篇=1个批次，批量=全部处理完）
                involved = {item.get("batch_id", "") for item in items if item.get("batch_id")}
                for bid in involved:
                    b = batches.get(bid)
                    if b:
                        db.finish_manual_task(bid, b["synced"], b["existing"], b["failed"])
                        b["done"] = True
                await ws.send_json({"kind": "sync.result", "results": results})

            elif kind in ("session.key", "session.album"):
                biz = payload.get("__biz") or payload.get("biz")
                if biz:
                    acc = db.get_account(biz)
                    payload["account_name"] = (acc or {}).get("name", "")
                    syncer.SESSIONS[biz] = payload
                    # 补 key 后自动续跑该公众号所有暂停任务
                    resumed = syncer.resume_paused(biz)
                    await ws.send_json({"kind": "session.ack", "biz": biz, "resumed": resumed})
                else:
                    await ws.send_json({"kind": "session.ack", "biz": None})

            else:
                await ws.send_json({"kind": "error", "error": f"unknown kind: {kind}"})
    except WebSocketDisconnect:
        pass
