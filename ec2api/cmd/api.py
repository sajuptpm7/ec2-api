# Copyright 2014
# The Cloudscaling Group, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
EC2api API Server
"""

import sys

from oslo.config import cfg

from ec2api.api import clients
from ec2api import config
from ec2api.openstack.common import log as logging
from ec2api import service


def main():
    config.parse_args(sys.argv)
    logging.setup('ec2api')
    clients.rpc_init(cfg.CONF)

    server = service.WSGIService('ec2api', max_url_len=16384)
    service.serve(server)
    service.wait()


if __name__ == '__main__':
    main()
