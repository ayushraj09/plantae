"""Durable LangGraph checkpointer shared by the chat and escalation graphs.

Graph state (conversation memory, paused interrupts) lives in the same Postgres
database as the rest of the app, so it survives deploys/restarts and is shared
between gunicorn workers and the django-q worker that resumes escalations.

Set AGENT_CHECKPOINTER=memory to fall back to the old in-process saver (tests).
Run ``python manage.py setup_checkpointer`` once per database to create tables.
"""
import os

from langgraph.checkpoint.memory import InMemorySaver


def _conninfo() -> str:
    from psycopg.conninfo import make_conninfo
    return make_conninfo(
        dbname=os.environ.get('DB_NAME'),
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD') or None,
        host=os.environ.get('DB_HOST'),
        port=os.environ.get('DB_PORT', '5432'),
        sslmode=os.environ.get('DB_SSLMODE', 'require'),
    )


def _make_pool():
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    # min_size=0 means importing this module never opens a connection, so
    # migrate/collectstatic still work while the DB is unreachable.
    return ConnectionPool(
        conninfo=_conninfo(),
        min_size=0,
        max_size=int(os.environ.get('AGENT_CHECKPOINTER_POOL', '5')),
        max_idle=300,
        check=ConnectionPool.check_connection,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )


def _build_checkpointer():
    if os.environ.get('AGENT_CHECKPOINTER', 'postgres').lower() == 'memory':
        return InMemorySaver()

    from langgraph.checkpoint.postgres import PostgresSaver
    return PostgresSaver(_make_pool())


checkpointer = _build_checkpointer()

# A forked child (the django-q worker processes on Linux) inherits the pool
# object but not its background threads, so it would wait forever for a
# connection. Give each child its own pool. The inherited pool is kept
# referenced (never closed) so the child can't close the parent's connections.
_inherited_pools = []


def _reset_pool_after_fork():
    if hasattr(checkpointer, "conn"):
        _inherited_pools.append(checkpointer.conn)
        checkpointer.conn = _make_pool()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_pool_after_fork)


def delete_thread(thread_id: str) -> None:
    """Remove all stored state for a LangGraph thread."""
    checkpointer.delete_thread(thread_id)


def has_thread(thread_id: str) -> bool:
    return checkpointer.get_tuple({"configurable": {"thread_id": thread_id}}) is not None
