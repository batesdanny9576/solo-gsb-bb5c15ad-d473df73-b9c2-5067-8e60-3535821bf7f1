"""秘密赠礼匹配算法。

要求：
- 每人恰好送出一份、收到一份（参与者集合上的一个置换 / 完美匹配）；
- 无人抽中自己；
- 不命中任何禁配关系（禁配为无向对，双向禁止）；
- 匹配随机化；
- 无解时不产生任何部分结果，并给出可操作的无解原因。

使用 Kuhn 增广路算法（二分图完美匹配），候选顺序随机洗牌以获得随机结果；
无解时用 Hall 定理找出“可选集合过小”的人群作为证据。
"""
import random

Neighbors = dict[int, list[int]]


class NoSolution(Exception):
    """无解：携带面向组织者的中文说明。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _kuhn(u: int, adj: Neighbors, match_to: dict[int, int], seen: set[int]) -> bool:
    for v in adj[u]:
        if v in seen:
            continue
        seen.add(v)
        if v not in match_to or _kuhn(match_to[v], adj, match_to, seen):
            match_to[v] = u
            return True
    return False


def _find_hall_witness(ids: list[int], adj: Neighbors) -> tuple[set[int], set[int]]:
    """返回 (U, T)：U 中所有人可接收对象的并集 T 满足 |T| < |U|。

    从每个左点出发做确定性增广搜索，收集“可到达的左点”与“可到达的右点”。
    当且仅当不存在完美匹配时，存在满足 Hall 条件的起点；该 Hall 违例
    恰好说明 U 里的人被迫挤在 T 里，不可能每人拿到不同的接收对象。
    """
    for start in ids:
        match_to: dict[int, int] = {}
        # 先为除 start 外的人求一个（可能不完美的）最大匹配
        for u in ids:
            if u == start:
                continue
            _kuhn(u, adj, match_to, set())
        # 从 start 沿“非匹配边去、匹配边回”搜索增广路
        reachable_left: set[int] = set()
        reachable_right: set[int] = set()
        stack = [start]
        while stack:
            u = stack.pop()
            if u in reachable_left:
                continue
            reachable_left.add(u)
            for v in adj[u]:
                reachable_right.add(v)
                owner = match_to.get(v)
                if owner is not None and owner not in reachable_left:
                    stack.append(owner)
        if len(reachable_right) < len(reachable_left):
            return reachable_left, reachable_right
    # 理论上不会走到这里（无完美匹配必有 Hall 违例）
    return set(ids), {v for vs in adj.values() for v in vs}

def solve(
    participants: list,
    forbidden_pairs: list,
    rng: random.Random | None = None,
) -> dict[int, int]:
    """计算 giver_id -> recipient_id 的完美匹配。

    participants: 含 id/name 的对象列表；
    forbidden_pairs: 含 lower_id/higher_id 的对象列表；
    成功返回完整映射；无解抛 NoSolution（调用方据此不写入任何部分结果）。
    """
    rng = rng or random.SystemRandom()
    n = len(participants)

    if n < 2:
        raise NoSolution("至少需要 2 名参与者才能发起抽签。")

    ids = [p.id for p in participants]
    id_set = set(ids)
    names = {p.id: p.name for p in participants}

    forbidden: set[tuple[int, int]] = set()
    for pair in forbidden_pairs:
        a, b = pair.lower_id, pair.higher_id
        if a in id_set and b in id_set and a != b:
            forbidden.add((a, b))
            forbidden.add((b, a))

    # 左点=送礼人，右点=收礼人；每人的候选=除自己和禁配对象外的所有人。
    # 保留洗牌后的列表顺序：Kuhn 按此顺序尝试增广，决定最终匹配的随机性。
    adj: Neighbors = {}
    for u in ids:
        candidates = [v for v in ids if v != u and (u, v) not in forbidden]
        rng.shuffle(candidates)
        adj[u] = candidates

    match_to: dict[int, int] = {}  # 右点(收礼人) -> 左点(送礼人)
    for u in ids:
        if not _kuhn(u, adj, match_to, set()):
            left, right = _find_hall_witness(ids, adj)
            who = "、".join(names[i] for i in ids if i in left)
            if right:
                options = "、".join(names[i] for i in ids if i in right)
                raise NoSolution(
                    f"无解：{who} 只能分配给 {options}，人数不够（"
                    f"{len(left)} 人只有 {len(right)} 个可选接收对象）。"
                    "请删除部分禁配关系后重试。"
                )
            raise NoSolution(
                f"无解：{who} 没有任何可分配的接收对象（不能抽自己，且与其余所有人均为禁配）。"
                "请调整禁配关系后重试。"
            )

    if set(match_to.keys()) != id_set or set(match_to.values()) != id_set:
        # 防御性检查：绝不返回部分结果
        raise NoSolution("无解：无法生成完整匹配。")

    return {giver: receiver for receiver, giver in match_to.items()}
