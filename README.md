# 🎁 秘密赠礼抽签（Secret Santa）

一个自托管的秘密赠礼抽签 Web 应用：组织者录入参与者与禁配关系后一键抽签，系统为每位参与者生成**只能成功揭晓一次**的随机链接。

技术栈：**Python · FastAPI · React · SQLite**，前后端打包进单个镜像。

## 功能与约束保证

- **完整匹配**：每人恰好送出一份、收到一份礼物（参与者集合上的一个置换）。
- **硬性规则**：无人抽中自己；不命中任何禁配关系（禁配按无向对处理，双方互不能抽中对方）。
- **无解明确告知**：无法匹配时返回具体原因（例如“张三只能分配给李四，人数不够”），**不写入任何部分结果**，活动保持可编辑，调整后可重新抽签。
- **一次性随机链接**：每位参与者获得独立随机链接；点击揭晓后服务端原子地标记“已揭晓”，并发访问也只有一次能看到结果，再次打开只显示“已揭晓”。
- **对组织者保密**：组织者管理页只能看到“已揭晓 / 未揭晓”状态，**看不到任何人抽到了谁**。
- 抽签完成后参与者名单与禁配关系自动锁定。

## 一条命令启动

需要已安装 Docker 与 Docker Compose（v2）：

```bash
docker compose up -d --build
```

启动时容器会自动完成：Python/Node 依赖安装（构建阶段）、SQLite 建表初始化（入口脚本，幂等）。

然后访问：

- 应用地址：**http://localhost:8000**
- 健康检查：**http://localhost:8000/health**

停止：`docker compose down`（数据保留在命名卷中）；连同数据一起删除：`docker compose down -v`。

## 必要配置（均有默认值，可不设置）

通过环境变量或 `.env` 文件配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_PORT` | `8000` | 宿主机映射端口（容器内固定监听 8000） |
| `DATABASE_PATH` | `/data/secret_santa.db` | SQLite 数据库文件路径，位于持久化卷内 |
| `DATABASE_URL` | `sqlite:////data/secret_santa.db` | 数据库连接串，一般无需修改 |

修改宿主机端口示例：

```bash
APP_PORT=9000 docker compose up -d --build
# 访问 http://localhost:9000
```

数据保存在 Docker 命名卷 `secret-santa-data` 中；也可以在 `docker-compose.yml` 里改为绑定挂载（如 `./data:/data`）。

## 使用流程

1. 打开 http://localhost:8000 ，填写活动名称、参与者名单（每行一个）和禁配关系（每行“甲, 乙”，可留空），点击“创建活动”。
2. 在活动管理页继续增删参与者 / 禁配关系，然后点击“发起抽签”。
   - 若无解，页面会显示具体原因且不产生结果，修改后重试即可。
3. 抽签成功后，管理页列出每位参与者的专属链接，分别私发给本人。
4. 参与者打开链接 → 点击“揭晓我的赠礼对象”，**结果仅展示这一次**，离开后无法再看。
5. 组织者管理页只显示揭晓状态，不知道具体匹配。

> 活动管理链接形如 `/event/<活动ID>?token=<组织者令牌>`，令牌同时保存在浏览器 localStorage 中，请妥善保管，不要直接发给普通参与者。

## API 摘要

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/events` | 创建活动（可附带参与者与禁配关系） |
| GET | `/api/events/{id}` | 组织者查看活动（需令牌，不返回匹配结果） |
| POST | `/api/events/{id}/participants` | 新增参与者 |
| DELETE | `/api/events/{id}/participants/{pid}` | 删除参与者 |
| PUT | `/api/events/{id}/forbidden-pairs` | 整体覆盖禁配关系 |
| POST | `/api/events/{id}/draw` | 发起抽签；无解返回 `409` 及原因，不产生部分结果 |
| GET | `/api/reveal/{token}` | 查看链接状态（待抽签 / 已揭晓等） |
| POST | `/api/reveal/{token}` | **一次性揭晓**，重复调用返回 `409` |
| GET | `/health` | 健康检查 |

组织者令牌通过请求头 `X-Organizer-Token: <token>` 或查询参数 `?token=` 传递。

## 本地开发（不使用 Docker）

后端：

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DATABASE_PATH=../data/dev.db STATIC_DIR=../frontend/dist \
  uvicorn app.main:app --reload --port 8000
```

前端（另开终端）：

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 自动代理到 8000
```

前端类型检查 / 构建：`npm run build`，产物输出到 `frontend/dist`，生产镜像由 FastAPI 托管并支持前端路由回退。

## 项目结构

```
.
├── backend/
│   ├── app/
│   │   ├── main.py        # FastAPI 路由、原子揭晓、SPA 托管
│   │   ├── matching.py    # 随机完美匹配 + Hall 定理无解原因
│   │   ├── models.py      # Event / Participant / ForbiddenPair
│   │   ├── schemas.py     # 请求校验
│   │   ├── database.py    # SQLite 引擎与建表
│   │   └── config.py
│   ├── entrypoint.sh      # 启动即建表并运行 uvicorn
│   └── requirements.txt
├── frontend/              # React + Vite
│   └── src/pages/         # 创建页 / 组织者页 / 揭晓页
├── Dockerfile             # 多阶段：Node 构建前端 + Python 运行
└── docker-compose.yml     # 一条命令启动 + 数据卷
```
