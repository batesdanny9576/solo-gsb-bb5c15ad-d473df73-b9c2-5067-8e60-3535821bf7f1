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

# ---------- 7. 礼物偏好卡 ----------
print("== 礼物偏好卡 ==")
r = client.post("/api/events", json={
    "name": "偏好局",
    "participants": ["甲", "乙", "丙"],
})
pev = r.json()
pid, ptok = pev["id"], pev["organizer_token"]
PH = {"X-Organizer-Token": ptok}
toks = {p["name"]: p["reveal_token"] for p in pev["participants"]}

# 初始：未填写，GET 自己的链接可见空偏好卡
r = client.get(f"/api/reveal/{toks['甲']}")
check(r.status_code == 200, "GET 本人链接 200")
pref = r.json()["preference"]
check(pref["filled"] is False and pref["wishes"] == "" and pref["updated_at"] is None,
      "初始偏好卡为空且未填写")

# 组织者只看到 preference_filled=False，看不到内容
r = client.get(f"/api/events/{pid}", headers=PH)
raw = r.text
pa = next(p for p in r.json()["participants"] if p["name"] == "甲")
check(pa["preference_filled"] is False, "组织者见甲未填写")
check("preference_wishes" not in raw and "preference_dislikes" not in raw
      and "preference_sizes" not in raw, "组织者响应不含任何偏好卡内容字段")

# 甲填写偏好卡
r = client.put(f"/api/reveal/{toks['甲']}/preferences", json={
    "wishes": "悬疑小说", "dislikes": "对坚果过敏", "sizes": "上衣 L",
})
check(r.status_code == 200 and r.json()["filled"] is True and r.json()["updated_at"],
      "甲保存偏好卡成功，返回已填写与时间戳")

# 组织者只能看到 filled 变为 True，仍看不到内容
r = client.get(f"/api/events/{pid}", headers=PH)
pa = next(p for p in r.json()["participants"] if p["name"] == "甲")
check(pa["preference_filled"] is True, "组织者见甲已填写")
check("悬疑小说" not in r.text and "坚果" not in r.text and "上衣 L" not in r.text,
      "组织者响应中不含偏好内容")

# 甲可反复修改
r = client.put(f"/api/reveal/{toks['甲']}/preferences", json={
    "wishes": "  机械键盘  ", "dislikes": "不喝酒", "sizes": "鞋码 41",
})
check(r.status_code == 200 and r.json()["wishes"] == "机械键盘", "甲再次修改成功（首尾空白被去除）")
r = client.get(f"/api/reveal/{toks['甲']}")
check(r.json()["preference"]["wishes"] == "机械键盘", "再次 GET 看到的是最新内容")

# 乙的链接看不到甲的内容
r = client.get(f"/api/reveal/{toks['乙']}")
body = r.text
check("机械键盘" not in body and "不喝酒" not in body and "鞋码 41" not in body,
      "他人链接中不出现甲的偏好内容")
check(r.json()["preference"]["filled"] is False, "乙自己的偏好卡仍为空")

# 抽签前揭晓不允许
r = client.post(f"/api/reveal/{toks['甲']}")
check(r.status_code == 409 and "尚未" in r.json()["detail"], "抽签前揭晓被拒绝")

# 非法输入
r = client.put(f"/api/reveal/{toks['甲']}/preferences", json={"wishes": "x" * 5000})
check(r.status_code == 422, "超长字段 422")
r = client.put("/api/reveal/does-not-exist/preferences", json={"wishes": "x"})
check(r.status_code == 404, "无效链接填写偏好卡 404")

# 抽签
r = client.post(f"/api/events/{pid}/draw", headers=PH)
check(r.status_code == 200, f"偏好局抽签成功 -> {r.status_code}")
drawn = r.json()

# 抽签后偏好卡锁定
r = client.put(f"/api/reveal/{toks['甲']}/preferences", json={"wishes": "想改"})
check(r.status_code == 409, "抽签后修改偏好卡被拒绝（锁定）")

# 状态接口仍可读本人偏好卡（锁定的只读副本），但不含任何他人内容
r = client.get(f"/api/reveal/{toks['甲']}")
j = r.json()
check(j["preference"]["wishes"] == "机械键盘", "锁定后仍可只读查看本人偏好卡")
check("recipient" not in r.text, "状态接口不泄露收礼对象及其偏好")

# 揭晓后一次性拿到收礼人姓名 + 对方偏好卡
giver = next(p for p in drawn["participants"] if p["name"] == "甲")
r = client.post(f"/api/reveal/{toks['甲']}")
check(r.status_code == 200, f"甲揭晓成功 -> {r.status_code}")
rev = r.json()
recipient_name = rev["recipient_name"]
check("recipient_preference" in rev, "揭晓响应包含对方偏好卡")

# 直接读收礼人的链接，核对偏好卡内容一致（只有抽中者的揭晓结果才带这份内容）
r2 = client.get(f"/api/reveal/{toks[recipient_name]}")
expected_pref = r2.json()["preference"]
check(rev["recipient_preference"]["name"] == recipient_name, "偏好卡归属姓名正确")
check(rev["recipient_preference"]["wishes"] == expected_pref["wishes"]
      and rev["recipient_preference"]["dislikes"] == expected_pref["dislikes"]
      and rev["recipient_preference"]["sizes"] == expected_pref["sizes"]
      and rev["recipient_preference"]["filled"] == expected_pref["filled"],
      "揭晓所得对方偏好卡与本人填写的内容一致")

# 二次揭晓：409 且不再带偏好卡 / 结果
r = client.post(f"/api/reveal/{toks['甲']}")
check(r.status_code == 409, "二次揭晓仍被拒绝")
check("recipient" not in r.text and "机械键盘" not in r.text,
      "二次揭晓响应不含结果与偏好内容")
r = client.get(f"/api/reveal/{toks['甲']}")
check(r.json()["revealed"] is True, "状态显示已揭晓")

# 乙揭晓：响应里的偏好卡只属于乙的收礼人，且不会出现甲的内容（乙的收礼人≠甲时）
r = client.post(f"/api/reveal/{toks['乙']}")
check(r.status_code == 200, f"乙揭晓成功 -> {r.status_code}")
body = r.text
if r.json()["recipient_name"] != "甲":
    check("机械键盘" not in body and "不喝酒" not in body and "鞋码 41" not in body,
          "非收礼人偏好卡不出现在乙的揭晓结果中")
else:
    check("机械键盘" in body, "乙的收礼人恰为甲时，才在结果中看到甲的偏好卡")

# 两人局：双方都未填写 -> 揭晓时对方偏好卡 filled=False
r = client.post("/api/events", json={"name": "空卡局", "participants": ["a", "b"]})
ev2 = r.json()
eid2, tok2 = ev2["id"], ev2["organizer_token"]
ta = next(p for p in ev2["participants"] if p["name"] == "a")["reveal_token"]
client.post(f"/api/events/{eid2}/draw", headers={"X-Organizer-Token": tok2})
r = client.post(f"/api/reveal/{ta}")
check(r.status_code == 200, "空卡局揭晓成功")
check(r.json()["recipient_preference"] == {
    "name": r.json()["recipient_name"], "wishes": "", "dislikes": "",
    "sizes": "", "filled": False,
}, "对方未填写时偏好卡为空卡结构")

# 全部清空 -> 回到未填写
r = client.post("/api/events", json={"name": "清空局", "participants": ["a", "b"]})
ev3 = r.json()
ta3 = next(p for p in ev3["participants"] if p["name"] == "a")["reveal_token"]
r = client.put(f"/api/reveal/{ta3}/preferences",
               json={"wishes": "x", "dislikes": "y", "sizes": "z"})
check(r.json()["filled"] is True, "填写后为已填")
r = client.put(f"/api/reveal/{ta3}/preferences",
               json={"wishes": "   ", "dislikes": "", "sizes": ""})
check(r.json()["filled"] is False and r.json()["updated_at"] is None,
      "全部清空后回到未填写状态")
r = client.get(f"/api/reveal/{ta3}")
check(r.json()["preference"]["wishes"] == "" and r.json()["preference"]["filled"] is False,
      "空白内容被规范化为空串")

# ---------- 8. 旧数据库自动补列（持久化迁移，幂等） ----------
print("== 旧库迁移 ==")
import sqlite3  # noqa: E402

old_path = os.path.join(tmp, "old_schema.db")
con = sqlite3.connect(old_path)
con.execute(
    "CREATE TABLE events (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, "
    "organizer_token VARCHAR(64) UNIQUE NOT NULL, status VARCHAR(20) NOT NULL, "
    "failure_reason VARCHAR(1000), created_at DATETIME NOT NULL)"
)
con.execute(
    "CREATE TABLE participants (id INTEGER PRIMARY KEY, event_id INTEGER NOT NULL, "
    "name VARCHAR(100) NOT NULL, reveal_token VARCHAR(64) UNIQUE NOT NULL, "
    "recipient_id INTEGER, revealed BOOLEAN NOT NULL DEFAULT 0, "
    "created_at DATETIME NOT NULL)"
)
con.execute(
    "INSERT INTO events VALUES (1, '旧局', 'oldtok', 'pending', NULL, '2026-01-01 00:00:00')"
)
con.execute(
    "INSERT INTO participants VALUES (1, 1, '老兵', 'oldreveal', NULL, 0, "
    "'2026-01-01 00:00:00')"
)
con.commit()
con.close()

from sqlalchemy import create_engine as _create_engine  # noqa: E402

from app.database import _apply_migrations  # noqa: E402

old_engine = _create_engine(f"sqlite:///{old_path}", future=True)
_apply_migrations(old_engine)  # 首次：补列
_apply_migrations(old_engine)  # 再次：幂等不报错
cols = {r[1] for r in sqlite3.connect(old_path).execute("PRAGMA table_info(participants)")}
check({"preference_wishes", "preference_dislikes", "preference_sizes",
       "preference_updated_at"} <= cols, "旧 participants 表自动补出 4 个偏好列")
# 存量数据仍在，且新列默认 NULL（视为未填写）
row = sqlite3.connect(old_path).execute(
    "SELECT name, preference_wishes FROM participants WHERE id = 1"
).fetchone()
check(row == ("老兵", None), f"存量参与者数据保留: {row}")
old_engine.dispose()

# ---------- 9. health ----------
r = client.get("/health")
check(r.status_code == 200 and r.json()["status"] == "ok", "health ok")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部测试通过 ✔")
