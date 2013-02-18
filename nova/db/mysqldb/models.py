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

"""
MySQLdb models
"""
import sys

from oslo.config import cfg

from nova.db.mysqldb import sql
from nova import exception
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)
_OUR_MODULE = sys.modules[__name__]
_SCHEMA_INFO = {'version': None}


class Constraint(object):
    def __init__(self, conditions):
        self.conditions = conditions

    def check(self, model):
        for key, condition in self.conditions.iteritems():
            condition.check(model, key)


class EqualityCondition(object):
    def __init__(self, values):
        self.values = values

    def check(self, model, field):
        if model[field] not in self.values:
            raise exception.ConstraintNotMet()


class InequalityCondition(object):

    def __init__(self, values):
        self.values = values

    def check(self, model, field):
        if model[field] in self.values:
            raise exception.ConstraintNotMet()


class Join(object):
    def __init__(self, table_name, join_str, join_kwargs=None,
                 join_type=None, use_list=True, use_dict=False,
                 prereq_join_names=None, hidden=False):
        if join_kwargs is None:
            join_kwargs = {}
        if join_type is None:
            join_type = 'LEFT OUTER JOIN'
        if prereq_join_names is None:
            prereq_join_names = []
        # target will be set automatically by _create_models()
        self.target = None
        self.table_name = table_name
        self.join_type = join_type
        self.join_str = join_str
        self.join_kwargs = join_kwargs
        self.use_list = use_list
        self.use_dict = use_dict
        self.prereq_join_names = prereq_join_names
        self.hidden = hidden


class _BaseModel(dict):
    """Base Model.  This is essentially a dictionary with some extra
    methods.  To access values for columns, access this object as a
    dictionary.
    """

    _default_joins = []
    # These will be set automatically in _create_models() below.
    __joins__ = []
    columns = []

    @classmethod
    def get_model(cls, name):
        return getattr(cls.__all_models__, name)

    @classmethod
    def from_response(cls, col_iter):
        obj = cls()
        for column in cls.columns:
            obj[column] = col_iter.next()
        if not obj['id']:
            return None
        # Swap out the joins
        for join_name in cls.__joins__:
            join = getattr(cls, join_name)
            if join.use_list:
                obj[join_name] = []
            elif join.use_dict:
                obj[join_name] = {}
            else:
                obj[join_name] = None
        return obj

    def to_dict(self):
        """Return dictionary representation of ourselves, including
        anything that we joined.
        """
        # 'copy' only creates a new dictionary, not a new model object.
        d = self.copy()
        # Recurse into joins
        for j in self.__joins__:
            val = d[j]
            if val is None:
                continue
            if isinstance(val, dict):
                d[j] = val.copy()
            elif isinstance(val, list):
                d[j] = [x.to_dict() for x in val]
            else:
                d[j] = val.to_dict()
        return d

    @classmethod
    def soft_delete(cls, conn, where_str, **where_kwargs):
        now = timeutils.utcnow()
        query = sql.UpdateQuery(cls, values=dict(deleted_at=now),
                raw_values=dict(deleted='`id`'))
        query = query.where(where_str, **where_kwargs)
        return query.update(conn)


class _BaseBandwidthUsageCache(_BaseModel):
    __model__ = 'BandwidthUsageCache'
    __table__ = 'bw_usage_cache'


class _BaseInstance(_BaseModel):
    __model__ = 'Instance'
    __table__ = 'instances'

    # Joins
    info_cache = Join('instance_info_caches',
            'info_cache.instance_uuid = self.uuid',
            use_list=False)
    metadata = Join('instance_metadata',
            '(metadata.instance_uuid = self.uuid and metadata.deleted = 0)')
    system_metadata = Join('instance_system_metadata',
            '(system_metadata.instance_uuid = self.uuid and '
            'system_metadata.deleted = 0)')
    instance_type = Join('instance_types',
            'instance_type.id = self.instance_type_id',
            use_list=False)
    sec_group_assoc = Join('security_group_instance_association',
            '(sec_group_assoc.instance_uuid = self.uuid and '
            'sec_group_assoc.deleted = 0)',
            hidden=True)
    security_groups = Join('security_groups',
            '(sec_group_assoc.security_group_id = security_groups.id and '
            'security_groups.deleted = 0)',
            prereq_join_names=['sec_group_assoc'])
    # NOTE(deva/comstud): Temporary for bare metal.  See note in
    # _instance_update() in sqlalchemy/api.py
    extra_specs = Join('instance_type_extra_specs',
            '(extra_specs.instance_type_id = self.instance_type_id and '
            'extra_specs.deleted = 0)',
            use_list=False, use_dict=True)

    _default_joins = ['info_cache', 'metadata', 'system_metadata',
                       'instance_type', 'security_groups', 'extra_specs']

    def to_dict(self):
        dict_ = super(_BaseInstance, self).to_dict()
        # We need to add the 'name' hack.
        try:
            base_name = CONF.instance_name_template % dict_['id']
        except TypeError:
            try:
                base_name = CONF.instance_name_template % dict_
            except KeyError:
                base_name = dict_['uuid']
        dict_['name'] = base_name
        return dict_


class _BaseInstanceInfoCache(_BaseModel):
    __model__ = 'InstanceInfoCache'
    __table__ = 'instance_info_caches'


class _BaseInstanceMetadata(_BaseModel):
    __model__ = 'InstanceMetadata'
    __table__ = 'instance_metadata'


class _BaseInstanceSystemMetadata(_BaseModel):
    __model__ = 'InstanceSystemMetadata'
    __table__ = 'instance_system_metadata'


class _BaseInstanceTypes(_BaseModel):
    __model__ = 'InstanceTypes'
    __table__ = 'instance_types'


class _BaseInstanceTypeExtraSpecs(_BaseModel):
    __model__ = 'InstanceTypeExtraSpecs'
    __table__ = 'instance_type_extra_specs'

    def to_dict(self):
        """Return dictionary representation of key/value pairs."""
        return {self['key']: self['value']}


class _BaseSecurityGroup(_BaseModel):
    __model__ = 'SecurityGroup'
    __table__ = 'security_groups'


class _BaseSecurityGroupInstanceAssociation(_BaseModel):
    __model__ = 'SecurityGroupInstanceAssociation'
    __table__ = 'security_group_instance_association'


class Models(object):
    """This will have attributes for every model.  Ie, 'Instance'.
    This gets setattr'd every time we update the schema, so it's an
    atomic swap.  This is here just so pylint, etc is happy.
    """
    pass


def _table_to_base_model_mapping():
    """Create a table name to base model mapping."""
    mapping = {}
    for obj_name in dir(_OUR_MODULE):
        obj = getattr(_OUR_MODULE, obj_name)
        try:
            if issubclass(obj, _BaseModel) and obj_name != '_BaseModel':
                mapping[obj.__table__] = obj
        except TypeError:
            continue
    return mapping


def _create_models(schema):
    tbl_to_base_model = _table_to_base_model_mapping()
    version = schema['version']
    # Create a new Models class.  This will end up with an attribute
    # for every model we create.

    models_obj = type('Models', (object, ), {})
    table_to_model = {}
    for table, table_info in schema['tables'].iteritems():
        # Find the base model for this mapping based on the table name.
        base_model = tbl_to_base_model.get(table)
        if not base_model:
            # Just skip it if we've not defined one yet.
            continue
        model_name = base_model.__model__

        # Create a new class like Instance_v<version>
        vers_model_name = '%s_v%s' % (base_model.__model__, str(version))
        # Find the Mixin class for this model.
        mixin_cls = _mixin_cls(model_name)

        # Do the actual class creation here.  We'll subclass the base
        # model as as from the mixin.  Populate some useful attributes.
        vers_model = type(vers_model_name, (mixin_cls, base_model),
                {'__repo_version__': version,
                 '__all_models__': models_obj,
                 'columns': table_info['columns']})
        # Update '__joins__' on the model and set each Join()'s target
        # to the 'column name'.
        joins = []
        for obj_name in dir(vers_model):
            obj = getattr(vers_model, obj_name)
            try:
                if isinstance(obj, Join):
                    obj.target = obj_name
                    # Skip adding Joins to __joins__ that should remain
                    # hidden
                    if obj.hidden:
                        continue
                    joins.append(obj_name)
            except TypeError:
                continue
        setattr(vers_model, '__joins__', joins)

        # Set this model in our 'Models' object.
        setattr(models_obj, model_name, vers_model)
        table_to_model[table] = vers_model
    # Currently not used
    setattr(models_obj, '__table_model_map__', table_to_model)
    # Update our 'Models' object within this module.
    setattr(_OUR_MODULE, 'Models', models_obj)


class _DefaultMixin(object):
    pass


def _mixin_cls(model_name):
    """Fix the Mixin class for the model.  Each Mixin will be
    in a module named by the model.  Ie, the Instance model Mixin
    will be in mysqldb/instance.py.
    """
    pkg = _OUR_MODULE.__package__
    module_name = ''
    for c in model_name:
        if c.isupper():
            if module_name:
                module_name += '_'
            c = c.lower()
        module_name += c
    mixin_str = ('%(pkg)s.%(name)s.Mixin' % {'pkg': pkg, 'name':
        module_name})
    try:
        return importutils.import_class(mixin_str)
    except ImportError:
        LOG.warn(_("Couldn't load mixin class: %s") % mixin_str)
        return _DefaultMixin


def set_schema(schema):
    """Update our schema and regenerate our models if the version changed."""
    if schema['version'] != _SCHEMA_INFO['version']:
        _SCHEMA_INFO['version'] = schema['version']
        _create_models(schema)
