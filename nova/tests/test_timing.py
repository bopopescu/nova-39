# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2013 OpenStack, LLC.
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

from nova import context
from nova import db
from nova import test
from nova import timing


class TimingTest(test.TestCase):
    """Simple smoke tests for timing module."""

    def setUp(self):
        super(TimingTest, self).setUp()
        self._called = False
        self.stubs.Set(timing, 'log_query_timing', self._fake_log)
        self.ctxt = context.get_admin_context()

    def testFunc(self):
        @timing.timefunc
        def foo(x):
            return x * 2

        self.assertEqual(4, foo(2))

    def testQueryLoggingDisabled(self):
        db.service_get_all(self.ctxt)
        self.assertFalse(self._called)

    def testQueryLoggingEnabled(self):
        # just wrap an existing db function to enable logging:
        @timing.timequeries
        def dbfunc(ctxt):
            return db.service_get_all(ctxt)

        dbfunc(self.ctxt)
        self.assertTrue(self._called)

    def _fake_log(self, *args):
        self._called = True
