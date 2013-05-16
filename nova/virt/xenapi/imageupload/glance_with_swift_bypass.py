# Copyright 2013 Rackspace Hosting
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

import urllib

from oslo.config import cfg

from nova import exception
from nova.image import glance
import nova.openstack.common.log as logging
from nova.virt.xenapi import vm_utils

LOG = logging.getLogger(__name__)

swift_opts = [
    cfg.StrOpt("swift_store_auth_version",
               default="2",
               help='Version of authentication service to use'),
    cfg.StrOpt("swift_store_auth_address",
               default="http://localhost:5000/v2.0/",
               help='Address where swift authentication service lives'),
    cfg.StrOpt("swift_store_user",
               default="tenant:user",
               help='User to authenticate against the swift authentication'
                    ' service'),
    cfg.StrOpt("swift_store_key",
               default="openstack",
               help='Auth key for the user authenticating'),
    cfg.StrOpt("swift_store_container",
               default="glance",
               help='Container that the account should use'),
    cfg.BoolOpt("swift_store_create_container_on_put",
                default=True,
                help='Whether to create the container if the container does'
                     ' not already exist'),
    cfg.IntOpt("swift_store_large_object_size",
               default=5 * 1024,
               help='The maximum image file size in megabytes that the file'
                    ' can be uploaded without chunking'),
    cfg.IntOpt("swift_store_large_object_chunk_size",
               default=4 * 1024,
               help='The size of chunks in megabytes in which images are'
                    ' uploaded to swift'),
    cfg.BoolOpt("swift_enable_snet",
                default=False,
                help='Whether to use ServiceNET to communicate with Swift'
                     ' storage servers'),
    cfg.StrOpt("swift_store_region",
                default=None,
                help='The region of swift endpoint to be used. The setting'
                      ' is only necessary when multiple endpoints are used'),
    cfg.BoolOpt("swift_store_multitenant",
                default=False,
                help='When set to True, enables multi-tenant storage mode'
                     ' which causes images to be stored in tenant specific'
                     ' Swift accounts')
]

CONF = cfg.CONF

CONF.register_opts(swift_opts)


class Store(object):
    """Driver for uploading image data directly to Swift and
    updating image metadata in Glance.
    """

    def __init__(self, image_service=None):
        self.image_service = (image_service or
                              glance.get_default_image_service())
        self.store_url = None

    def get_image_url(self, image_id):
        """
        Creates location uri for the specified image.

        :param image_id id of the image
        """
        auth_or_store_url = self.store_url or CONF.swift_store_auth_address
        scheme = 'swift+https'

        if auth_or_store_url.startswith('http://'):
            scheme = 'swift+http'
            auth_or_store_url = auth_or_store_url[len('http://'):]
        elif auth_or_store_url.startswith('https://'):
            auth_or_store_url = auth_or_store_url[len('https://'):]

        credstring = self._get_credstring()
        auth_or_store_url = auth_or_store_url.strip('/')
        container = CONF.swift_store_container.strip('/')
        obj = str(image_id).strip('/')

        return '%s://%s%s/%s/%s' % (scheme, credstring, auth_or_store_url,
                                    container, obj)

    def _get_credstring(self):
        if not CONF.swift_store_multitenant:
            user = urllib.quote(CONF.swift_store_user)
            key = urllib.quote(CONF.swift_store_key)
            return '%s:%s@' % (user, key)
        return ''

    def upload_image(self, context, session, instance, vdi_uuids, image_id,
                     max_size=0):
        """Uploads the image data to swift and updates the image metadata in
        glance.

        If any errors occur in the upload process then the image is deleted.
        """
        try:
            image_metadata = self.upload_vhd(context,
                                             session,
                                             instance,
                                             vdi_uuids,
                                             image_id,
                                             max_size)
        except Exception:
            LOG.exception(_('Error taking snapshot'))
            LOG.warn(_('Deleting image %s') % image_id)
            self._delete_image_glance(context, image_id)
        else:
            self._update_image_glance(context, image_id, image_metadata)

    def upload_vhd(self, context, session, instance, vdi_uuids, image_id,
                   max_size=0):
        """Requests that the Swift plugin bundle the specified VDIs and
        push them into Swift.
        """
        # NOTE(sirp): Currently we only support uploading images as VHD, there
        # is no RAW equivalent (yet)
        LOG.debug(_("Asking xapi to upload to swift %(vdi_uuids)s as"
                    " ID %(image_id)s"), locals(), instance=instance)

        large_object_size = CONF.swift_store_large_object_size
        large_chunk_size = CONF.swift_store_large_object_chunk_size
        create_container = CONF.swift_store_create_container_on_put

        params = {'vdi_uuids': vdi_uuids,
                  'image_id': image_id,
                  'sr_path': vm_utils.get_sr_path(session),
                  'swift_enable_snet': CONF.swift_enable_snet,
                  'swift_store_auth_version': CONF.swift_store_auth_version,
                  'swift_store_container': CONF.swift_store_container,
                  'swift_store_large_object_size': large_object_size,
                  'swift_store_large_object_chunk_size': large_chunk_size,
                  'swift_store_create_container_on_put': create_container,
                  'project_id': context.project_id,
                  'max_size': max_size,
                 }

        if CONF.swift_store_region:
            params['region_name'] = CONF.swift_store_region

        if CONF.swift_store_multitenant:
            params['storage_url'] = None
            if context.service_catalog:
                service_catalog = context.service_catalog
                endpoint = self._get_object_store_endpoint(service_catalog,
                                      region=CONF.swift_store_region)
                self.store_url = endpoint['publicURL']
                params['storage_url'] = endpoint['publicURL']
            params['token'] = context.auth_token
        else:
            params['swift_store_user'] = CONF.swift_store_user
            params['swift_store_key'] = CONF.swift_store_key
            params['full_auth_address'] = CONF.swift_store_auth_address

        return session.call_plugin_serialized('swift', 'upload_vhd', **params)

    def _get_object_store_endpoint(self, service_catalog, region=None):
        endpoints = []
        for service in service_catalog:
            if service.get('type') == 'object-store':
                for ep in service['endpoints']:
                    if not region or region == ep['region']:
                        endpoints.append(ep)

        if len(service['endpoints']) == 1:
            return endpoints[0]
        elif len(service['endpoints']) > 1:
            raise exception.RegionAmbiguity(region=region)

        raise exception.NoServiceEndpoint(service_id='object-store')

    def _update_image_glance(self, context, image_id, image_metadata):
        """Updates Image with the metadata obtained after upload to store.

        :param context: security context
        :param image_id: glance.db.sqlalchemy.models.Image.Id
        :param image_metadata: image metadata to be updated in glance
        """
        image_meta = {'checksum': image_metadata['etag'],
                      'size': image_metadata['image_size'],
                      'location': self.get_image_url(image_id),
                      'disk_format': image_metadata['disk_format'],
                      'container_format': image_metadata['container_format']}
        self.image_service.update(context, image_id, image_meta,
                                  purge_props=False)

    def _delete_image_glance(self, context, image_id):
        try:
            self.image_service.delete(context, image_id)
        except exception.ImageNotFound:
            msg = _('Could not cleanup image %s, it does not exist in glance')
            LOG.warn(msg % image_id)
