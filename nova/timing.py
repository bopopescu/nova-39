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

"""Profiling/timing methods."""

import functools

from eventlet import corolocal

from nova.openstack.common import log as logging
from nova.openstack.common import timeutils

LOG = logging.getLogger(__name__)

local = corolocal.local()


def is_query_timing_enabled():
    try:
        return local.query_timing
    except AttributeError:
        return False


def log_query_timing(statement, params, start, end):
    secs = timeutils.delta_seconds(start, end)
    name = local.db_method_name

    # strip newlines from statement to keep log on 1 line
    statement = statement.replace("\n", " ")

    LOG.debug(_("Executed query in %(secs)0.3f secs, method: %(name)s, "
                "statement: %(statement)s, params: %(params)s"), locals())


def timefunc(f):
    """Decorator that logs time to execute a wrapped callable."""
    @functools.wraps(f)
    def inner(*args, **kwargs):
        try:
            start = timeutils.utcnow()
            return f(*args, **kwargs)
        finally:
            end = timeutils.utcnow()
            secs = timeutils.delta_seconds(start, end)

            module = f.__module__
            name = f.__name__
            LOG.debug(_("Executed func %(module)s:%(name)s in %(secs)0.3f "
                        "secs."), locals())

    return inner


def timequeries(f):
    """Decorator that logs the time to execute any queries issued
    by the wrapped db method.
    """
    @functools.wraps(f)
    def inner(*args, **kwargs):
        try:
            local.query_timing = True  # enable query timing
            local.db_method_name = f.__name__

            return f(*args, **kwargs)  # execute db method

        finally:
            del(local.query_timing)
            del(local.db_method_name)

    return inner
