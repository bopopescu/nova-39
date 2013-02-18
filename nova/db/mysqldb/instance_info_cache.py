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
from nova.openstack.common import timeutils

_WHERE_STR = '`instance_uuid`=%(instance_uuid)s'


class Mixin(object):
    @classmethod
    def get(cls, conn, context, instance_uuid):
        query = sql.SelectQuery(cls)
        query = query.where(_WHERE_STR, instance_uuid=instance_uuid)
        return query.first(conn)

    @classmethod
    def update(cls, conn, context, instance_uuid, values):
        info_cache = cls.get(conn, context, instance_uuid)
        if info_cache and not info_cache['deleted']:
            if 'updated_at' not in values:
                values['updated_at'] = timeutils.utcnow()
            query = sql.UpdateQuery(cls, values=values)
            query = query.where(_WHERE_STR, instance_uuid=instance_uuid)
            rows = query.update(conn)
            if rows:
                return cls.get(conn, context, instance_uuid)
            else:
                return info_cache
        return cls.create(conn, context, instance_uuid, values)

    @classmethod
    def create(cls, conn, context, instance_uuid, values):
        values['instance_uuid'] = instance_uuid
        if 'created_at' not in values:
            values['created_at'] = timeutils.utcnow()
        query = sql.InsertQuery(cls, values=values)
        query.insert(conn)
        return cls.get(conn, context, instance_uuid)

    @classmethod
    def soft_delete(cls, conn, instance_uuid):
        return super(Mixin, cls).soft_delete(conn,
                _WHERE_STR, instance_uuid=instance_uuid)
