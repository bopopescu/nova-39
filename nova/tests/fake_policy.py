# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


policy_data = """
{
    "admin_api": "role:admin",

    "context_is_admin": "role:admin or role:administrator",
    "compute:create": "",
    "compute:create:attach_network": "",
    "compute:create:attach_volume": "",

    "compute:get": "",
    "compute:get_all": "",
    "compute:get_all_tenants": "",

    "compute:update": "",

    "compute:get_instance_metadata": "",
    "compute:get_all_instance_metadata": "",
    "compute:update_instance_metadata": "",
    "compute:delete_instance_metadata": "",

    "compute:get_instance_faults": "",
    "compute:get_diagnostics": "",

    "compute:get_lock": "",
    "compute:lock": "",
    "compute:unlock": "",

    "compute:get_vnc_console": "",
    "compute:get_spice_console": "",
    "compute:get_console_output": "",

    "compute:associate_floating_ip": "",
    "compute:reset_network": "",
    "compute:inject_network_info": "",
    "compute:add_fixed_ip": "",
    "compute:remove_fixed_ip": "",

    "compute:attach_volume": "",
    "compute:detach_volume": "",

    "compute:inject_file": "",

    "compute:set_admin_password": "",

    "compute:rescue": "",
    "compute:unrescue": "",

    "compute:suspend": "",
    "compute:resume": "",

    "compute:pause": "",
    "compute:unpause": "",

    "compute:start": "",
    "compute:stop": "",

    "compute:resize": "",
    "compute:confirm_resize": "",
    "compute:revert_resize": "",

    "compute:rebuild": "",

    "compute:reboot": "",

    "compute:snapshot": "",
    "compute:backup": "",

    "compute:security_groups:add_to_instance": "",
    "compute:security_groups:remove_from_instance": "",

    "compute:delete": "",
    "compute:soft_delete": "",
    "compute:force_delete": "",
    "compute:restore": "",


    "compute_extension:accounts": "",
    "compute_extension:admin_actions:pause": "",
    "compute_extension:admin_actions:unpause": "",
    "compute_extension:admin_actions:suspend": "",
    "compute_extension:admin_actions:resume": "",
    "compute_extension:admin_actions:lock": "",
    "compute_extension:admin_actions:unlock": "",
    "compute_extension:admin_actions:resetNetwork": "",
    "compute_extension:admin_actions:injectNetworkInfo": "",
    "compute_extension:admin_actions:createBackup": "",
    "compute_extension:admin_actions:migrateLive": "",
    "compute_extension:admin_actions:resetState": "",
    "compute_extension:admin_actions:migrate": "",
    "compute_extension:aggregates": "",
    "compute_extension:agents": "",
    "compute_extension:attach_interfaces": "",
    "compute_extension:baremetal_nodes": "",
    "compute_extension:cells": "",
    "compute_extension:certificates": "",
    "compute_extension:cloudpipe": "",
    "compute_extension:cloudpipe_update": "",
    "compute_extension:config_drive": "",
    "compute_extension:console_output": "",
    "compute_extension:consoles": "",
    "compute_extension:coverage_ext": "is_admin:True",
    "compute_extension:createserverext": "",
    "compute_extension:deferred_delete": "",
    "compute_extension:disk_config": "",
    "compute_extension:evacuate": "is_admin:True",
    "compute_extension:extended_server_attributes": "",
    "compute_extension:extended_status": "",
    "compute_extension:extended_availability_zone": "",
    "compute_extension:extended_ips": "",
    "compute_extension:extended_ips_mac": "",
    "compute_extension:extended_vif_net": "",
    "compute_extension:fixed_ips": "",
    "compute_extension:flavor_access": "",
    "compute_extension:flavor_disabled": "",
    "compute_extension:flavor_rxtx": "",
    "compute_extension:flavor_swap": "",
    "compute_extension:flavorextradata": "",
    "compute_extension:flavorextraspecs:index": "",
    "compute_extension:flavorextraspecs:show": "",
    "compute_extension:flavorextraspecs:create": "is_admin:True",
    "compute_extension:flavorextraspecs:update": "is_admin:True",
    "compute_extension:flavorextraspecs:delete": "is_admin:True",
    "compute_extension:flavormanage": "",
    "compute_extension:floating_ip_dns": "",
    "compute_extension:floating_ip_pools": "",
    "compute_extension:floating_ips": "",
    "compute_extension:floating_ips_bulk": "",
    "compute_extension:fping": "",
    "compute_extension:fping:all_tenants": "is_admin:True",
    "compute_extension:hide_server_addresses": "",
    "compute_extension:hosts": "",
    "compute_extension:hypervisors": "",
    "compute_extension:image_size": "",
    "compute_extension:instance_actions": "",
    "compute_extension:instance_actions:events": "is_admin:True",
    "compute_extension:instance_usage_audit_log": "",
    "compute_extension:keypairs": "",
    "compute_extension:multinic": "",
    "compute_extension:networks": "",
    "compute_extension:networks:view": "",
    "compute_extension:networks_associate": "",
    "compute_extension:os-tenant-networks": "",
    "compute_extension:quotas:show": "",
    "compute_extension:quotas:update": "",
    "compute_extension:quota_classes": "",
    "compute_extension:rescue": "",
    "compute_extension:scheduled_images:index": "",
    "compute_extension:scheduled_images:create": "",
    "compute_extension:scheduled_images:delete": "",
    "compute_extension:scheduled_images_filter": "",
    "compute_extension:security_group_default_rules": "",
    "compute_extension:security_groups": "",
    "compute_extension:server_diagnostics": "",
    "compute_extension:server_password": "",
    "compute_extension:services": "",
    "compute_extension:simple_tenant_usage:show": "",
    "compute_extension:simple_tenant_usage:list": "",
    "compute_extension:users": "",
    "compute_extension:virtual_interfaces": "",
    "compute_extension:virtual_storage_arrays": "",
    "compute_extension:volumes": "",
    "compute_extension:volume_attachments:index": "",
    "compute_extension:volume_attachments:show": "",
    "compute_extension:volume_attachments:create": "",
    "compute_extension:volume_attachments:delete": "",
    "compute_extension:volumetypes": "",
    "compute_extension:zones": "",
    "compute_extension:availability_zone:list": "",
    "compute_extension:availability_zone:detail": "is_admin:True",


    "volume:create": "",
    "volume:get": "",
    "volume:get_all": "",
    "volume:get_volume_metadata": "",
    "volume:delete": "",
    "volume:update": "",
    "volume:delete_volume_metadata": "",
    "volume:update_volume_metadata": "",
    "volume:attach": "",
    "volume:detach": "",
    "volume:reserve_volume": "",
    "volume:unreserve_volume": "",
    "volume:begin_detaching": "",
    "volume:roll_detaching": "",
    "volume:check_attach": "",
    "volume:check_detach": "",
    "volume:initialize_connection": "",
    "volume:terminate_connection": "",
    "volume:create_snapshot": "",
    "volume:delete_snapshot": "",
    "volume:get_snapshot": "",
    "volume:get_all_snapshots": "",


    "volume_extension:volume_admin_actions:reset_status": "rule:admin_api",
    "volume_extension:snapshot_admin_actions:reset_status": "rule:admin_api",
    "volume_extension:volume_admin_actions:force_delete": "rule:admin_api",
    "volume_extension:volume_actions:upload_image": "",
    "volume_extension:types_manage": "",
    "volume_extension:types_extra_specs": "",


    "network:get_all": "",
    "network:get": "",
    "network:create": "",
    "network:delete": "",
    "network:associate": "",
    "network:disassociate": "",
    "network:get_vifs_by_instance": "",
    "network:get_vif_by_mac_address": "",
    "network:allocate_for_instance": "",
    "network:deallocate_for_instance": "",
    "network:validate_networks": "",
    "network:get_instance_uuids_by_ip_filter": "",
    "network:get_instance_id_by_floating_address": "",
    "network:setup_networks_on_host": "",

    "network:get_floating_ip": "",
    "network:get_floating_ip_pools": "",
    "network:get_floating_ip_by_address": "",
    "network:get_floating_ips_by_project": "",
    "network:get_floating_ips_by_fixed_address": "",
    "network:allocate_floating_ip": "",
    "network:deallocate_floating_ip": "",
    "network:associate_floating_ip": "",
    "network:disassociate_floating_ip": "",
    "network:release_floating_ip": "",
    "network:migrate_instance_start": "",
    "network:migrate_instance_finish": "",

    "network:get_fixed_ip": "",
    "network:get_fixed_ip_by_address": "",
    "network:add_fixed_ip_to_instance": "",
    "network:remove_fixed_ip_from_instance": "",
    "network:add_network_to_project": "",
    "network:get_instance_nw_info": "",

    "network:get_dns_domains": "",
    "network:add_dns_entry": "",
    "network:modify_dns_entry": "",
    "network:delete_dns_entry": "",
    "network:get_dns_entries_by_address": "",
    "network:get_dns_entries_by_name": "",
    "network:create_private_dns_domain": "",
    "network:create_public_dns_domain": "",
    "network:delete_dns_domain": ""
}
"""
