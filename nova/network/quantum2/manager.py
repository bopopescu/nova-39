# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Openstack LLC.
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

import functools
import re
import sys
import uuid

import eventlet
import netaddr

from oslo.config import cfg

from nova import db
from nova import exception
from nova import manager
from nova.network import api as network_api
from nova.network import model
from nova.network.quantum2 import aiclib_connection
from nova.network.quantum2 import melange_connection
from nova.network.quantum2 import quantum_connection
from nova.openstack.common import excutils
from nova.openstack.common import importutils
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

quantum_opts = [
    cfg.BoolOpt('quantum_use_port_security',
                default=False,
                help='Whether or not to enable port security'),
    cfg.BoolOpt('quantum_port_security_include_link_local',
                default=False,
                help='Add the link local address to the port security list'),
]

CONF = cfg.CONF

try:
    CONF.register_opts(quantum_opts)
except cfg.DuplicateOptError:
    # NOTE(jkoelker) These options are verbatim in the legacy quantum
    #                manager. This is here to make sure they are
    #                registered in the tests.
    pass

quantum2_opts = [
    cfg.ListOpt('network_order',
                default=['public', 'private', '.*'],
                help='Ordered list of network labels, using regex syntax'),
    cfg.ListOpt('network_global_uuid_label_map',
                default=[],
                help='List of uuid,label,uuid,label... for default networks'),
    cfg.ListOpt('rackconnect_roles',
                default=[],
                help='List of keystone roles to trigger RackConnect logic'),
    cfg.ListOpt('rackconnect_public_gateway_roles',
                default=[],
                help=('RackConnect roles if present will not set gateway '
                      'on create_network')),
    cfg.StrOpt('rackconnect_servicenet',
               default='private',
               help='Servicenet network name'),
    cfg.StrOpt('rackconnect_servicenet_policy',
               default=None,
               help='Base Servicenet Security Policy'),
    cfg.BoolOpt('rackconnect_clone_servicenet_policy',
                default=False,
                help='Use the base Servicenet Security Policy as a template'),
    cfg.BoolOpt('rackconnect_clone_servicenet_policy_per_tenant',
                default=False,
                help=('When cloning use one policy per tenant instead of per '
                      'port')),
]

CONF.register_opts(quantum2_opts)
CONF.import_opt('network_driver', 'nova.network.driver')
CONF.import_opt('default_availability_zone', 'nova.availability_zones')
CONF.import_opt('quantum_default_tenant_id',
                'nova.network.quantum2.quantum_connection')


def uuidize(f):
    """
    Decorator to pass in instance_uuid as instance_id
    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'instance_id' in kwargs and 'instance_uuid' in kwargs:
            kwargs['instance_id'] = kwargs['instance_uuid']
            del kwargs['instance_uuid']
        return f(*args, **kwargs)
    return wrapper


def _log_kwargs(msg='', **kwargs):
    """
    Utility to return a message with kwarg variables appended
    """
    kwarg_msg = ' '.join([('%s: |%s|' % (str(key), kwargs[key]))
                          for key in kwargs])
    return "%s %s" % (msg, kwarg_msg)


class QuantumManager(manager.SchedulerDependentManager):
    """NetworkManager class that communicates with a Quantum service
       via a web services API to provision VM network connectivity.

       currently also communicates with melange
    """

    RPC_API_VERSION = '1.9'

    def __init__(self, *args, **kwargs):
        """Initialize two key libraries, the connection to a
           Quantum service, and the library for implementing IPAM.

        """
        self.driver = importutils.import_module(CONF.network_driver)

        self.q_conn = quantum_connection.QuantumClientConnection()
        self.m_conn = melange_connection.MelangeConnection()
        self.a_conn = aiclib_connection.AICLibConnection()

        # NOTE(tr3buchet): map for global uuids
        #                  if these should change, restart this service
        # self._nw_map will look like:
        # self._nw_map = {'0000000000-0000-0000-0000-000000000000': pub_uuid,
        #                 '1111111111-1111-1111-1111-111111111111': priv_uuid,
        #                 pub_uuid: '0000000000-0000-0000-0000-000000000000',
        #                 priv_uuid: '1111111111-1111-1111-1111-111111111111'}
        # there will be only one (each way) entry per label
        self._nw_map = {}
        self._rackconnect_servicenet = None

        if CONF.network_global_uuid_label_map:
            self._nw_map = self._get_nw_map()
            LOG.debug('the self._nw_map is |%s|' % self._nw_map)
        else:
            self._nw_map = {}

        self._rackconnect_roles = set(CONF.rackconnect_roles)
        rc_public_gateway_roles = CONF.rackconnect_public_gateway_roles
        self._rc_public_gateway_roles = set(rc_public_gateway_roles)

        super(QuantumManager, self).__init__(service_name='network',
                                             *args, **kwargs)

    def _get_nw_map(self):
        the_map = {}
        # get default networks
        q_default_tenant_id = CONF.quantum_default_tenant_id
        networks = self.m_conn.get_networks_for_tenant(q_default_tenant_id)
        networks = [self._normalize_network(network)
                    for network in networks]

        # make a key=label, value=uuid dictionary from the conf
        label_map = CONF.network_global_uuid_label_map
        flag_dict = dict((i[1], i[0]) for i in zip(*[iter(label_map)] * 2))

        # build a birectional map of global uuid to specific network uuid
        for nw in networks:
            if nw['label'] in flag_dict:
                global_uuid = str(uuid.UUID(flag_dict[nw['label']]))
                if global_uuid not in the_map:
                    the_map[global_uuid] = nw['id']
                    the_map[nw['id']] = global_uuid

            if (nw['label'] == CONF.rackconnect_servicenet and
                    self._rackconnect_servicenet is None):
                self._rackconnect_servicenet = nw['id']

        return the_map

    def init_host(self):
        pass

    #
    # NOTE(jkoelker) Here be the stub points and helper functions, matey
    #
    def _clean_up_melange(self, tenant_id, instance_id,
                          raise_exception=True):
        try:
            self.m_conn.allocate_for_instance_networks(tenant_id,
                                                       instance_id,
                                                       [])
        except Exception, e:
            LOG.exception(_("Error cleaning up melange: %s"), e)
            if raise_exception:
                exc = exception.VirtualInterfaceCleanupException
                raise exc(reason=str(e))

    def _deallocate_port(self, tenant_id, network_id, interface_id,
                         port_id=None):
        if port_id is None:
            port_id = self.q_conn.get_port_by_attachment(tenant_id,
                                                         network_id,
                                                         interface_id)
        if port_id:
            self.q_conn.detach_and_delete_port(tenant_id, network_id, port_id)
        else:
            LOG.error(_("Unable to find port with attachment: %s") %
                      interface_id)

    def _generate_address_pairs(self, vif, ips):
        return [{'mac_address': vif['mac_address'],
                 'ip_address': ip} for ip in ips]

    def _verify_vif_network_info(self, vif, network_tenant_ids, network_ids,
                                 exc_class=None):

        if exc_class is None:
            exc_class = exception.VirtualInterfaceIntegrityException

        if not network_tenant_ids:
            msg = _("No network tenants for VIF %s") % vif['id']
            raise exc_class(reason=msg)
        if not network_ids:
            msg = _("No networks for VIF %s") % vif['id']
            raise exc_class(reason=msg)

        if len(network_tenant_ids) > 1:
            msg = _("Too many network tenants for VIF %s") % vif['id']
            raise exc_class(reason=msg)

        if len(network_ids) > 1:
            msg = _("Too many networks for VIF %s") % vif['id']
            raise exc_class(reason=msg)

    def _get_ips_and_ids_from_vif(self, vif):
        ips = []
        network_tenant_ids = set()
        network_ids = set()
        network_names = set()

        for ip in vif['ip_addresses']:
            ips.append(ip['address'])
            network_tenant_ids.add(ip['ip_block']['tenant_id'])
            network_ids.add(ip['ip_block']['network_id'])
            if 'network_name' in ip['ip_block']:
                network_names.add(ip['ip_block']['network_name'])

        return (ips, network_tenant_ids, network_ids, network_names)

    def _get_network(self, network_id, tenant_id):
        networks = self.m_conn.get_networks_for_tenant(tenant_id)
        networks = [net for net in networks
                    if net['network_id'] == network_id]

        if not networks:
            raise exception.NetworkNotFound(network_id=network_id)
        elif len(networks) > 1:
            raise exception.NetworkFoundMultipleTimes(network_id=network_id)

        return networks[0]

    def _is_haz_rackconnect(self, context):
        return set(context.roles) & self._rackconnect_roles

    def _normalize_network(self, network):
        # NOTE(jkoelker) We don't want to expose out a bunch of melange
        #                details, so we prune down here
        net = {'id': network['network_id'],
               'cidr': network['cidr']}

        net['label'] = 'UKNOWN'

        if 'network_name' in network and network['network_name']:
            net['label'] = network['network_name']
        else:
            try:
                label = self.q_conn.get_network_name(network['tenant_id'],
                                                     network['network_id'])
                net['label'] = label
                self._update_melange_with_name(network['tenant_id'],
                                               network['network_id'],
                                               label)
            except Exception:
                msg = _('Error get name for network_id %s')
                LOG.exception(msg % network['network_id'])

        return net

    def _order_nw_info_by_label(self, nw_info):
        if nw_info is None:
            return nw_info

        def get_vif_label_key(vif):
            for i, pattern in enumerate(CONF.network_order):
                if re.match(pattern, vif['network']['label']):
                    return i
            else:
                return len(CONF.network_order)
        nw_info.sort(key=get_vif_label_key)
        return nw_info

    def _update_melange_with_name(self, tenant_id, network_id, name):
        try:
            self.m_conn.set_name_for_ip_blocks(tenant_id, name, network_id)
        except Exception:
            msg = _('Failed to set name on network_id %s')
            LOG.exception(msg % network_id)

    def _map_network(self, network_id, label):
        mapped_id = self._nw_map.get(network_id) or network_id
        kwargs = {}
        # NOTE(jhammond) If network_id gets mapped, store original in meta
        if mapped_id != network_id:
            kwargs["original_id"] = network_id
        return model.Network(id=mapped_id, label=label, **kwargs)

    def _vif_from_network(self, m_vif, network_id, label):
        network = self._map_network(network_id, label)

        ip_blocks = {}
        for ip_address in m_vif['ip_addresses']:
            address = ip_address['address']
            block = ip_address['ip_block']
            if block['cidr'] not in ip_blocks:
                ip_blocks[block['cidr']] = (block, [])
            ip_blocks[block['cidr']][1].append(address)

        for cidr, block_thing in ip_blocks.iteritems():
            ip_block, ip_addresses = block_thing

            gateway = None
            if ip_block.get('gateway'):
                gateway = model.IP(address=ip_block['gateway'],
                                   type='gateway')

            subnet = model.Subnet(cidr=ip_block['cidr'],
                                  gateway=gateway)

            for key in ('dns1', 'dns2'):
                if ip_block.get(key):
                    subnet.add_dns(model.IP(address=ip_block[key],
                                            type='dns'))

            for route in ip_block['ip_routes']:
                route_cidr = netaddr.IPNetwork('%s/%s' %
                                               (route['destination'],
                                                route['netmask'])).cidr
                gateway = model.IP(address=route['gateway'],
                                   type='gateway')
                subnet.add_route(model.Route(cidr=str(route_cidr),
                                             gateway=gateway))

            for ip_address in ip_addresses:
                subnet.add_ip(model.FixedIP(address=ip_address))
            network.add_subnet(subnet)
        return model.VIF(id=m_vif['id'], address=m_vif['mac_address'],
                         network=network)

    def _vifs_to_model(self, melange_vifs, skip_broken_vifs=False):
        nw_info = model.NetworkInfo()
        # NOTE(jkoelker) This allows us to call quantum in the loop
        #                but only once per tenant_id. Keys are tenant_id
        #                value is list of networks
        for m_vif in melange_vifs:
            (ips,
             network_tenant_ids,
             network_ids,
             network_names) = self._get_ips_and_ids_from_vif(m_vif)

            try:
                self._verify_vif_network_info(m_vif, network_tenant_ids,
                                              network_ids)
            except exception.VirtualInterfaceIntegrityException:
                if skip_broken_vifs:
                    LOG.warn(_('Skipping missing/broken vif when building '
                               'model: %(m_vif)s'), locals())
                    continue
                raise

            network_tenant_id = network_tenant_ids.pop()
            network_id = network_ids.pop()
            network_name = network_names.pop()

            if not network_name:
                args = (network_tenant_id, network_id)
                try:
                    network_name = self.q_conn.get_network_name(*args)
                except Exception:
                    msg = _('Error get name for network_id %s')
                    LOG.exception(msg % network_id)
                self._update_melange_with_name(network_tenant_id,
                                               network_id,
                                               network_name)

            vif = self._vif_from_network(m_vif, network_id, network_name)

            nw_info.append(vif)

        return nw_info

    def _clean_vif_list(self, vifs):
        vif_list = []

        def _net_mapped(net_id):
            return self._nw_map.get(net_id) or net_id

        for vif in vifs:
            addrs = [{"network_id": _net_mapped(a["ip_block"]["network_id"]),
                      "network_label": a["ip_block"]["network_name"],
                      "address": a["address"]} for a in vif["ip_addresses"]]
            v = dict(id=vif["id"],
                     address=vif["mac_address"],
                     ip_addresses=addrs)
            vif_list.append(v)
        return vif_list

    @uuidize
    def get_vifs_by_instance(self, context, instance_id):
        vifs = self.m_conn.get_allocated_networks(instance_id)
        return self._clean_vif_list(vifs)

    @uuidize
    def deallocate_interface_for_instance(self, context, instance_id,
                                          interface_id, **kwargs):
        vif = self.m_conn.get_interface_for_device(instance_id, interface_id)
        port_id = vif.get('vif_id_on_device')
        if not port_id:
            port_id = None

        for ip in vif["ip_addresses"]:
            tenant_id = ip["ip_block"]["tenant_id"]
            network_id = ip["ip_block"]["network_id"]
            self._deallocate_port(tenant_id, network_id, interface_id,
                                  port_id=port_id)
        self.m_conn.deallocate_interface_for_instance(context.project_id,
                                                      instance_id,
                                                      interface_id)
        return vif

    @uuidize
    def allocate_interface_for_instance(self, context, instance_id,
                                        rxtx_factor, project_id, network_id,
                                        **kwargs):
        rackconnect = self._is_haz_rackconnect(context)
        networks = self._discover_networks(tenant_id=project_id,
                                           requested_networks=[(network_id,)])
        attached_vifs = self.m_conn.get_allocated_networks(instance_id)
        net_ids = [n["id"] for n in networks]
        for v in attached_vifs:
            for address in v["ip_addresses"]:
                LOG.critical(address)
                if address["ip_block"]["network_id"] in net_ids:
                    raise exception.AlreadyAttachedToNetwork()

        vif = self.m_conn.allocate_interface_for_instance(project_id,
                                                          instance_id,
                                                          networks[0])
        self._establish_interface_and_port(context, vif, instance_id,
                                           project_id, rxtx_factor,
                                           rackconnect=rackconnect)
        return self._clean_vif_list([vif])

    def _discover_networks(self, tenant_id, requested_networks=None):
        q_default_tenant_id = CONF.quantum_default_tenant_id
        networks = self.m_conn.get_networks_for_tenant(q_default_tenant_id)
        if requested_networks is not None:
            requested_networks = [self._nw_map.get(rn[0]) or rn[0]
                                  for rn in requested_networks]
            networks.extend(self.m_conn.get_networks_for_tenant(tenant_id))
            nw_dict = dict((n['network_id'], n) for n in networks)
            networks = []
            for rn in requested_networks:
                try:
                    networks.append(nw_dict[rn])
                except KeyError:
                    LOG.exception(_('Bad network_id requested in allocate'))
                    raise exception.NetworkNotFound(rn)

        # Make sure we only request one allocation per network
        networks = set([(net['network_id'],
                         net['tenant_id']) for net in networks])

        networks = [{'id': net[0],
                     'tenant_id': net[1]} for net in networks]
        return networks

    def _establish_interface_and_port(self, contex, vif, instance_id,
                                      tenant_id, rxtx_factor,
                                      rackconnect=False):
        nova_id = CONF.default_availability_zone
        q_default_tenant_id = CONF.quantum_default_tenant_id
        pairs = []
        exc_class = exception.VirtualInterfaceCreateException
        try:
            (ips,
             network_tenant_ids,
             network_ids,
             network_names) = self._get_ips_and_ids_from_vif(vif)
            self._verify_vif_network_info(vif, network_tenant_ids,
                                          network_ids, exc_class=exc_class)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Error extracting vif information'))
                self._clean_up_melange(tenant_id, instance_id)

        network_tenant_id = network_tenant_ids.pop()
        network_id = network_ids.pop()

        if (CONF.quantum_use_port_security and
                q_default_tenant_id == network_tenant_id):

            if CONF.quantum_port_security_include_link_local:
                mac = netaddr.EUI(vif['mac_address'])
                ips.append(str(mac.ipv6_link_local()))

            pairs = self._generate_address_pairs(vif, ips)

        kwargs = dict(vm_id=instance_id, rxtx_factor=rxtx_factor,
                      nova_id=nova_id, allowed_address_pairs=pairs)
        port_id = self.q_conn.create_and_attach_port(network_tenant_id,
                                                     network_id,
                                                     vif['id'],
                                                     **kwargs)

        # NOTE(jkoelker) Attempt to let melange store the port_id
        try:
            self.m_conn.set_interface_vif_id_on_device(vif['id'], port_id)
        except Exception:
            msg = _('Could not set vif_id_on_device for vif: %(id)s')
            LOG.exception(msg % vif)

        if rackconnect and network_id == self._rackconnect_servicenet:
            self._can_haz_rc_policy_for_port(port_id, tenant_id, instance_id)

    def _can_haz_rc_policy_for_port(self, port_id, tenant_id, instance_id):
        template_id = CONF.rackconnect_servicenet_policy

        if not template_id:
            msg = _('Racconnect Service Policy Base not specifed. '
                    'Skipping applying policies to port %(port_id)s')
            LOG.debug(msg % dict(port_id=port_id))
            return

        msg = _('Adding %(port_id)s to securityprofile '
                '%(securityprofile_id)s.')

        # NOTE(jkoelker) Cluster wide shared policy
        if not CONF.rackconnect_clone_servicenet_policy:
            LOG.debug(msg % dict(port_id=port_id,
                                 securityprofile_id=template_id))
            self.a_conn.set_securityprofile(port_id, template_id)
            return

        # NOTE(jkoelker) Per port policy
        if not CONF.rackconnect_clone_servicenet_policy_per_tenant:
            args = (tenant_id, template_id, instance_id)
            sp = self.a_conn.create_securityprofile_from_template(*args)

        # NOTE(jkoelker) Per tenant policy
        else:
            sp = self.a_conn.get_securityprofile(tenant_id=tenant_id)

            if sp is None:
                args = (tenant_id, template_id)
                sp = self.a_conn.create_securityprofile_from_template(*args)

        LOG.debug(msg % dict(port_id=port_id,
                             securityprofile_id=sp['uuid']))
        self.a_conn.set_securityprofile(port_id, sp['uuid'])

    #
    # NOTE(jkoelker) Ahoy! Here be the API implementations, ya land louver
    #
    # NOTE(jkoelker) Accept **kwargs, for the bass ackwards compat. Dont use
    #                them.
    @uuidize
    def allocate_for_instance(self, context, instance_id, rxtx_factor,
                              project_id, host, requested_networks=None,
                              **kwargs):
        LOG.debug(_('network allocations for instance %s'), instance_id)
        tenant_id = project_id

        networks = self._discover_networks(tenant_id, requested_networks)
        rackconnect = self._is_haz_rackconnect(context)

        vifs = []
        try:
            vifs = self.m_conn.allocate_for_instance_networks(tenant_id,
                                                              instance_id,
                                                              networks)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Melange allocation failed'))
                self._clean_up_melange(tenant_id, instance_id)

        pool = eventlet.GreenPool()

        def _establish(vif):
            try:
                self._establish_interface_and_port(context, vif, instance_id,
                                                   tenant_id, rxtx_factor,
                                                   rackconnect=rackconnect)
            except Exception:
                exc_info = sys.exc_info()
                return exc_info

        for exc in pool.imap(_establish, vifs):
            # there will only be a result if it was an exception
            if exc is not None:
                raise exc[0], exc[1], exc[2]

        nw_info = self._vifs_to_model(vifs)
        return self._order_nw_info_by_label(nw_info)

    def _update_port_allowed_address_pairs(self, tenant_id, instance_id,
                                           interface_id, network_id):
        """gets mac address and ips from melange for an interface,
           gets port from quantum for that interface,
           then updates the allowed address pairs in quantum to match what
           is in melange

           Takes no action if unnecessary by CONF or if vif cannot be found
        """
        if (CONF.quantum_use_port_security and
                CONF.quantum_default_tenant_id == tenant_id):

            # get the whole vif record
            vif = self.m_conn.get_interface_for_device(instance_id,
                                                       interface_id)
            # make sure we got a result
            if not vif:
                LOG.exception(_('vif could not be found to generate allowed'
                                'address pairs'))
                return

            # get the list of ips from the vif (should include/exclude a
            # recently added/removed fixed ip)
            # TODO(tr3buchet) make sure this isn't a race condition
            ips = [ip['address'] for ip in vif.get('ip_addresses', [])]

            # append link local to ips if flags are set
            if CONF.quantum_port_security_include_link_local:
                mac = netaddr.EUI(vif['mac_address'])
                ips.append(str(mac.ipv6_link_local()))

            # get a list of [{'mac_address': 'xx:xx..',
            #                 'ip': 'xxx.xxx.xxx.xxx'}, ...]
            # for each ip in the ip list
            pairs = self._generate_address_pairs(vif, ips)

            # get the port id from quantum
            port_id = self.q_conn.get_port_by_attachment(tenant_id,
                                                         network_id,
                                                         interface_id)
            # update the port
            self.q_conn.update_allowed_address_pairs_on_port(tenant_id,
                                                             network_id,
                                                             port_id,
                                                             pairs)

    def add_fixed_ip_to_instance(self, context, instance_id, host, network_id,
                                 **kwargs):
        if not context.is_admin:
            LOG.error('Must be admin context to add fixed ip')
            return
        msg = _('adding fixed_ip to instance |%(instance_id)s| on '
                'network |%(network_id)s|')
        LOG.debug(msg % {'instance_id': instance_id, 'network_id': network_id})

        # map the network id, and use default tenant if map took
        requested_network_id = network_id
        network_id = self._nw_map.get(network_id) or network_id
        if requested_network_id != network_id:
            # map took place meaning they requested a rax network
            tenant_id = CONF.quantum_default_tenant_id
        else:
            # set to None, we'll get it from interface later
            tenant_id = None

        # get the interfaces for this instance and find one attached to nw_id
        interfaces = self.m_conn.get_allocated_networks(instance_id)
        interface_id = None
        instance_tenant_id = None
        for interface in interfaces:
            for ip_addr in interface.get('ip_addresses', []):
                ip_block = ip_addr.get('ip_block', {})
                block_network_id = ip_block.get('network_id')
                if block_network_id == network_id:
                    # found it!
                    interface_id = interface.get('id')
                    instance_tenant_id = interface.get('tenant_id')
                    break
            if interface_id is not None:
                break
        else:
            LOG.error(_('Interface not found, IP allocation failed'))
            return

        # if not using the quantum default tenant because we mapped the network
        # id, use the instance's interface's tenant_id
        # such a hack....
        if tenant_id is None:
            tenant_id = instance_tenant_id

        # allocate the ip in melange
        self.m_conn.allocate_ip_for_instance(tenant_id, instance_id,
                                             interface_id, network_id, 4)

        # update port address pairs (does nothing if unnecessary)
        self._update_port_allowed_address_pairs(tenant_id, instance_id,
                                                interface_id, network_id)

    def remove_fixed_ip_from_instance(self, context, instance_id,
                                      host, address, **kwargs):
        if not context.is_admin:
            LOG.error('Must be admin context to remove fixed ip')
            return
        msg = _('removing fixed_ip |%(address)s| from '
                'instance |%(instance_id)s|')
        LOG.debug(msg % {'address': address, 'instance_id': instance_id})

        # get the interface on the instance that has address
        interfaces = self.m_conn.get_allocated_networks(instance_id)
        interface_id = None
        for interface in interfaces:
            for ip_addr in interface.get('ip_addresses', []):
                if ip_addr.get('address') == address:
                    # found it!
                    interface_with_ip = interface
                    interface_id = interface.get('id')
                    ip_block = ip_addr.get('ip_block', {})
                    network_id = ip_block.get('network_id')
                    network_tenant_id = ip_block.get('tenant_id')
                    break
            if interface_id is not None:
                break
        else:
            LOG.error(_('IP could not be found on any interface. '
                        'IP Deallocation failed.'))
            return

        # make sure this isn't the last address on this interface
        v4_addresses = [ip for ip in interface_with_ip['ip_addresses']
                        if ip.get('version') == 4]
        if len(v4_addresses) <= 1:
            LOG.error(_('Cannot remove last v4 address from interface'))
            return

        # deallocate the ip
        self.m_conn.deallocate_ip_for_instance(instance_id, interface_id,
                                               address)

        # update port address pairs (does nothing if unnecessary)
        self._update_port_allowed_address_pairs(network_tenant_id, instance_id,
                                                interface_id, network_id)

    # NOTE(jkoelker) Only a single network is supported. Function is
    #                pluralized for da backwards compatability.
    # NOTE(jkoelker) Accept **kwargs, for the bass ackwards compat. Dont use
    #                them.
    def create_networks(self, context, label, cidr, gateway=None, **kwargs):
        # NOTE(jkoelker) For devstack compat we'll assume the defaul
        #                tenant if it is None in the context
        # NOTE(jkoelker) For the time being we only support 1 subnet
        #                you choose ipv6 or ipv4 but not both
        tenant_id = context.project_id or CONF.quantum_default_tenant_id
        nova_id = CONF.default_availability_zone
        policy_length = 1
        rackconnect = self._is_haz_rackconnect(context)

        if rackconnect:
            # NOTE(jkoelker) The format of cidr was checked in the
            #                os_networks_v2 extension, so we know we
            #                have a valid cidr.
            net = netaddr.IPNetwork(cidr)

            # NOTE(jkoelker) This should really live in the extension
            #                so we can return a more informative error
            #                back to the user, but that will polute the
            #                config on the api nodes as well. Since this
            #                code is going away (hopefully, eventually,
            #                hey gotta belib in something) do the quick
            #                and dirty here instead, and document that
            #                RackConect customers require at least a /29
            if net.size < 8:
                req = 'A /29 or greater is required for RackConnect.'
                raise exception.NetworkNotCreated(req=req)

            policy_length = 4

            # NOTE(jkoelker) Check and set the default gateway
            if not (rackconnect & self._rc_public_gateway_roles):
                gateway = str(net[1])

        # NOTE(jhammond) cidr has been checked in os_networksv2 for kosher
        network_id = self.q_conn.create_network(tenant_id, label,
                                                nova_id=nova_id)

        extra = {'network_id': network_id, 'tenant_id': tenant_id,
                 'label': label, 'nova_id': nova_id}
        msg = _('Network created in quantum')
        LOG.debug(_log_kwargs(msg, **extra), extra=extra)

        policy = self.m_conn.create_ip_policy(tenant_id, network_id,
                                              ('Policy for network %s' %
                                               network_id))
        self.m_conn.create_unusable_range_in_policy(tenant_id,
                                                    policy['id'],
                                                    length=policy_length)
        ip_block = self.m_conn.create_ip_block(tenant_id,
                                               str(cidr),
                                               network_id,
                                               label,
                                               policy_id=policy['id'],
                                               gateway=gateway)
        return [self._normalize_network(ip_block)]

    # NOTE(jkoelker) Accept **kwargs, for the bass ackwards compat. Dont use
    #                them.
    @uuidize
    def deallocate_for_instance(self, context, instance_id, project_id,
                                **kwargs):
        tenant_id = project_id
        vifs = self.m_conn.get_allocated_networks(instance_id)
        self.m_conn.allocate_for_instance_networks(tenant_id, instance_id,
                                                   [])

        exc_class = exception.VirtualInterfaceCleanupException

        for vif in vifs:
            (_ips,
             network_tenant_ids,
             network_ids,
             network_names) = self._get_ips_and_ids_from_vif(vif)

            try:
                self._verify_vif_network_info(vif, network_tenant_ids,
                                              network_ids,
                                              exc_class=exc_class)
            except Exception:
                # NOTE(comstud): Skip broken vifs.
                LOG.warn(_('Skipping deallocate for missing/broken vif: '
                           '%(vif)s'), locals())
                continue

            network_tenant_id = network_tenant_ids.pop()
            network_id = network_ids.pop()

            port_id = vif.get('vif_id_on_device')
            if not port_id:
                port_id = None

            try:
                self._deallocate_port(network_tenant_id, network_id,
                                      vif['id'], port_id=port_id)
            except Exception:
                # except anything so the rest of deallocate can succeed
                extra = {'instance_id': instance_id,
                         'network_tenant_id': network_tenant_id,
                         'network_id': network_id,
                         'vif_id': vif['id']}
                msg = _('Port deallocation failed for instance.')
                LOG.critical(_log_kwargs(msg, **extra), extra=extra)

    # NOTE(jkoelker) Accept **kwargs, for the bass ackwards compat. Dont use
    #                them.
    def delete_network(self, context, uuid, **kwargs):
        tenant_id = context.project_id
        # NOTE(jkoelker) The param uuid is the network_id needs to be fixed
        #                in the api.
        network_id = uuid
        network = self._get_network(network_id, tenant_id)

        # Refuse to delete a network that has attached ports
        try:
            ports = self.m_conn.get_interfaces(tenant_id=tenant_id,
                                               network_id=network_id)
            if len(ports) > 0:
                raise exception.NetworkBusy(network=network_id)
            self.q_conn.delete_network(tenant_id, network_id)
            LOG.debug(_('Deleting network %(network_id)s for tenant '
                        '%(tenant_id)s') % {'network_id': network_id,
                                            'tenant_id': tenant_id})
        except quantum_connection.quantum_client.QuantumNotFoundException:
            LOG.exception(_('Deleting quantum network %s failed') %
                          network_id)

        try:
            self.m_conn.delete_ip_block(tenant_id, network['id'])
        except Exception:
            LOG.exception(_("Melange block deletion failed"))
            raise

    def get_all_networks(self, context):
        tenant_id = context.project_id
        networks = self.m_conn.get_networks_for_tenant(tenant_id)
        networks = [self._normalize_network(network) for network in networks]

        if CONF.network_global_uuid_label_map:
            for nw in networks:
                nw['id'] = self._nw_map.get(nw['id']) or nw['id']

        return networks

    # NOTE(jkoelker) Accept **kwargs, for the bass ackwards compat. Dont use
    #                them.
    @uuidize
    def get_instance_nw_info(self, context, instance_id, project_id,
                             **kwargs):

        try:
            vifs = self.m_conn.get_allocated_networks(instance_id)
            nw_info = self._vifs_to_model(vifs, skip_broken_vifs=True)
            nw_info = self._order_nw_info_by_label(nw_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                msg = _('Failed to get nw_info!!! for instance '
                        '|%s|') % instance_id
                LOG.exception(msg)
        return nw_info

    def get_network(self, context, network_uuid):
        # NOTE(jkoelker) The param uuid is the network_id needs to be fixed
        #                in the api.
        network_id = network_uuid
        tenant_id = context.project_id

        network = self._get_network(network_id, tenant_id)
        return self._normalize_network(network)

    # NOTE(jkoelker) Stub function. setup_networks_on_host is for legacy
    #                dhcp and multi_host setups
    def setup_networks_on_host(self, *args, **kwargs):
        pass

    @network_api.wrap_check_policy
    def get_instance_uuids_by_ip_filter(self, context, filters):
        # This is not returning the instance IDs like the method name would
        # make you think, its matching the return format of the method it's
        # overriding. Yahrrr
        address = filters.get('ip', None)
        instance_ids = self.m_conn.get_instance_ids_by_ip_address(context,
                                                                  address)
        instances = [db.instance_get_by_uuid(context,
                                             id) for id in instance_ids]
        return [{'instance_uuid': instance.uuid} for instance in instances]

    # NOTE(jkoelker) Stub function. validate_networks is only called
    #                in the compute api prior to creating the instance
    #                passing here since it would perform the same checks
    #                as in allocate_for_instance. In the effort of not
    #                making extraneous calls, we're just letting the
    #                allocate_for_instance fail there.
    def validate_networks(self, context, networks):
        pass

    def migrate_instance_start(self, context, instance_uuid, rxtx_factor,
                               project_id, source, dest, floating_addresses):
        pass

    def migrate_instance_finish(self, context, instance_uuid, rxtx_factor,
                                project_id, source, dest, floating_addresses):
        # Update the rxtx_factor for the port
        vifs = self.m_conn.get_allocated_networks(instance_uuid)

        exc_class = exception.VirtualInterfaceCleanupException

        for vif in vifs:
            (_ips,
             network_tenant_ids,
             network_ids,
             _network_names) = self._get_ips_and_ids_from_vif(vif)

            try:
                self._verify_vif_network_info(vif, network_tenant_ids,
                                              network_ids,
                                              exc_class=exc_class)
            except Exception:
                LOG.warn(_('Skipping rxtx_factor update for missing/'
                           'broken vif: %(vif)s'), locals())
                continue

            network_tenant_id = network_tenant_ids.pop()
            network_id = network_ids.pop()

            try:
                self._update_rxtx_factor(network_tenant_id, network_id,
                                         vif['id'], rxtx_factor)
            except Exception:
                # Log the exception but otherwise ignore it, so the
                # rest of the interfaces can be updated
                extra = {'instance_id': instance_uuid,
                         'network_tenant_id': network_tenant_id,
                         'network_id': network_id,
                         'vif_id': vif['id']}
                msg = _('Port rxtx_factor adjustment failed for instance.')
                LOG.exception(_log_kwargs(msg, **extra), extra=extra)

    def _update_rxtx_factor(self, tenant_id, network_id, interface_id,
                            rxtx_factor):
        # FIXME(comstud): The below code causes port to disappear and not
        # come back
        return
        port_id = self.q_conn.get_port_by_attachment(tenant_id,
                                                     network_id,
                                                     interface_id)
        if port_id:
            self.q_conn.update_rxtx_factor_on_port(tenant_id, network_id,
                                                   port_id, rxtx_factor)
        else:
            LOG.error(_("Unable to find port with attachment: %s") %
                      interface_id)
