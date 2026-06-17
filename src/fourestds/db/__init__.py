"""数据库层:三层单木模型与 run 补。

- schema.py : 标准库 sqlite3 DDL(无重依赖,保证 ``4estds db init`` 可跑)
- models.py : SQLAlchemy 2.0 ORM(本地 ``uv sync --extra db`` 后使用)
"""
