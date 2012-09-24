# Copyright 2012 Rackspace Hosting
# All Rights Reserved.

"""
Tests For Rackspace weighting functions.
"""
from nova.compute import vm_states
from nova.scheduler import host_manager
from nova.scheduler import weights
from nova import test


class RackspaceWeightsTestCase(test.TestCase):
    def setUp(self):
        super(RackspaceWeightsTestCase, self).setUp()
        # Set up 100 empty hosts
        self.hosts = []
        for i in xrange(100):
            hs = host_manager.HostState('host-%03i' % (i + 1), 'node1')
            hs.free_ram_mb = 32 * 1024
            hs.free_disk_mb = 1 * 1024 * 1024 * 1024
            self.hosts.append(hs)

        self.weight_handler = weights.HostWeightHandler()
        weights_path = 'nova.scheduler.weights.'
        self.classes = self.weight_handler.get_matching_classes(
                [weights_path + 'rackspace_weights.get_weighers'])
        self.class_map = {}
        for cls in self.classes:
            self.class_map[cls.__name__] = cls
        # Must be after weight class imports
        self.flags(rax_randomize_top_hosts=0)

    def _fake_instance(self, memory_mb, disk_gb=None, vm_state=None,
            task_state=None, os_type=None, project_id='1'):
        if disk_gb is None:
            disk_gb = 10
        if vm_state is None:
            vm_state = vm_states.ACTIVE
        if os_type is None:
            os_type = 'linux'
        return dict(ephemeral_gb=0, root_gb=disk_gb,
                memory_mb=memory_mb, vm_state=vm_state,
                task_state=task_state, os_type=os_type,
                vcpus=1, project_id=project_id)

    def _weighing_properties(self, instance):
        weighing_properties = dict(project_id=instance['project_id'],
                os_type=instance['os_type'])
        return weighing_properties

    def _get_weighed_hosts(self, weighing_properties, classes=None):
        if classes is None:
            classes = self.classes
        return self.weight_handler.get_weighed_objects(classes,
                self.hosts, weighing_properties)

    def test_single_instance(self):

        instance = self._fake_instance(512)
        weighing_properties = self._weighing_properties(instance)
        weighted_hosts = self._get_weighed_hosts(weighing_properties)
        host = weighted_hosts[0].obj
        self.assertTrue(host is not None)
        # Should be the first host
        self.assertEqual(host.host, 'host-001')

    def test_one_instance_already_on_first_host(self):
        instance = self._fake_instance(512)
        weighing_properties = self._weighing_properties(instance)
        # Put an instance on first host
        self.hosts[0].consume_from_instance(instance)
        weighted_hosts = self._get_weighed_hosts(weighing_properties)
        host = weighted_hosts[0].obj
        self.assertTrue(host is not None)
        self.assertEqual(host.host, 'host-002')

    def test_two_instances_already_on_first_host(self):
        instance = self._fake_instance(512)
        weighing_properties = self._weighing_properties(instance)
        # Put 2 instances on first host
        self.hosts[0].consume_from_instance(instance)
        self.hosts[0].consume_from_instance(instance)
        weighted_hosts = self._get_weighed_hosts(weighing_properties)
        host = weighted_hosts[0].obj
        self.assertTrue(host is not None)
        # Should be the second host
        self.assertEqual(host.host, 'host-002')

    def test_one_instance_on_first_two_hosts(self):
        instance = self._fake_instance(512)
        weighing_properties = self._weighing_properties(instance)
        # Put 2 instances on first host
        self.hosts[0].consume_from_instance(instance)
        self.hosts[1].consume_from_instance(instance)
        weighted_hosts = self._get_weighed_hosts(weighing_properties)
        host = weighted_hosts[0].obj
        self.assertTrue(host is not None)
        # Should be the second host
        self.assertEqual(host.host, 'host-003')

    def test_one_instance_on_first_two_hosts_diff_project(self):
        instance_proj1 = self._fake_instance(512)
        instance_proj2 = self._fake_instance(512, project_id='2')
        weighing_properties = self._weighing_properties(instance_proj2)
        # Put 2 instances on first host
        self.hosts[0].consume_from_instance(instance_proj1)
        self.hosts[1].consume_from_instance(instance_proj1)
        weighted_hosts = self._get_weighed_hosts(weighing_properties)
        host = weighted_hosts[0].obj
        self.assertTrue(host is not None)
        # Should go to the first host
        self.assertEqual(host.host, 'host-001')

    def test_random_top_hosts(self):
        self.flags(rax_randomize_top_hosts=2)

        instances = [self._fake_instance(512) for x in xrange(6)]
        self.hosts[0].consume_from_instance(instances[0])
        self.hosts[0].consume_from_instance(instances[1])
        self.hosts[0].consume_from_instance(instances[2])
        self.hosts[1].consume_from_instance(instances[3])
        self.hosts[2].consume_from_instance(instances[4])
        self.hosts[2].consume_from_instance(instances[5])
        instance_proj2 = self._fake_instance(512, project_id='2')
        weighing_properties = self._weighing_properties(instance_proj2)

        hosts_picked = {}

        # Run this a number of times and make sure we get a mix.  Highly
        # unlikely we'll pick the same host 100 times with the fuzzing,
        # so this test _should_ pass!  We're going to build an instance
        # with a different project ID than we put on the above hosts.
        # This should result in the higher-loaded hosts above to be picked.
        for i in xrange(100):
            weighted_hosts = self._get_weighed_hosts(weighing_properties)
            hostname = weighted_hosts[0].obj.host
            hosts_picked.setdefault(hostname, 0)
            hosts_picked[hostname] += 1

        self.assertEqual(len(hosts_picked), 2)
        self.assertIn('host-001', hosts_picked.keys())
        self.assertIn('host-003', hosts_picked.keys())
