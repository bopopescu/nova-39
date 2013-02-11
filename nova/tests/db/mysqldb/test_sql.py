# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright (c) 2012 Rackspace Hosting
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
Tests For Compute w/ Cells
"""
from nova.db.mysqldb import models
from nova.db.mysqldb import sql
from nova import test


_FakeJoin = models.Join('joined_table',
                        'joined_table.foo = self.foo')


class FakeModel(object):
    __table__ = 'fake_table'
    _default_joins = []
    joined_col1 = _FakeJoin = models.Join('joined_table1',
                        'joined_col1.foo = self.foo')
    joined_col2 = _FakeJoin = models.Join('joined_table2',
                        'joined_col2.foo = self.foo')


class MysqlDBSQLQueryTestCase(test.TestCase):
    def setUp(self):
        super(MysqlDBSQLQueryTestCase, self).setUp()
        self.model = FakeModel
        self.table = FakeModel.__table__
        self.model.joined_col1.target = 'joined_col1'
        self.model.joined_col2.target = 'joined_col2'

    def test_select_query_form(self):
        base_expected = 'SELECT * from %s as self' % self.table
        query = sql.SelectQuery(self.model)
        expected = (base_expected, {}, [])
        self.assertEqual(expected, query._form_query())

        orig_query = query
        query = query.where('foo = bar')
        # Make sure original query is unmodified
        self.assertEqual(expected, orig_query._form_query())
        expected = (base_expected + " WHERE foo = bar", {}, [])
        self.assertEqual(expected, query._form_query())

        # Add another where
        orig_query = query
        query = query.where('dog != cat')
        # Make sure original query is unmodified
        self.assertEqual(expected, orig_query._form_query())
        expected = (base_expected + " WHERE foo = bar AND dog != cat",
                    {}, [])
        self.assertEqual(expected, query._form_query())

        # Add a join
        orig_query = query
        query = query.join('joined_col1')
        # Make sure original query is unmodified
        self.assertEqual(expected, orig_query._form_query())
        expected = (base_expected +
                    '\n  LEFT OUTER JOIN joined_table1 as joined_col1'
                    '\n    ON joined_col1.foo = self.foo'
                    ' WHERE foo = bar AND dog != cat',
                    {}, [self.model.joined_col1])
        self.assertEqual(expected, query._form_query())

        query = query.join('joined_col2')
        expected = (base_expected +
                    '\n  LEFT OUTER JOIN joined_table1 as joined_col1'
                    '\n    ON joined_col1.foo = self.foo'
                    '\n  LEFT OUTER JOIN joined_table2 as joined_col2'
                    '\n    ON joined_col2.foo = self.foo'
                    ' WHERE foo = bar AND dog != cat',
                    {}, [self.model.joined_col1,
                         self.model.joined_col2])
        self.assertEqual(expected, query._form_query())

    def _insert_update_common_form(self, base, method):
        base_expected = '%s %s' % (base, self.table)
        expected_args = dict()

        query = method(self.model, values=dict(foo='bar'))
        expected_args['foo'] = 'bar'
        expected = (base_expected + " SET `foo` = %(foo)s",
                expected_args)
        self.assertEqual(expected, query._form_query())

        orig_query = query
        query = query.values(cat='meow')
        query = query.raw_values(dog='"raw_wuff"')
        # Make sure original query is unmodified
        self.assertEqual(expected, orig_query._form_query())
        expected_args.update(cat='meow', dog='wuff')
        # The SQLQuery could have the values in any order because
        # its stored internally as a dict.
        be_with_set = base_expected + " SET "
        expected_parts = ['`foo` = %(foo)s', '`dog` = "raw_wuff"',
                          '`cat` = %(cat)s']
        result_str, result_args = query._form_query()
        self.assertTrue(result_str.startswith(be_with_set))
        the_rest_of_string = result_str[len(be_with_set):]
        result_parts = the_rest_of_string.split(', ')
        for part in result_parts:
            self.assertIn(part, expected_parts)
        for part in expected_parts:
            self.assertIn(part, result_parts)

    def test_insert_query_form(self):
        self._insert_update_common_form('INSERT INTO', sql.InsertQuery)

    def test_update_query_form(self):
        self._insert_update_common_form('UPDATE', sql.UpdateQuery)
