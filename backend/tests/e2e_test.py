"""端到端冒烟测试：使用临时 SQLite 文件 + FastAPI TestClient。"""
import concurrent.futures
import os
import sys
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(tmp, "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{os.environ['DATABASE_PATH']}"
os.environ.setdefault("STATIC_DIR", os.path.join(tmp, "no-static"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)

fails = []


def check(cond, msg):
    if cond:
        print(f"  PASS: {msg}")
    else:
        print(f"  FAIL: {msg}")
        fails.append(msg)


# ---------- 1. 创建 + 抽签 + 验证完美匹配性质 ----------
print("== 正常抽签 ==")
r = client.post("/api/events", json={
    "name": "测试局",
    "participants": ["张三", "李四", "王五", "赵六", "钱七"],
    "forbidden_pairs": [["张三", "李四"], ["王五", "赵六"]],
})
check(r.status_code == 201, f"创建活动 -> {r.status_code}")
ev = r.json()
eid, tok = ev["id"], ev["organizer_token"]
H = {"X-Organizer-Token": tok}
check(len(ev["participants"]) == 5, "5 名参与者")
check(len(ev["forbidden_pairs"]) == 2, "2 条禁配关系")

r = client.post(f"/api/events/{eid}/draw", headers=H)
check(r.status_code == 200, f"抽签成功 -> {r.status_code} {r.text if r.status_code != 200 else ''}")
ev = r.json()
check(ev["status"] == "drawn", "状态 drawn")
check(ev["failure_reason"] is None, "无失败原因")

# 组织者视图不得包含 recipient 信息
raw = r.text
check("recipient_id" not in raw and "recipient_name" not in raw, "组织者响应中不含匹配结果")

# 用随机化重复抽多局，验证匹配性质与禁配
from app.matching import solve  # noqa: E402


class P:
    def __init__(self, i, n):
        self.id, self.name = i, n


class FP:
    def __init__(self, a, b):
        self.lower_id, self.higher_id = sorted((a, b))


people = [P(i, f"p{i}") for i in range(10)]
fps = [FP(0, 1), FP(2, 3), FP(0, 4)]
for trial in range(200):
    m = solve(people, fps)
    givers, receivers = list(m.keys()), list(m.values())
    assert sorted(givers) == list(range(10)), "每人送出一份"
    assert sorted(receivers) == list(range(10)), "每人收到一份"
    assert all(g != r_ for g, r_ in m.items()), "无人抽自己"
    for fp in fps:
        assert m[fp.lower_id] != fp.higher_id and m[fp.higher_id] != fp.lower_id, "禁配不被命中"
print("  PASS: 200 次随机解均满足 完美匹配/非自环/禁配")

# ---------- 2. 锁定期不能增删 ----------
print("== 锁定 ==")
r = client.post(f"/api/events/{eid}/participants", headers=H, json={"name": "新人"})
check(r.status_code == 409, "抽签后禁止加人")
r = client.put(f"/api/events/{eid}/forbidden-pairs", headers=H, json={"pairs": []})
check(r.status_code == 409, "抽签后禁止改禁配")
r = client.post(f"/api/events/{eid}/draw", headers=H)
check(r.status_code == 409, "重复抽签被拒绝")

# 无组织者令牌
r = client.get(f"/api/events/{eid}")
check(r.status_code == 403, "无令牌 403")
r = client.get(f"/api/events/{eid}", headers={"X-Organizer-Token": "wrong"})
check(r.status_code == 403, "错误令牌 403")
r = client.get("/api/events/999999", headers=H)
check(r.status_code == 404, "活动不存在 404")

# ---------- 3. 揭晓：GET 不暴露结果；POST 一次成功 ----------
print("== 一次性揭晓 ==")
ps = ev["participants"]
rtok = ps[0]["reveal_token"]

r = client.get(f"/api/reveal/{rtok}")
check(r.status_code == 200 and "recipient" not in r.text, "GET 状态不含结果")

r = client.post(f"/api/reveal/{rtok}")
check(r.status_code == 200, f"首次揭晓成功 -> {r.status_code}")
res1 = r.json()
check(res1["participant_name"] == ps[0]["name"], "揭晓人名字正确")
check(bool(res1["recipient_name"]) and res1["recipient_name"] != ps[0]["name"], "有收礼人且非自己")

r = client.post(f"/api/reveal/{rtok}")
check(r.status_code == 409, f"二次揭晓被拒绝 -> {r.status_code}")

r = client.get(f"/api/reveal/{rtok}")
check(r.json()["revealed"] is True, "状态变为已揭晓")

# 组织者只能看到 revealed=true
r = client.get(f"/api/events/{eid}", headers=H)
p0 = next(p for p in r.json()["participants"] if p["id"] == ps[0]["id"])
check(p0["revealed"] is True and "recipient" not in str(p0), "组织者仅见已揭晓状态")

# 无效链接
r = client.get("/api/reveal/does-not-exist")
check(r.status_code == 404, "无效链接 404")

# ---------- 4. 并发揭晓：只有一个成功 ----------
print("== 并发揭晓 ==")
rtok2 = ps[1]["reveal_token"]
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    codes = list(ex.map(lambda _: client.post(f"/api/reveal/{rtok2}").status_code, range(10)))
check(codes.count(200) == 1 and codes.count(409) == 9, f"并发 10 次仅 1 次成功: {codes}")

# ---------- 5. 无解场景 ----------
print("== 无解（不产生部分结果）==")
# 3 人中 p0 与另外两人全部禁配 -> p0 无任何可送对象
r = client.post("/api/events", json={
    "name": "死局",
    "participants": ["甲", "乙", "丙"],
    "forbidden_pairs": [["甲", "乙"], ["甲", "丙"]],
})
dead = r.json()
did, dtok = dead["id"], dead["organizer_token"]
r = client.post(f"/api/events/{did}/draw", headers={"X-Organizer-Token": dtok})
check(r.status_code == 409, f"无解返回 409 -> {r.status_code}")
check("无解" in r.json()["detail"], f"原因明确: {r.json()['detail']}")
r = client.get(f"/api/events/{did}", headers={"X-Organizer-Token": dtok})
dj = r.json()
check(dj["status"] == "pending", "无解后活动仍 pending（可编辑）")
check(dj["failure_reason"] and "无解" in dj["failure_reason"], "失败原因已记录")

# 无解后揭晓链接应提示尚未抽签（没有结果可看）
rt = dead["participants"][0]["reveal_token"]
r = client.post(f"/api/reveal/{rt}")
check(r.status_code == 409 and "尚未" in r.json()["detail"], "无解活动揭晓返回未抽签")

# 放宽约束后可以成功重抽（3 人仅禁一对仍然无解——两个三元错排都会命中该对；清空即可）
r = client.put(f"/api/events/{did}/forbidden-pairs",
               headers={"X-Organizer-Token": dtok}, json={"pairs": []})
check(r.status_code == 200, "放宽禁配成功")
r = client.post(f"/api/events/{did}/draw", headers={"X-Organizer-Token": dtok})
check(r.status_code == 200, f"调整后重抽成功 -> {r.status_code}")

# 少于 2 人
r = client.post("/api/events", json={"name": "单人", "participants": ["孤独"]})
solo = r.json()
r = client.post(f"/api/events/{solo['id']}/draw", headers={"X-Organizer-Token": solo["organizer_token"]})
check(r.status_code == 409 and "2 名" in r.json()["detail"], "1 人无解并提示")

# 禁配引用不存在的参与者 -> 422（而非 500），且活动未创建
before = client.get("/health")
r = client.post("/api/events", json={
    "name": "坏禁配",
    "participants": ["甲", "乙"],
    "forbidden_pairs": [["甲", "不存在的人"]],
})
check(r.status_code == 422, f"未知参与者禁配 422 -> {r.status_code}")

# 重名 / 空名校验
r = client.post("/api/events", json={"name": "x", "participants": ["甲", "甲"]})
check(r.status_code == 422, "重名参与者 422")

# ---------- 6. 参与者增删 ----------
print("== 编辑参与者/禁配 ==")
r = client.post("/api/events", json={"name": "编辑局", "participants": ["a", "b"]})
e2, t2 = r.json()["id"], r.json()["organizer_token"]
H2 = {"X-Organizer-Token": t2}
r = client.post(f"/api/events/{e2}/participants", headers=H2, json={"name": "c"})
check(r.status_code == 201, "新增 c")
r = client.post(f"/api/events/{e2}/participants", headers=H2, json={"name": "c"})
check(r.status_code == 409, "重名 409")
r = client.put(f"/api/events/{e2}/forbidden-pairs", headers=H2, json={"pairs": [["a", "b"], ["b", "a"]]})
check(r.status_code == 200 and len(r.json()["forbidden_pairs"]) == 1, "重复禁配去重")
r = client.put(f"/api/events/{e2}/forbidden-pairs", headers=H2, json={"pairs": [["a", "x"]]})
check(r.status_code == 422, "未知参与者 422")

cid = client.get(f"/api/events/{e2}", headers=H2).json()
cid_b = next(p for p in cid["participants"] if p["name"] == "b")["id"]
r = client.delete(f"/api/events/{e2}/participants/{cid_b}", headers=H2)
check(r.status_code == 204, "删除 b")
r = client.get(f"/api/events/{e2}", headers=H2)
check(len(r.json()["participants"]) == 2 and len(r.json()["forbidden_pairs"]) == 0,
      "删除后禁配被级联清理")

# ---------- 7. health ----------
r = client.get("/health")
check(r.status_code == 200 and r.json()["status"] == "ok", "health ok")

# ---------- 8. 礼物偏好卡 ----------
print("== 礼物偏好卡 ==")
r = client.post("/api/events", json={
    "name": "偏好局",
    "participants": ["甲", "乙", "丙", "丁"],
})
check(r.status_code == 201, f"创建偏好局 -> {r.status_code}")
pev = r.json()
peid, ptok = pev["id"], pev["organizer_token"]
PH = {"X-Organizer-Token": ptok}
ta, tb, tc, td = pev["participants"]
tokA, tokB, tokC = ta["reveal_token"], tb["reveal_token"], tc["reveal_token"]

# 8.1 初始状态：未填写、可编辑，且状态响应中不含卡片内容
r = client.get(f"/api/reveal/{tokA}")
j = r.json()
check(j["preference_filled"] is False and j["preference"] is None, "初始偏好卡为空")
check(j["preference_editable"] is True, "抽签前可编辑")
check("wish_text" not in r.text and "avoid_text" not in r.text and "size_text" not in r.text,
      "空卡响应中不出现任何偏好内容字段")

# 8.2 本人凭链接填写并可反复修改
r = client.put(f"/api/reveal/{tokA}/preference", json={
    "wish_text": "想要围巾", "avoid_text": "忌羊毛", "size_text": "L 码",
})
check(r.status_code == 200, f"填写偏好卡 -> {r.status_code}")
check(r.json()["preference_filled"] is True, "填写后标记为已填")

r = client.put(f"/api/reveal/{tokA}/preference", json={
    "wish_text": "改想要手套", "avoid_text": "忌羊毛", "size_text": "M 码",
})
j = r.json()
check(j["preference"]["wish_text"] == "改想要手套", "反复修改生效（upsert）")

r = client.get(f"/api/reveal/{tokA}")
j = r.json()
check(j["preference"]["wish_text"] == "改想要手套", "GET 状态返回本人最新卡片")
check(j["preference_editable"] is True, "抽签前仍可编辑")

# 全空保存 -> 视为未填写（卡片存在但无内容）
r = client.put(f"/api/reveal/{tokA}/preference", json={
    "wish_text": "  ", "avoid_text": "", "size_text": "",
})
check(r.status_code == 200 and r.json()["preference_filled"] is False, "全空保存视为未填写")
# 恢复一个有内容的版本供后续揭晓使用
r = client.put(f"/api/reveal/{tokA}/preference", json={
    "wish_text": "甲的愿望", "avoid_text": "甲的忌讳", "size_text": "甲的尺码",
})

# 乙、丙各填一张（丁故意不填）
client.put(f"/api/reveal/{tokB}/preference", json={
    "wish_text": "乙的愿望", "avoid_text": "乙的忌讳", "size_text": "乙的尺码",
})
client.put(f"/api/reveal/{tokC}/preference", json={
    "wish_text": "丙的愿望", "avoid_text": "", "size_text": "",
})

# 8.3 隐私：别人的链接 GET 不到他人卡片；状态中不含任何他人内容
r = client.get(f"/api/reveal/{tokB}")
check("甲的愿望" not in r.text and "丙的愿望" not in r.text,
      "B 的链接状态中不含 A/C 的偏好内容")

# 8.4 组织者接口只能看到“是否已填写”，看不到内容（即使在管理链接里）
r = client.get(f"/api/events/{peid}", headers=PH)
raw = r.text
filled = {p["name"]: p["preference_filled"] for p in r.json()["participants"]}
check(filled == {"甲": True, "乙": True, "丙": True, "丁": False},
      f"组织者只见填写标记: {filled}")
check("wish_text" not in raw and "甲的愿望" not in raw and "乙的忌讳" not in raw,
      "组织者响应中不含任何偏好卡内容字段/文本")

# 8.5 抽签成功后锁定：PUT 被拒；GET 仍可见本人只读卡片
r = client.post(f"/api/events/{peid}/draw", headers=PH)
check(r.status_code == 200, f"偏好局抽签 -> {r.status_code}")
drawn_ev = r.json()

r = client.put(f"/api/reveal/{tokA}/preference", json={
    "wish_text": "抽签后偷改", "avoid_text": "", "size_text": "",
})
check(r.status_code == 409, f"抽签后偏好卡锁定 -> {r.status_code}")

r = client.get(f"/api/reveal/{tokA}")
j = r.json()
check(j["preference_editable"] is False, "抽签后标记为不可编辑")
check(j["preference"]["wish_text"] == "甲的愿望", "抽签后本人仍能看到自己的卡片（原样未变）")

# 8.6 一次性揭晓：结果中带的是“收礼人”的偏好卡，且全应用只此一处暴露
# 直接查库找出每人的收礼人，验证响应与之一致
from app.models import Participant as _P  # noqa: E402
from app.database import SessionLocal  # noqa: E402
_db = SessionLocal()
try:
    recipient_of = {}
    for giver in _db.query(_P).filter_by(event_id=peid).all():
        rec = _db.get(_P, giver.recipient_id)
        recipient_of[giver.name] = rec.name
finally:
    _db.close()

token_by_name = {p["name"]: p["reveal_token"] for p in drawn_ev["participants"]}
card_wishes = {"甲": "甲的愿望", "乙": "乙的愿望", "丙": "丙的愿望", "丁": None}

for giver_name in ("甲", "乙", "丙", "丁"):
    gtok = token_by_name[giver_name]
    r = client.post(f"/api/reveal/{gtok}")
    check(r.status_code == 200, f"{giver_name} 揭晓成功")
    j = r.json()
    rec_name = recipient_of[giver_name]
    check(j["recipient_name"] == rec_name, f"{giver_name} 的收礼人为 {rec_name}")
    rp = j["recipient_preference"]
    if card_wishes[rec_name] is None:
        check(rp is None, f"{giver_name} 揭晓：{rec_name} 未填卡 -> recipient_preference 为 null")
    else:
        check(rp is not None and rp["wish_text"] == card_wishes[rec_name],
              f"{giver_name} 揭晓响应恰为收礼人 {rec_name} 的卡片")
    # 不包含任何“非收礼人”的卡片文本
    others = [w for n, w in card_wishes.items() if n != rec_name and w]
    check(all(w not in r.text for w in others),
          f"{giver_name} 的揭晓响应不含其他参与者的卡片内容")

# 8.7 重复揭晓仍守一次性规则，且不再次泄露偏好卡
r = client.post(f"/api/reveal/{tokA}")
check(r.status_code == 409 and "甲的愿望" not in r.text,
      "二次揭晓 409 且响应不含收礼人卡片")
r = client.get(f"/api/reveal/{tokA}")
check(r.json()["revealed"] is True and "乙的愿望" not in r.text,
      "已揭晓后 GET 状态仍不含他人卡片")

# 8.8 无效链接
r = client.put("/api/reveal/does-not-exist/preference",
               json={"wish_text": "x", "avoid_text": "", "size_text": ""})
check(r.status_code == 404, "无效链接填写偏好卡 404")

# 8.9 超长内容被拒（422）
r = client.post("/api/events", json={"name": "长度局", "participants": ["x", "y"]})
lv = r.json()
ltok = lv["participants"][0]["reveal_token"]
r = client.put(f"/api/reveal/{ltok}/preference",
               json={"wish_text": "长" * 1001, "avoid_text": "", "size_text": ""})
check(r.status_code == 422, f"偏好内容超长 422 -> {r.status_code}")

# 8.10 组织者在锁定后仍只见布尔标记
r = client.get(f"/api/events/{peid}", headers=PH)
check("wish_text" not in r.text and "甲的愿望" not in r.text,
      "锁定后组织者依然读不到偏好内容")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部测试通过 ✔")
