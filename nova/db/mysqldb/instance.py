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

"""Mixin class for Instance."""
from oslo.config import cfg

from nova import context
from nova.db.mysqldb import sql
from nova import exception
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.import_opt('osapi_compute_unique_server_name_scope',
                'nova.db.sqlalchemy.api')


class Mixin(object):
    @classmethod
    def _build_instance_get(cls, ctxt, columns_to_join=None,
                            project_only=True):
        query = sql.SelectQuery(cls)
        if columns_to_join is not None:
            query = query.join(*columns_to_join)
        if ctxt.read_deleted == 'no':
            query = query.where('self.deleted = 0')
        elif ctxt.read_deleted == 'only':
            query = query.where('self.deleted > 0')
        if context.is_user_context(ctxt) and project_only:
            query = query.where('self.project_id = %(project_id)s',
                                project_id=ctxt.project_id)
        return query

    @classmethod
    def _instance_get_by_uuid(cls, conn, ctxt, instance_uuid):
        query = cls._build_instance_get(ctxt)
        query = query.where('self.uuid = %(instance_uuid)s',
                            instance_uuid=instance_uuid)
        instance = query.first(conn)
        if not instance:
            raise exception.InstanceNotFound(instance_id=instance_uuid)
        return instance

    @classmethod
    def get_by_uuid(cls, conn, ctxt, instance_uuid):
        return cls._instance_get_by_uuid(conn, ctxt, instance_uuid)

    @classmethod
    def get_all(cls, conn, ctxt, columns_to_join):
        query = cls._build_instance_get(ctxt,
                                        columns_to_join=columns_to_join)
        return query.fetchall(conn)
