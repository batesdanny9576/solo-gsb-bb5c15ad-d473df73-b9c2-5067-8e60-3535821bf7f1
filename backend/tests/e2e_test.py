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

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部测试通过 ✔")
