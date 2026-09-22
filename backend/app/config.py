"""运行期配置，全部可通过环境变量覆盖。"""
import os
from pathlib import Path

# SQLite 数据库文件路径（默认放在容器挂载卷 /data 下）
DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/secret_santa.db")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATABASE_PATH}")

# 前端构建产物目录（Docker 中为 /app/static）
STATIC_DIR = os.environ.get("STATIC_DIR", "static")


def ensure_data_dir() -> None:
    """确保数据库父目录存在，随启动完成初始化。"""
    if DATABASE_URL.startswith("sqlite:///"):
        Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
