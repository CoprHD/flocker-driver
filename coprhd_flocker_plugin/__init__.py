# Copyright Hybrid Logic Ltd.
# Copyright 2015 EMC Corporation
# See LICENSE file for details.

from flocker.node import BackendDescription, DeployerType
from coprhd_flocker_plugin.coprhd_blockdevice import configuration


def api_factory(cluster_id, **kwargs):
    return configuration(coprhdhost=kwargs[u'coprhdhost'],port=kwargs[u'port'],
                                  tenant=kwargs[u'tenant'],project=kwargs[u'project'],
                                  varray=kwargs[u'varray'],cookiedir=kwargs[u'cookiedir'],
                                  vpool=kwargs[u'vpool'],vpool_platinum=kwargs[u'vpool_platinum'],vpool_gold=kwargs[u'vpool_gold'],
                                  vpool_silver=kwargs[u'vpool_silver'],vpool_bronze=kwargs[u'vpool_bronze'],
                                  hostexportgroup=kwargs[u'hostexportgroup'],coprhdcli_security_file=kwargs[u'coprhdcli_security_file'])


FLOCKER_BACKEND = BackendDescription(
    name=u"coprhd_flocker_plugin",  # name isn't actually used for 3rd party plugins
    needs_reactor=False, needs_cluster_id=True,
    api_factory=api_factory, deployer_type=DeployerType.block) 
