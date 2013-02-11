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

"""MySQdb custom exception classes and helper methods."""

from nova.openstack.common.db import exception as db_exc


class DBRetryableError(db_exc.DBError):
    """Retryable IO Errors."""
    def __init__(self, inner_exception=None):
        super(DBRetryableError, self).__init__(inner_exception)


class DBIOError(DBRetryableError):
    """IOError received during query."""
    def __init__(self, inner_exception=None):
        super(DBIOError, self).__init__(inner_exception)


class DBCantConnect(DBRetryableError):
    """Couldn't connect to mysql server."""
    def __init__(self, inner_exception=None):
        super(DBCantConnect, self).__init__(inner_exception)


class DBWentAway(DBRetryableError):
    """mysql server stoped."""
    def __init__(self, inner_exception=None):
        super(DBWentAway, self).__init__(inner_exception)


RetryableErrors = (DBRetryableError, db_exc.DBDeadlock)
