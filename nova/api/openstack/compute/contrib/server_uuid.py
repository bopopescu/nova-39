# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

"""The Server UUID extension."""

from nova.api.openstack.compute.views import address_uuid as views_addressuuid
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import utils as compute_utils
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

authorize = extensions.soft_extension_authorizer('compute', 'server_uuid')


class ServerUUIDController(wsgi.Controller):

    def get_networks_for_instance_from_nw_info(self, nw_info):
        """This function is very similar to nova.api.openstack.common.
        get_networks_for_instance_from_nw_info(). This version of it adds the
        'id' to the structure"""
        networks = {}
        for vif in nw_info:
            ips = vif.fixed_ips()
            floaters = vif.floating_ips()
            label = vif['network']['label']
            if label not in networks:
                networks[label] = {'ips': [], 'floating_ips': []}

            networks[label]['ips'].extend(ips)
            networks[label]['floating_ips'].extend(floaters)
            networks[label]['id'] = vif['network']['id']
        return networks

    def _show(self, req, resp_obj, id):
        """Modifies the resp_obj."""
        if not authorize(req.environ['nova.context']):
            return
        if 'server' in resp_obj.obj:
            resp_obj.attach(xml=NetworkUUIDTemplate())
            address_builder = views_addressuuid.AddressWithUUID()
            nw_info = compute_utils.get_nw_info_for_instance(
                    req.get_db_instance(id))
            networks = self.get_networks_for_instance_from_nw_info(nw_info)
            del resp_obj.obj["server"]["addresses"]
            resp_obj.obj["server"]["addresses"] = address_builder.index(
                    networks)["addresses"]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        return self._show(req, resp_obj, id)


class Server_uuid(extensions.ExtensionDescriptor):
    """Support to show the UUID of networks of instance."""

    name = "ServerUUID"
    alias = "os-server-uuid"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "server_uuid/api/v1.1")
    updated = "2012-11-14T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = ServerUUIDController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]


def make_network(elem):
    elem.set('id', 0)

    ip = xmlutil.SubTemplateElement(elem, 'ip', selector=1)
    ip.set('id')


network_nsmap = {None: xmlutil.XMLNS_V11}


class NetworkUUIDTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        sel = xmlutil.Selector(xmlutil.get_items, 0)
        root = xmlutil.TemplateElement('server')
        addr = xmlutil.SubTemplateElement(root, 'addresses', selector=sel)
        network = xmlutil.SubTemplateElement(addr, 'network',
            selector=xmlutil.get_items)
        make_network(network)
        return xmlutil.SlaveTemplate(root, 1, nsmap=network_nsmap)


class AddressesUUIDTemplate(xmlutil.TemplateBuilder):
    """Not currently used -JLH."""
    def construct(self):
        root = xmlutil.TemplateElement('addresses', selector='addresses')
        elem = xmlutil.SubTemplateElement(root, 'network',
                                          selector=xmlutil.get_items)
        make_network(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap=network_nsmap)
