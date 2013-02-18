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
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import utils

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
    def _metadata_replace(cls, conn, ctxt, model, instance_uuid,
                          orig_metadata, new_metadata):
        for keyvalue in orig_metadata:
            key = keyvalue['key']
            if key in new_metadata:
                value = new_metadata.pop(key)
                if keyvalue['value'] != value:
                    model.update(conn, instance_uuid, key, value)
            elif key not in new_metadata:
                model.soft_delete(conn, instance_uuid, key)
        for key, value in new_metadata.iteritems():
            model.insert(conn, instance_uuid, key, value)

    @classmethod
    def _validate_unique_hostname(cls, conn, ctxt, hostname):
        if not CONF.osapi_compute_unique_server_name_scope:
            return
        # Make sure read_deleted is 'no' and that we don't join any
        # columns as it's a waste.
        if CONF.osapi_compute_unique_server_name_scope == 'project':
            with utils.temporary_mutation(ctxt, read_deleted='no'):
                query = cls._build_instance_get(ctxt, columns_to_join=[])
        elif CONF.osapi_compute_unique_server_name_scope == 'global':
            with utils.temporary_mutation(ctxt, read_deleted='no'):
                query = cls._build_instance_get(ctxt, columns_to_join=[],
                        project_only=False)
        else:
            msg = _('Unknown osapi_compute_unique_server_name_scope value: '
                    '%s Flag must be empty, "global" or' ' "project"')
            LOG.warn(msg % CONF.osapi_compute_unique_server_name_scope)
            return
        lowername = hostname.lower()
        query = query.where('LOWER(self.hostname) = %(hostname)s',
                hostname=lowername)
        instance = query.first(conn)
        if instance:
            raise exception.InstanceExists(name=instance.hostname)

    @classmethod
    def _instance_update(cls, conn, ctxt, instance_uuid, values,
                         copy_old_instance=False):
        if not uuidutils.is_uuid_like(instance_uuid):
            raise exception.InvalidUUID(instance_uuid)

        instance = cls._instance_get_by_uuid(conn, ctxt,
                                                 instance_uuid)

        if "expected_task_state" in values:
            # it is not a db column so always pop out
            expected = values.pop("expected_task_state")
            if not isinstance(expected, (tuple, list, set)):
                expected = (expected,)
            actual_state = instance['task_state']
            if actual_state not in expected:
                raise exception.UnexpectedTaskStateError(
                        actual=actual_state, expected=expected)

        if ("hostname" in values and
                (instance['hostname'] is None or
                values["hostname"].lower() != instance['hostname'].lower())):
            cls._validate_unique_hostname(conn, ctxt, values['hostname'])

        if copy_old_instance:
            # just return the 1st instance, we don't mutate the
            # instance in this DB backend
            old_instance = instance
        else:
            old_instance = None

        metadata = values.pop('metadata', None)
        if metadata is not None:
            model = cls.get_model('InstanceMetadata')
            cls._metadata_replace(conn, ctxt, model,
                    instance_uuid, instance['metadata'], metadata)

        system_metadata = values.pop('system_metadata', None)
        if system_metadata is not None:
            model = cls.get_model('InstanceSystemMetadata')
            cls._metadata_replace(conn, ctxt, model,
                    instance_uuid, instance['system_metadata'],
                    system_metadata)

        # Pop this off... it's a hack for baremetal
        values.pop('extra_specs', None)

        # update the instance itself:
        if len(values) > 0:
            not_found = []
            for k, v in values.items():
                if k not in cls.columns:
                    not_found.append("%s=%s" % (k, v))
                    values.pop(k)
            if not_found:
                err_str = ' ,'.join(not_found)
                LOG.warning(_("Unknown columns found when trying to update "
                              "instance: %(err_str)s"),
                            dict(err_str=err_str), instance=instance)
            if 'updated_at' not in values:
                values['updated_at'] = timeutils.utcnow()
            upd_query = sql.UpdateQuery(cls, values=values)
            where_str = "`uuid` = %(instance_uuid)s"
            upd_query = upd_query.where(where_str,
                                        instance_uuid=instance_uuid)
            rows = upd_query.update(conn)
            if rows != 1:
                raise exception.InstanceNotFound(instance_id=instance_uuid)

        # get updated record
        new_instance = cls._instance_get_by_uuid(conn, ctxt, instance_uuid)
        return old_instance, new_instance

    @classmethod
    def get_by_uuid(cls, conn, ctxt, instance_uuid):
        return cls._instance_get_by_uuid(conn, ctxt, instance_uuid)

    @classmethod
    def get_all(cls, conn, ctxt, columns_to_join):
        query = cls._build_instance_get(ctxt,
                                        columns_to_join=columns_to_join)
        return query.fetchall(conn)

    @classmethod
    def destroy(cls, conn, ctxt, instance_uuid, constraint=None):
        if uuidutils.is_uuid_like(instance_uuid):
            instance_ref = cls._instance_get_by_uuid(conn, ctxt,
                    instance_uuid)
        else:
            raise exception.InvalidUUID(instance_uuid)
        if constraint:
            constraint.check(instance_ref)
        result = cls.soft_delete(conn, instance_uuid)
        if result == 0:
            return
        sg_assoc = cls.get_model('SecurityGroupInstanceAssociation')
        sg_assoc.soft_delete(conn, instance_uuid)
        ic = cls.get_model('InstanceInfoCache')
        ic.soft_delete(conn, instance_uuid)
        return instance_ref

    @classmethod
    def update(cls, conn, ctxt, instance_uuid, values):
        instance_ref = cls._instance_update(conn, ctxt, instance_uuid,
                                            values)[1]
        return instance_ref

    @classmethod
    def update_and_get_original(cls, conn, ctxt, instance_uuid, values):
        return cls._instance_update(conn, ctxt, instance_uuid, values,
                                    copy_old_instance=True)

    @classmethod
    def soft_delete(cls, conn, instance_uuid):
        return super(Mixin, cls).soft_delete(conn,
                '`uuid` = %(instance_uuid)s', instance_uuid=instance_uuid)
