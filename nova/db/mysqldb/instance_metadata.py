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

from nova.db.mysqldb import sql
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils

LOG = logging.getLogger(__name__)

_WHERE_STR = '(`key` = %(key)s AND `instance_uuid`=%(instance_uuid)s)'


class Mixin(object):
    @classmethod
    def update(cls, conn, instance_uuid, key, value):
        now = timeutils.utcnow()
        query = sql.UpdateQuery(cls,
                values=dict(value=value, updated_at=now))
        query = query.where(_WHERE_STR, key=key, instance_uuid=instance_uuid)
        return query.update(conn)

    @classmethod
    def insert(cls, conn, instance_uuid, key, value):
        now = timeutils.utcnow()
        query = sql.InsertQuery(cls,
                values=dict(key=key, value=value, created_at=now,
                            deleted=0, instance_uuid=instance_uuid))
        return query.insert(conn)

    @classmethod
    def soft_delete(cls, conn, instance_uuid, key):
        return super(Mixin, cls).soft_delete(conn, _WHERE_STR,
                                             key=key,
                                             instance_uuid=instance_uuid)
