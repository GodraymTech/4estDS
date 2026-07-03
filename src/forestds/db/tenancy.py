"""多租户上下文助手 (PostGIS RLS)。

RLS 策略以会话级 GUC ``app.tenant_id`` 做隔离 (见 deploy/postgis/rls.sql)。
应用在取得数据库连接后、执行任何业务查询前, 调用 set_tenant() 绑定当前租户;
未绑定时策略拒绝所有行 (默认安全)。

与具体驱动解耦: 只要求传入符合 DB-API 2.0 的连接 (psycopg 等)。
本地 SQLite 部署无 RLS, 调用为安全空操作。
"""
from __future__ import annotations

# 会话 GUC 名, 与 RLS 策略中的 current_setting 一致。
TENANT_GUC = "app.tenant_id"
# 单租户/存量部署的缺省租户 (与 rls.sql 列默认值一致)。
DEFAULT_TENANT = "default"


def set_tenant(conn, tenant_id: str | None) -> None:
    """在当前连接会话绑定租户 (参数化防注入)。

    用 set_config(name, value, is_local=false): 作用于整个会话/连接;
    连接池归还前应由下一次 set_tenant 覆盖。
    非 PostgreSQL 连接 (如 SQLite) 无 set_config, 视为无 RLS 的安全空操作。
    """
    tenant = tenant_id or DEFAULT_TENANT
    cur = conn.cursor()
    try:
        cur.execute("SELECT set_config(%s, %s, false)", (TENANT_GUC, tenant))
    except Exception:  # noqa: BLE001 - SQLite/无 RLS 场景安全跳过
        pass
    finally:
        cur.close()


def reset_tenant(conn) -> None:
    """重置会话租户 (连接池归还前调用, 避免租户残留)。"""
    cur = conn.cursor()
    try:
        cur.execute("SELECT set_config(%s, NULL, false)", (TENANT_GUC,))
    except Exception:  # noqa: BLE001
        pass
    finally:
        cur.close()
