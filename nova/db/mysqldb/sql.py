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

"""
MySQLdb SQL Helpers.
"""
from oslo.config import cfg

from nova.openstack.common import log as logging


mysqldb_opts = [
    cfg.BoolOpt('query_debug',
                default=False,
                help='Enable logging of queries for debugging.')
]

CONF = cfg.CONF
CONF.register_opts(mysqldb_opts, group='mysqldb')
LOG = logging.getLogger(__name__)


class _BaseSQLQuery(object):
    """Base SQLQuery class."""
    def __init__(self, model, query, query_kwargs):
        if query is None:
            query = ''
        if query_kwargs is None:
            query_kwargs = {}
        self.query = query
        self.query_kwargs = query_kwargs
        self.model = model

    def copy(self):
        query = self.__class__(self.model, self.query,
                               self.query_kwargs[:])
        return query

    def _add_where(self, where_str, where_kwargs):
        """For SelectQuery and UpdateQuery, add a WHERE clause.  Do not
        specify the literal string 'WHERE'.  It will be prepended when the
        query is run.

        `where_str` may contain format characters for MySQLdb with mappings
        pass in via `where_kwargs`.

        Example: query = query.where('foo = %(bar)s', bar='meow')
        """
        query = self.copy()
        if query.where_str:
            query.where_str += ' AND '
        else:
            query.where_str = 'WHERE '
        query.where_str += where_str
        query.query_kwargs.update(where_kwargs)
        return query

    def _add_values(self, values, values_kwargs):
        """For InstanceQuery and UpdateQuery, add a mapping of key to
        values.  This will add `key`=%(key)s to the MySQLdb query string
        and the key=value pair to the kwargs for the query.  This means
        that MySQLdb will translate the value type for us.

        Note: Be extremely careful to not pass any user-specified keys
        to avoid SQL injection exploits.
        """
        query = self.copy()
        for v in values:
            if not isinstance(v, dict):
                raise Exception("Position arguments for values() should be "
                                "dicts.")
            query.values_dict.update(v)
        query.values_dict.update(values_kwargs)
        return query

    def _add_raw_values(self, raw_values_kwargs):
        """For InstanceQuery and UpdateQuery, add a mapping of key to
        literal values.  This will add key=value pairs to the SET part of
        an update/insert without any type translation by MySQLdb.

        Note: Be extremely careful to not pass any user-specified keys
        or values to avoid SQL injection exploits.
        """
        query = self.copy()
        query.raw_values_dict.update(raw_values_kwargs)
        return query

    def _get_set_info(self, query, kwargs):
        """Return the SET portion of an UPDATE/INSERT query."""
        if not self.values_dict and not self.raw_values_dict:
            return
        value_str = ''
        for key in self.values_dict.iterkeys():
            if value_str:
                value_str += ', '
            value_str += '`%s` = %%(%s)s' % (key, key)
        kwargs.update(self.values_dict)
        for key, value in self.raw_values_dict.iteritems():
            if value_str:
                value_str += ', '
            value_str += '`%s` = %s' % (key, value)
        if value_str:
            query += ' SET ' + value_str
        return query, kwargs

    def _execute(self, conn, query, query_kwargs):
        """Execute a query with a connection."""
        if CONF.mysqldb.query_debug:
            LOG.debug('QUERY: %s -- %s' % (query, query_kwargs))
        cursor = conn.execute(query, args=query_kwargs)
        return cursor


class SelectQuery(_BaseSQLQuery):
    """SELECT query."""
    def __init__(self, model, query=None, query_kwargs=None,
                 joined_names=None, where_str=None):
        if query is None:
            query = 'SELECT * from %s as self' % model.__table__
        if query_kwargs is None:
            query_kwargs = {}
        super(SelectQuery, self).__init__(model, query, query_kwargs)
        if where_str is None:
            where_str = ''
        self.joined_names = joined_names
        self.where_str = where_str

    def _to_models(self, rows, joins):
        """Convert the raw response from MySQLdb into a list of models."""
#        LOG.debug("Converting to models")
        results = []
        join_mappings = {}
        all_models = self.model.__all_models__
        table_model_map = all_models.__table_model_map__

        last_obj = None

        for row in rows:
            col_iter = iter(row)
            this_obj = self.model.from_response(col_iter)
            if not last_obj or last_obj['id'] != this_obj['id']:
                last_obj = this_obj
                results.append(last_obj)
            else:
                this_obj = last_obj
            for join in joins:
                if join.hidden:
                    # Just drop the data.
                    model = table_model_map[join.table_name]
                    model.from_response(col_iter)
                    continue
                join_map = join_mappings.setdefault(join.table_name, {})
                model = table_model_map[join.table_name]
                this_join_obj = model.from_response(col_iter)
                if not this_join_obj:
                    continue
                if this_join_obj['id'] not in join_map:
                    old_val = this_obj[join.target]
                    if join.use_list:
                        old_val.append(this_join_obj)
                    elif join.use_dict:
                        old_val.update(this_join_obj.to_dict())
                    elif old_val is None:
                        this_obj[join.target] = this_join_obj
                    join_map[this_join_obj['id']] = this_join_obj
            try:
                # Shouldn't happen unless schema changed.
                col_iter.next()
                # FIXME -- return something that'll reconnect and retry
                raise Exception("Unexpected values return in row.")
            except StopIteration:
                pass
#        LOG.debug("Done converting to models")
        return results

    def copy(self):
        """Create a copy of ourselves and return the new instance."""
        if self.joined_names is None:
            joined_names = None
        else:
            joined_names = self.joined_names[:]
        query = self.__class__(self.model,
                query=self.query, query_kwargs=self.query_kwargs.copy(),
                joined_names=joined_names, where_str=self.where_str)
        return query

    def join(self, *joined_names):
        """Add column names to join.  If no joined 'columns' have been
        specified when the query is executed, the model._default_joins
        list will be used.
        """
        query = self.copy()
        if query.joined_names is None:
            query.joined_names = []
        query.joined_names.extend(list(joined_names))
        return query

    def where(self, where_str, **where_kwargs):
        """Add a WHERE clause.  Do not specify the literal string 'WHERE'.
        It will be prepended when the query is run.

        `where_str` may contain format characters for MySQLdb with mappings
        pass in via `where_kwargs`.

        Example: query = query.where('foo = %(bar)s', bar='meow')
        """
        return self._add_where(where_str, where_kwargs)

    def _form_query(self):
        """Return a query string and keyword args to pass to MySQLdb's
        execute().
        """
        query = self.query
        kwargs = self.query_kwargs.copy()
        if self.joined_names is None:
            joined_names = self.model._default_joins
        else:
            joined_names = self.joined_names[:]
        joins = []
        for joined_name in joined_names:
            join = getattr(self.model, joined_name)
            for joined_name2 in join.prereq_join_names:
                j2 = getattr(self.model, joined_name2)
                query += '\n  %s %s as %s' % (j2.join_type, j2.table_name,
                                              j2.target)
                query += '\n    ON %s' % j2.join_str
                kwargs.update(j2.join_kwargs)
                joins.append(j2)
            query += '\n  %s %s as %s' % (join.join_type, join.table_name,
                                          join.target)
            query += '\n    ON %s' % join.join_str
            kwargs.update(join.join_kwargs)
            joins.append(join)
        if self.where_str:
            query += ' ' + self.where_str
        return query, kwargs, joins

    def fetchall(self, conn):
        """Return all models for the SELECT."""
        query, args, joins = self._form_query()
        cursor = self._execute(conn, query, args)
        rows = cursor.fetchall()
        return self._to_models(rows, joins)

    def first(self, conn):
        """Return the first model for the SELECT."""
        objs = self.fetchall(conn)
        if not objs:
            return None
        return objs[0]


class InsertQuery(_BaseSQLQuery):
    """INSERT INTO query.  Be care with raw_values.  See each method
    doc string below.
    """
    def __init__(self, model, query=None, query_kwargs=None,
                 raw_values=None, values=None):
        if query is None:
            query = 'INSERT INTO %s' % model.__table__
        super(InsertQuery, self).__init__(model, query, query_kwargs)
        if raw_values is None:
            raw_values = {}
        if values is None:
            values = {}
        self.values_dict = values
        self.raw_values_dict = raw_values

    def copy(self):
        """Create a copy of ourselves and return the new instance."""
        query = self.__class__(self.model,
                query=self.query, query_kwargs=self.query_kwargs.copy(),
                raw_values=self.raw_values_dict.copy(),
                values=self.values_dict.copy())
        return query

    def raw_values(self, **raw_values_kwargs):
        """This will add key=value pairs to the SET part of the insert
        without any type translation by MySQLdb.

        Note: Be extremely careful to not pass any user-specified keys
        or values to avoid SQL injection exploits.
        """
        return self._add_raw_values(raw_values_kwargs)

    def values(self, *values, **values_kwargs):
        """This will add `key`=%(key)s to the MySQLdb query string
        and the key=value pair to the kwargs for the query.  This means
        that MySQLdb will translate the value type for us.

        Note: Be extremely careful to not pass any user-specified keys
        to avoid SQL injection exploits.
        """
        return self._add_values(values, values_kwargs)

    def _form_query(self):
        """Return a query string and keyword args to pass to MySQLdb's
        execute().
        """
        query, kwargs = self._get_set_info(self.query,
                                           self.query_kwargs.copy())
        return query, kwargs

    def insert(self, conn):
        """Execute the INSERT query.  The number of rows updated will be
        returned.
        """
        if not self.values_dict:
            raise Exception('No values specified for INSERT')
        query, kwargs = self._form_query()
        cursor = self._execute(conn, query, kwargs)
        return cursor.rowcount


class UpdateQuery(_BaseSQLQuery):
    """UPDATE query.  Be care with raw_values.  See each method doc string
    below.
    """
    def __init__(self, model, query=None, query_kwargs=None,
                 raw_values=None, values=None, where_str=None):
        if query is None:
            query = 'UPDATE %s' % model.__table__
        super(UpdateQuery, self).__init__(model, query, query_kwargs)
        if where_str is None:
            where_str = ''
        if raw_values is None:
            raw_values = {}
        if values is None:
            values = {}
        self.where_str = where_str
        self.values_dict = values
        self.raw_values_dict = raw_values

    def copy(self):
        """Create a copy of ourselves and return the new instance."""
        query = self.__class__(self.model,
                query=self.query, query_kwargs=self.query_kwargs.copy(),
                raw_values=self.raw_values_dict.copy(),
                values=self.values_dict.copy(), where_str=self.where_str)
        return query

    def raw_values(self, **raw_values_kwargs):
        return self._add_raw_values(raw_values_kwargs)

    def values(self, *values, **values_kwargs):
        """This will add `key`=%(key)s to the MySQLdb query string
        and the key=value pair to the kwargs for the query.  This means
        that MySQLdb will translate the value type for us.

        Note: Be extremely careful to not pass any user-specified keys
        to avoid SQL injection exploits.
        """
        return self._add_values(values, values_kwargs)

    def _form_query(self):
        """Return a query string and keyword args to pass to MySQLdb's
        execute().
        """
        query, kwargs = self._get_set_info(self.query,
                                           self.query_kwargs.copy())
        if self.where_str:
            query += ' ' + self.where_str
        return query, kwargs

    def where(self, where_str, **where_kwargs):
        """Add a WHERE clause.  Do not specify the literal string 'WHERE'.
        It will be prepended when the query is run.

        `where_str` may contain format characters for MySQLdb with mappings
        pass in via `where_kwargs`.

        Example: query = query.where('foo = %(bar)s', bar='meow')
        """
        return self._add_where(where_str, where_kwargs)

    def update(self, conn):
        """Execute the UPDATE query.  The number of rows updated will be
        returned.
        """
        if not self.values_dict:
            raise Exception('No values specified for UPDATE')
        query, kwargs = self._form_query()
        cursor = self._execute(conn, query, kwargs)
        return cursor.rowcount
