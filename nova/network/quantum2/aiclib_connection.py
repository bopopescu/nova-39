# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Rackspace, Inc
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

import aiclib

from oslo.config import cfg

from nova import exception
from nova.openstack.common import log as logging


aiclib_opts = [
    cfg.StrOpt('controller_connection',
               default='127.0.0.1:443:admin:admin:10:10:5:Not_used',
               help=_('NVP Controller connection string')),
]


CONF = cfg.CONF
CONF.register_opts(aiclib_opts)
LOG = logging.getLogger(__name__)


class AICLibConnection(object):

    def __init__(self):
        (ip, port, user, passwd, req_timeout, http_timeout, retries,
         redirects) = CONF.controller_connection.split(":")

        port = int(port)
        scheme = 'https' if port == 443 else 'http'
        uri = '%s://%s:%s' % (scheme, ip, port)
        self.conn = aiclib.Connection(uri, username=user, password=passwd)

    def create_securityprofile_from_template(self, tenant_id,
                                             template_securityprofile_id,
                                             vm_id=None):
        kwargs = dict(securityprofile_id=template_securityprofile_id)
        template = self.get_securityprifile(**kwargs)

        # NOTE(jkoelker) Totes be careful here; NVP only supports 5 tags
        tags = [aiclib.h.tag('os_tid', tenant_id),
                aiclib.h.tag('rc_type', 'service_net')]

        display_name = 'RC SP for tenant %s' % tenant_id
        if vm_id is not None:
            display_name = 'RC SP for instance  %s' % vm_id
            tags.append(aiclib.h.tag('vmid', vm_id))

        ingress = [aiclib.h.copy_securityrule(sr)
                   for sr in template['logical_port_ingress_rules']]

        egress = [aiclib.h.copy_securityrule(sr)
                  for sr in template['logical_port_egress_rules']]

        securityprofile = self.conn.securityprofile()
        securityprofile.display_name(display_name)
        securityprofile.tags(tags)
        securityprofile.port_ingress_rules(ingress)
        securityprofile.port_egress_rules(egress)

        return securityprofile.create()

    def get_securityprofile(self, tenant_id=None,
                            securityprofile_id=None):
        errormsg = 'Either tenant_id or securityprofile_id is required'
        if tenant_id is None and securityprofile_id is None:
            raise TypeError(errormsg)

        if securityprofile_id is not None:
            sp = self.conn.securityprofile(securityprofile_id).read()
            return sp or None

        if tenant_id is None:
            raise TypeError(errormsg)

        qry = self.conn.securityprofile().query()
        qry = qry.tagscopes('os_tid').tags(tenant_id)
        qry = qry.tagscopes('rc_type').tags('service_net')
        res = qry.results()

        if res['result_count'] < 1:
            return None

        # NOTE(jkoelker) For now we just take the LAST policy returned
        #                (which should only ever one, but you never know)
        return res['results'][-1]

    def set_securityprofile(self, port_id, securityprofile_id):
        # NOTE(jkoelker) See this is why nesting resources is Bad(tm)
        qry = self.conn.lswitch_port('*').query()
        qry = qry.relations('LogicalSwitchConfig')
        res = qry.uuid(port_id).results()

        if res['result_count'] != 1:
            raise exception.PortNotFound(port_id=port_id)

        port_dict = res['results'][0]
        lswitch_dict = port_dict['_relations']['LogicalSwitchConfig']
        lswitch_id = lswitch_dict['uuid']

        # NOTE(jkoelker) Now that we know the lswitch uuid we can set
        #                what we're after on the port uuid we already
        #                knew.
        port = self.conn.lswitch_port(lswitch_id, port_id)
        port = port.security_profiles(securityprofile_id)
        return port.update()
