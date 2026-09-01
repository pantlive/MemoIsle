# MemoIsle API

## 本地运行

在仓库根目录创建并进入 conda 环境：

```bash
conda env create -f environment.yml
conda activate memoisle
uvicorn app.main:app --app-dir backend --reload
```

默认使用 `data/memoisle.db` SQLite 数据库，API 地址为
`http://127.0.0.1:8000/api/v1`，交互文档位于
`http://127.0.0.1:8000/docs`。

可通过环境变量覆盖：

- `MEMOISLE_DATABASE_URL`：SQLAlchemy 数据库连接地址。
- `MEMOISLE_CORS_ORIGINS`：逗号分隔的 Web 来源。
- `MEMOISLE_LOCAL_USER_ID`：登录功能完成前使用的开发用户标识。
- `MEMOISLE_AUDIO_DIRECTORY`：原始录音的本地开发存储目录。

## 测试

```bash
pytest
```
