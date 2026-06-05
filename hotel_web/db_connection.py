import pymysql
from flask import g, has_app_context

from config import DB_CONFIG


def _create_conn():
    return pymysql.connect(**DB_CONFIG)


def get_db():
    if has_app_context():
        if "db_conn" not in g:
            g.db_conn = _create_conn()
        return g.db_conn
    return _create_conn()


def close_db(error=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        conn.close()


class DBConnection:
    @property
    def conn(self):
        return get_db()

    def get_cursor(self):
        return self.conn.cursor()

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        if has_app_context():
            close_db()
