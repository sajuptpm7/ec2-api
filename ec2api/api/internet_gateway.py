#    Copyright 2014 Cloudscaling Group, Inc
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
Cloud Controller: Implementation of EC2 REST API calls, which are
dispatched to other nodes via AMQP RPC. State is via distributed
datastore.
"""

from neutronclient.common import exceptions as neutron_exception
from oslo.config import cfg

from ec2api.api import clients
from ec2api.api import ec2utils
from ec2api.api import utils
from ec2api.db import api as db_api
from ec2api import exception
from ec2api.openstack.common.gettextutils import _
from ec2api.openstack.common import log as logging


LOG = logging.getLogger(__name__)

ec2_opts = [
    cfg.StrOpt('external_network',
               default=None,
               help='Name of the external network, which is used to connect'
                    'VPCs to Internet and to allocate Elastic IPs'),
]

CONF = cfg.CONF
CONF.register_opts(ec2_opts)

"""Internet gateway related API implementation
"""


def create_internet_gateway(context):
    igw = db_api.add_item(context, 'igw', {})
    return {'internet_gateway': _format_internet_gateway(igw)}


def attach_internet_gateway(context, internet_gateway_id, vpc_id):
    igw = ec2utils.get_db_item(context, 'igw', internet_gateway_id)
    if igw.get('vpc_id'):
        msg_params = {'igw_id': ec2utils.get_ec2_id(igw['id'], 'igw'),
                      'vpc_id': ec2utils.get_ec2_id(igw['vpc_id'], 'vpc')}
        msg = _("resource %(igw_id)s is already attached to "
                "network %(vpc_id)s") % msg_params
        raise exception.ResourceAlreadyAssociated(msg)
    vpc = ec2utils.get_db_item(context, 'vpc', vpc_id)
    # TODO(ft): move search by vpc_id to DB api
    for gw in db_api.get_items(context, 'igw'):
        if gw.get('vpc_id') == vpc['id']:
            msg_params = {'vpc_id': ec2utils.get_ec2_id(vpc['id'], 'vpc')}
            msg = _("Network %(vpc_id)s already has an internet gateway "
                    "attached") % msg_params
            raise exception.InvalidParameterValue(msg)

    neutron = clients.neutron(context)
    # TODO(ft): check no public network exists
    search_opts = {'router:external': True, 'name': CONF.external_network}
    os_networks = neutron.list_networks(**search_opts)['networks']
    os_public_network = os_networks[0]

    # TODO(ft):
    # set attaching state in db
    with utils.OnCrashCleaner() as cleaner:
        _attach_internet_gateway_item(context, igw, vpc['id'])
        cleaner.addCleanup(_detach_internet_gateway_item, context, igw)
        neutron.add_gateway_router(vpc['os_id'],
                                   {'network_id': os_public_network['id']})
    return True


def detach_internet_gateway(context, internet_gateway_id, vpc_id):
    igw = ec2utils.get_db_item(context, 'igw', internet_gateway_id)
    vpc = ec2utils.get_db_item(context, 'vpc', vpc_id)
    if igw.get('vpc_id') != vpc['id']:
        raise exception.GatewayNotAttached(igw_id=igw['id'],
                                           vpc_id=vpc['id'])

    neutron = clients.neutron(context)
    # TODO(ft):
    # set detaching state in db
    with utils.OnCrashCleaner() as cleaner:
        _detach_internet_gateway_item(context, igw)
        cleaner.addCleanup(_attach_internet_gateway_item,
                           context, igw, vpc['id'])
        try:
            neutron.remove_gateway_router(vpc["os_id"])
        except neutron_exception.NotFound:
            # TODO(ft): do log error
            # TODO(ft): adjust catched exception classes to catch:
            # the router doesn't exist
            pass
    return True


def delete_internet_gateway(context, internet_gateway_id):
    igw = ec2utils.get_db_item(context, 'igw', internet_gateway_id)
    if igw.get('vpc_id'):
        msg_params = {'igw_id': ec2utils.get_ec2_id(igw['id'], 'igw')}
        msg = _("The internetGateway '%(igw_id)s' has dependencies and "
                "cannot be deleted.") % msg_params
        raise exception.DependencyViolation(msg)
    db_api.delete_item(context, igw['id'])
    return True


def describe_internet_gateways(context, internet_gateway_id=None,
                               filter=None):
    # TODO(ft): implement filters
    igws = ec2utils.get_db_items(context, 'igw', internet_gateway_id)
    formatted_igws = []
    for igw in igws:
        formatted_igws.append(_format_internet_gateway(igw))
    return {'internetGatewaySet': formatted_igws}


def _format_internet_gateway(igw):
    ec2_igw = {'internetGatewayId': ec2utils.get_ec2_id(igw['id'], 'igw'),
                'attachmentSet': []}
    if igw.get('vpc_id'):
        attachment = {'vpcId': ec2utils.get_ec2_id(igw['vpc_id'], 'vpc'),
                      'state': 'available'}
        ec2_igw['attachmentSet'].append(attachment)
    return ec2_igw


def _attach_internet_gateway_item(context, igw, vpc_id):
    igw['vpc_id'] = vpc_id
    db_api.update_item(context, igw)


def _detach_internet_gateway_item(context, igw):
    igw['vpc_id'] = None
    db_api.update_item(context, igw)