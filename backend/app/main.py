"""FastAPI 入口：活动管理、抽签、一次性揭晓链接与前端托管。"""
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_
from sqlalchemy.orm import Session, aliased

from . import config, matching
from .database import get_db, init_db
from .models import Event, ForbiddenPair, Participant
from .schemas import EventCreate, ParticipantCreate, PairsCreate


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 数据库初始化随启动完成
    init_db()
    yield


app = FastAPI(title="秘密赠礼抽签", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def new_token() -> str:
    return secrets.token_urlsafe(32)


def get_organizer_event(
    event_id: int,
    db: Session = Depends(get_db),
    x_organizer_token: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> Event:
    """凭组织者令牌加载活动；令牌可走请求头或查询参数。"""
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="活动不存在")
    supplied = x_organizer_token or token
    if not supplied or not secrets.compare_digest(supplied, event.organizer_token):
        raise HTTPException(status_code=403, detail="组织者令牌无效")
    return event


def ensure_unlocked(event: Event) -> None:
    """抽签完成后参与者与禁配关系即锁定。"""
    if event.status == "drawn":
        raise HTTPException(status_code=409, detail="抽签已完成，参与者与禁配关系已锁定")


def participant_out(p: Participant) -> dict:
    # 注意：绝不包含 recipient_id，组织者只能看到“是否已揭晓”
    return {
        "id": p.id,
        "name": p.name,
        "reveal_token": p.reveal_token,
        "reveal_url": f"/reveal/{p.reveal_token}",
        "revealed": p.revealed,
        "created_at": p.created_at.isoformat(),
    }


def pair_out(pair: ForbiddenPair, names: dict[int, str]) -> dict:
    return {
        "id": pair.id,
        "lower_id": pair.lower_id,
        "higher_id": pair.higher_id,
        "lower_name": names[pair.lower_id],
        "higher_name": names[pair.higher_id],
    }


def event_out(event: Event) -> dict:
    names = {p.id: p.name for p in event.participants}
    return {
        "id": event.id,
        "name": event.name,
        "organizer_token": event.organizer_token,
        "status": event.status,
        "failure_reason": event.failure_reason,
        "created_at": event.created_at.isoformat(),
        "participants": [participant_out(p) for p in event.participants],
        "forbidden_pairs": [pair_out(pair, names) for pair in event.forbidden_pairs],
    }


# ---------------------------------------------------------------------------
# 活动管理（组织者）
# ---------------------------------------------------------------------------

@app.post("/api/events", status_code=201)
def create_event(payload: EventCreate, db: Session = Depends(get_db)):
    event = Event(name=payload.name, organizer_token=new_token(), status="pending")
    db.add(event)
    db.flush()

    person = {}
    for name in payload.participants:
        p = Participant(event_id=event.id, name=name, reveal_token=new_token())
        db.add(p)
        person[name] = p
    db.flush()

    seen: set[tuple[str, str]] = set()
    for raw_a, raw_b in payload.forbidden_pairs:
        a, b = raw_a.strip(), raw_b.strip()
        if a not in person or b not in person:
            raise HTTPException(
                status_code=422, detail=f"禁配关系包含未知参与者：{a} / {b}"
            )
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)  # type: ignore[arg-type]
        pa, pb = person[a], person[b]
        lo, hi = sorted((pa.id, pb.id))
        db.add(ForbiddenPair(event_id=event.id, lower_id=lo, higher_id=hi))

    db.commit()
    db.refresh(event)
    return event_out(event)


@app.get("/api/events/{event_id}")
def get_event(event: Event = Depends(get_organizer_event)):
    return event_out(event)


@app.post("/api/events/{event_id}/participants", status_code=201)
def add_participant(
    payload: ParticipantCreate,
    db: Session = Depends(get_db),
    event: Event = Depends(get_organizer_event),
):
    ensure_unlocked(event)
    exists = db.query(Participant).filter_by(event_id=event.id, name=payload.name).first()
    if exists:
        raise HTTPException(status_code=409, detail=f"参与者“{payload.name}”已存在")
    p = Participant(
        event_id=event.id, name=payload.name, reveal_token=new_token()
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return participant_out(p)


@app.delete("/api/events/{event_id}/participants/{participant_id}", status_code=204)
def delete_participant(
    participant_id: int,
    db: Session = Depends(get_db),
    event: Event = Depends(get_organizer_event),
):
    ensure_unlocked(event)
    p = db.get(Participant, participant_id)
    if p is None or p.event_id != event.id:
        raise HTTPException(status_code=404, detail="参与者不存在")
    # 同步清理与之相关的禁配关系
    db.query(ForbiddenPair).filter(
        or_(
            ForbiddenPair.lower_id == participant_id,
            ForbiddenPair.higher_id == participant_id,
        )
    ).delete(synchronize_session=False)
    db.delete(p)
    db.commit()


@app.put("/api/events/{event_id}/forbidden-pairs")
def set_forbidden_pairs(
    payload: PairsCreate,
    db: Session = Depends(get_db),
    event: Event = Depends(get_organizer_event),
):
    """整体覆盖禁配关系列表（便于前端增删后一次提交）。"""
    ensure_unlocked(event)

    by_name = {p.name: p for p in event.participants}
    normalized: set[tuple[int, int]] = set()
    for raw_a, raw_b in payload.pairs:
        a, b = raw_a.strip(), raw_b.strip()
        if a not in by_name or b not in by_name:
            raise HTTPException(status_code=422, detail=f"禁配关系包含未知参与者：{a} / {b}")
        lo, hi = sorted((by_name[a].id, by_name[b].id))
        normalized.add((lo, hi))

    db.query(ForbiddenPair).filter_by(event_id=event.id).delete(
        synchronize_session=False
    )
    for lo, hi in normalized:
        db.add(ForbiddenPair(event_id=event.id, lower_id=lo, higher_id=hi))
    db.commit()
    db.refresh(event)
    return event_out(event)


# ---------------------------------------------------------------------------
# 抽签
# ---------------------------------------------------------------------------

@app.post("/api/events/{event_id}/draw")
def draw(
    db: Session = Depends(get_db),
    event: Event = Depends(get_organizer_event),
):
    if event.status == "drawn":
        raise HTTPException(status_code=409, detail="该活动已完成抽签")

    try:
        assignment = matching.solve(event.participants, event.forbidden_pairs)
    except matching.NoSolution as exc:
        # 明确无解：不写入任何匹配结果，保留可编辑状态，记录原因
        event.failure_reason = exc.message
        db.commit()
        raise HTTPException(status_code=409, detail=exc.message)

    # 成功：在同一事务中一次性写入完整匹配，否则整体不生效
    by_id = {p.id: p for p in event.participants}
    for giver_id, receiver_id in assignment.items():
        by_id[giver_id].recipient_id = receiver_id
        by_id[giver_id].revealed = False
    event.status = "drawn"
    event.failure_reason = None
    db.commit()
    db.refresh(event)
    return event_out(event)


# ---------------------------------------------------------------------------
# 参与者一次性揭晓
# ---------------------------------------------------------------------------

@app.get("/api/reveal/{reveal_token}")
def reveal_status(reveal_token: str, db: Session = Depends(get_db)):
    p = (
        db.query(Participant)
        .filter(Participant.reveal_token == reveal_token)
        .first()
    )
    if p is None:
        raise HTTPException(status_code=404, detail="链接无效")
    event = db.get(Event, p.event_id)
    return {
        "event_name": event.name,
        "participant_name": p.name,
        "status": event.status,
        "revealed": p.revealed,
    }


@app.post("/api/reveal/{reveal_token}")
def do_reveal(reveal_token: str, db: Session = Depends(get_db)):
    p = (
        db.query(Participant)
        .filter(Participant.reveal_token == reveal_token)
        .first()
    )
    if p is None:
        raise HTTPException(status_code=404, detail="链接无效")

    event = db.get(Event, p.event_id)
    if event.status != "drawn":
        raise HTTPException(status_code=409, detail="抽签尚未完成，请稍后再试")

    if p.revealed:
        # 结果只能成功揭晓一次：再次访问只告知“已揭晓”，不重复暴露结果
        raise HTTPException(status_code=409, detail="该链接已经揭晓过，结果只能查看一次")

    # 原子条件更新：仅当 revealed=False 时翻转为 True，并发下也只有一次成功
    updated = (
        db.query(Participant)
        .filter(Participant.id == p.id, Participant.revealed.is_(False))
        .update({Participant.revealed: True}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="该链接已经揭晓过，结果只能查看一次")
    db.commit()

    # 提交后重新查询收礼人名字（不经过会话缓存）
    giver = aliased(Participant)
    receiver = aliased(Participant)
    row = (
        db.query(giver.name, receiver.name)
        .join(receiver, giver.recipient_id == receiver.id)
        .filter(giver.id == p.id)
        .one()
    )
    return {
        "event_name": event.name,
        "participant_name": row[0],
        "recipient_name": row[1],
    }


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# ---------------------------------------------------------------------------
# 前端静态资源与 SPA 回退（生产镜像）
# ---------------------------------------------------------------------------

_static_dir = Path(config.STATIC_DIR)
if (_static_dir / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_static_dir / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_entry(full_path: str):
    if full_path.startswith("api/") or full_path == "health":
        raise HTTPException(status_code=404, detail="Not found")
    index = _static_dir / "index.html"
    if not index.is_file():
        # 前端尚未构建（开发模式）时给出提示
        raise HTTPException(status_code=404, detail="前端未构建，请使用 Vite 开发服务器（:5173）")
    return FileResponse(index)
