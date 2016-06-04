# Copyright Hybrid Logic Ltd.
# Copyright 2015 EMC Corporation
# See LICENSE file for details.

"""
EMC Test helpers for ``flocker.node.agents``.
"""

import os
import yaml
import socket
from uuid import uuid4

from twisted.trial.unittest import SkipTest

from coprhd_flocker_plugin.coprhd_blockdevice import configuration
from coprhd_flocker_plugin.coprhd_blockdevice import CoprHDCLIDriver

def _read_coprhd_yaml():
    '''
    Reads the yaml file and returns the file object 
    '''
    config_file_path = '/etc/flocker/agent.yml'
    with open(config_file_path, 'r') as stream:
        coprhd_conf = yaml.load(stream)
    return coprhd_conf['dataset']
    
def tidy_coprhd_client_for_test(test_case):
    """
    Return a ``CoprHD Client`and register a ``test_case``
    :param test_case object
    """
    
    dataset = _read_coprhd_yaml()
    coprhdhost=dataset['coprhdhost']
    port = dataset['port']
    tenant = dataset['tenant']
    project = dataset['project']
    varray = dataset['varray']
    cookiedir = dataset['cookiedir']
    vpool = dataset['vpool']
    vpool_platinum = dataset['vpool_platinum']
    vpool_gold = dataset['vpool_gold']
    vpool_silver = dataset['vpool_silver']
    vpool_bronze = dataset['vpool_bronze']
    hostexportgroup = dataset['hostexportgroup']
    coprhdcli_security_file = dataset['coprhdcli_security_file']
        
    coprhdobj = configuration(coprhdhost, port, tenant,project, varray, cookiedir, vpool,vpool_platinum,vpool_gold,vpool_silver,vpool_bronze,hostexportgroup,coprhdcli_security_file)
    return coprhdobj
      