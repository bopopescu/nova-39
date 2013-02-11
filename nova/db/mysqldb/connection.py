# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Rackspace Hosting
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""MySQdb connection handling."""

import functools
import Queue
import sys
import threading
import time

import _mysql_exceptions
import MySQLdb
from MySQLdb.constants import CLIENT as mysql_client_constants
from oslo.config import cfg

from nova.db.mysqldb import exception as mysqldb_exc
from nova.openstack.common.db import exception as db_exc
from nova.openstack.common import log as logging

MySQLdb.threadsafety = 1
CONF = cfg.CONF

mysqldb_opts = [
    cfg.StrOpt('database',
               default='nova',
               help='the mysql database to use'),
    cfg.StrOpt('username',
               default='nova',
               help='the mysql username'),
    cfg.StrOpt('password',
               default='',
               help='the mysql password'),
    cfg.StrOpt('hostname',
               default='127.0.0.1',
               help='the hostname or IP of the mysql server'),
    cfg.IntOpt('port',
               default=3306,
               help='the TCP port of the mysql server'),
    cfg.IntOpt('max_connections',
               default=20,
               help='maximum number of concurrent mysql connections'),
]

CONF.register_opts(mysqldb_opts, group='mysqldb')
LOG = logging.getLogger(__name__)


def wrap_db_errors(f):
    @functools.wraps(f)
    def inner(self, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except IOError as e:
            self.close()
            LOG.warning(_("IOError detected...closing connection."))
            raise mysqldb_exc.DBIOError(e)
        except _mysql_exceptions.IntegrityError as e:
            code = e[0]
            if code == 1062:
                # FIXME(comstud): Use RE to get column names.
                columns = []
                raise db_exc.DBDuplicateEntry(columns, e)
            LOG.exception(_('DB exception wrapped.'))
            raise db_exc.DBError(e)
        except _mysql_exceptions.OperationalError as e:
            code = e[0]
            if code == 1213:
                raise db_exc.DBDeadlock(e)
            elif code == 2003:
                raise mysqldb_exc.DBCantConnect(e)
            elif code == 2006:
                raise mysqldb_exc.DBWentAway(e)
            LOG.exception(_('DB exception wrapped.'))
            raise db_exc.DBError(e)
    functools.update_wrapper(inner, f)
    return inner


class _Connection(object):
    def __init__(self, pool):
        self._conn = None
        self._ensure_connection()
        self.pool = pool

    def __enter__(self):
        return self

    def __exit__(self, exc, value, tb):
        try:
            if not self._conn:
                return
            if exc:
                try:
                    self.rollback()
                except Exception:
                    # Eat this exception so that the original
                    # one gets raised.
                    pass
                return
            self.commit()
        finally:
            self.pool.put(self)

    def close(self):
        if not self._conn:
            return
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = None

    def cursor(self):
        return self._conn.cursor()

    def _get_columns(self, name):
        cursor = self.execute('DESCRIBE %s' % name)
        rows = cursor.fetchall()
        return [r[0] for r in rows]

    def _get_tables(self):
        cursor = self.execute('SHOW TABLES')
        rows = cursor.fetchall()
        tables = {}
        for row in rows:
            table_name = row[0]
            columns = self._get_columns(table_name)
            tables[table_name] = dict(columns=columns)
        return tables

    def _get_migrate_version(self):
        cursor = self.execute('SELECT version from migrate_version WHERE '
                              'repository_id = %s',
                              (CONF.mysqldb.database, ))
        rows = cursor.fetchall()
        if not rows:
            # FIXME(comstud)
            raise SystemError
        return rows[0][0]

    def get_schema(self):
        self._ensure_connection()
        with self._conn:
            tables = self._get_tables()
            version = self._get_migrate_version()
            return {'version': version,
                    'tables': tables}

    def _init_connection(self):
        pass

    @wrap_db_errors
    def _create_connection(self, conn_args):
        return MySQLdb.connect(**conn_args)

    def _ensure_connection(self):
        if self._conn:
            return self._conn
        conn_args = {
            'db': CONF.mysqldb.database,
            'host': CONF.mysqldb.hostname,
            'port': CONF.mysqldb.port,
            'user': CONF.mysqldb.username,
            'passwd': CONF.mysqldb.password,
            'client_flag': mysql_client_constants.FOUND_ROWS}
        while True:
            try:
                info_str = _("Attempting connection to mysql server "
                             "'%(host)s:%(port)s'")
                LOG.info(info_str % conn_args)
                self._conn = self._create_connection(conn_args)
                self._init_connection()
            except mysqldb_exc.RetryableErrors as e:
                self.close()
                err_info = dict(conn_args)
                err_info['err'] = str(e)
                err_str = _("Error connecting to mysql server "
                            "'%(host)s:%(port)s: %(err)s'")
                LOG.error(err_str % err_info)
                # TODO(comstud): Make configurable and backoff.
                time.sleep(1)
                continue
            info_str = _("Connected to to mysql server '%(host)s:%(port)s'")
            LOG.info(info_str % conn_args)
            return self._conn

    @wrap_db_errors
    def commit(self):
        self._conn.commit()

    @wrap_db_errors
    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            # To restore sanity, close the connection if
            # we get an error during a rollback.
            exc_info = sys.exc_info()
            self.close()
            raise exc_info[0], exc_info[1], exc_info[2]

    @wrap_db_errors
    def execute(self, query, args=None):
        self._ensure_connection()
        cursor = self.cursor()
        cursor.execute(query, args)
        return cursor


class ConnectionPool(object):
    def __init__(self):
        self.conns_available = []
        self.queue = Queue.Queue(maxsize=CONF.mysqldb.max_connections)
        self.lock = threading.Lock()
        self.max_conns = CONF.mysqldb.max_connections
        self.num_conns = 0

    def _create_conn(self):
        self.num_conns += 1
        return _Connection(self)

    def get(self):
        while True:
            # We have to be careful with greenthreads running within
            # the same Thread.  We can't do any real blocking because
            # both Queue and threading.Lock are not monkey patched and
            # the current thread may hold locks from another greenthread.
            try:
                return self.queue.get(block=False)
            except Queue.Empty:
                pass
            if self.num_conns == self.max_conns:
                time.sleep(0.1)
                continue
            if not self.lock.acquire(False):
                time.sleep(0.1)
                continue
            # Check again now that we are synchronized.
            if self.num_conns == self.max_conns:
                # Queue became full between the check above
                # and now.
                self.lock.release()
                time.sleep(0.1)
                continue
            # We can create a connection.
            try:
                return self._create_conn()
            finally:
                self.lock.release()

    def put(self, conn):
        try:
            self.queue.put(conn, False)
        except Queue.Full:
            # Just drop the connection.  Somehow we exceeded the
            # pool size.
            try:
                conn.close()
            except Exception:
                pass
