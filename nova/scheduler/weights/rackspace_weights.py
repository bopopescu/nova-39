# Copyright (c) 2011-2012 Rackspace Hosting
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
Rackspace soft rules
"""
import random

from oslo.config import cfg

from nova.scheduler import weights


rackspace_weight_opts = [
    cfg.FloatOpt('rax_instances_weight_mult',
            default=5.0,
            help='How much weight to give the num_instances cost function'),
    cfg.FloatOpt('rax_instances_for_project_weight_mult',
            default=20.0,
            help='How much weight to give the project_id cost function'),
    cfg.FloatOpt('rax_instances_for_os_type_weight_mult',
            default=200000.0,
            help='How much weight to give the os_type cost function'),
    cfg.IntOpt('rax_randomize_top_hosts',
            default=5,
            help='Randomize the top "x" number of hosts'),
]

CONF = cfg.CONF
CONF.register_opts(rackspace_weight_opts)


class RAXInstancesHostWeigher(weights.BaseHostWeigher):
    def _weight_multiplier(self):
        return CONF.rax_instances_weight_mult

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want hosts with more instances to be
        preferred.
        """
        return host_state.num_instances


class RAXProjectHostWeigher(weights.BaseHostWeigher):
    def _weight_multiplier(self):
        return CONF.rax_instances_for_project_weight_mult

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want hosts with less instances for
        this project ID to be preferred.
        """
        try:
            project_id = weight_properties['project_id']
            num_instances = host_state.num_instances_by_project.get(
                    project_id, 0)
        except (AttributeError, KeyError):
            num_instances = 0
        return -num_instances


class RAXOSTypeHostWeigher(weights.BaseHostWeigher):
    def _weight_multiplier(self):
        return CONF.rax_instances_for_os_type_weight_mult

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want hosts with less instances for
        this os_type to be preferred.
        """
        try:
            os_type_dict = host_state.num_instances_by_os_type
        except AttributeError:
            return 0

        try:
            os_type = weight_properties['os_type']
        except AttributeError:
            return 0

        other_type_num_instances = sum([os_type_dict[key]
                for key in os_type_dict.iterkeys()
                        if key != os_type])
        return -other_type_num_instances


class RAXFuzzHostWeigher(weights.BaseHostWeigher):
    """Use this last in the list of Weighers to modify the top 'x'
    number of hosts.  This provides some slight level of randomization
    in the choices to help reduce races.
    """
    def weigh_objects(self, weighed_obj_list, weight_properties):
        if not CONF.rax_randomize_top_hosts:
            return
        sorted_objs = sorted(weighed_obj_list, key=lambda x: x.weight,
                reverse=True)
        num_hosts = min(CONF.rax_randomize_top_hosts, len(sorted_objs))
        top_weights = [x.weight for x in sorted_objs[:num_hosts]]
        random.shuffle(top_weights)
        # Modify the weights.
        for x in xrange(num_hosts):
            sorted_objs[x].weight = top_weights[x]


def get_weighers():
    return [RAXInstancesHostWeigher, RAXProjectHostWeigher,
            RAXOSTypeHostWeigher, RAXFuzzHostWeigher]
