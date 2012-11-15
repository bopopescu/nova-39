# Copyright (c) 2012 Rackspace Hosting, Inc
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
Scheduler cell filters
"""

from nova import filters
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class BaseCellFilter(filters.BaseFilter):
    """Base class for cell filters."""
    pass


class CellFilterHandler(filters.BaseFilterHandler):
    def __init__(self):
        super(CellFilterHandler, self).__init__(BaseCellFilter)


def all_filters():
    """Return a list of filter classes found in this directory.

    This method is used as the default for available scheduler filters
    and should return a list of all filter classes available.
    """
    return CellFilterHandler().get_all_classes()
