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


class Mixin(object):
    @classmethod
    def update(cls, conn, context, uuid, mac, start_period, bw_in, bw_out,
               last_ctr_in, last_ctr_out, last_refreshed=None):

        if last_refreshed is None:
            last_refreshed = timeutils.utcnow()

        values = {'last_refreshed': last_refreshed,
                  'last_ctr_in': last_ctr_in,
                  'last_ctr_out': last_ctr_out,
                  'bw_in': bw_in,
                  'bw_out': bw_out,
                  'updated_at': timeutils.utcnow}

        query = sql.UpdateQuery(cls, values=values)
        query = query.where(
                '`start_period` = %(start_period)s AND '
                '`uuid` = %(uuid)s AND '
                '`mac` = %(mac)s',
                start_period=start_period, uuid=uuid, mac=mac)
        num_rows_affected = query.update(conn)
        if num_rows_affected > 0:
            return

        values.pop('updated_at')
        values['created_at'] = timeutils.utcnow()
        values['start_period'] = start_period
        values['uuid'] = uuid
        values['mac'] = mac
        # Start a new transaction.  UPDATE + INSERT can cause a deadlock
        # if mixed into the same transaction.
        query = sql.InsertQuery(cls, values=values)
        query = query.values(**values)
        query.insert(conn)
