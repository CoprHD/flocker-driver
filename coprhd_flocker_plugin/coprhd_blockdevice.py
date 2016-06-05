# Copyright Hybrid Logic Ltd.
# Copyright 2015-2016 EMC Corporation
# See LICENSE file for details..

from uuid import UUID, uuid4
from decimal import *

from flocker.node.agents.blockdevice import (
    VolumeException, AlreadyAttachedVolume,
    UnknownVolume, UnattachedVolume,
    IBlockDeviceAPI, BlockDeviceVolume, IProfiledBlockDeviceAPI,
    UnknownInstanceID, get_blockdevice_volume
)

import socket
import sys
import traceback
import viprcli.authentication as auth
import viprcli.common as utils
import viprcli.exportgroup as exportgroup
import viprcli.host as hosts
import viprcli.hostinitiators as host_initiator
import viprcli.snapshot as snapshot
import viprcli.virtualarray as virtualarray
import viprcli.volume as volume
import viprcli.consistencygroup as consistencygroup
import viprcli.tag as tag
import viprcli.project as coprhdproject
import viprcli.storagesystem as storagesystem
import viprcli.storageport as storageport
import viprcli.network as network

from eliot import Message, Logger
from twisted.python.filepath import FilePath
from zope.interface import implementer
from subprocess import check_output

import base64
import urllib
import urllib2
import json
import os
import re
import socket
import viprcli
_logger = Logger()

def retry_wrapper(func):
    def try_and_retry(*args, **kwargs):
        retry = False
        try:
            return func(*args, **kwargs)
        except utils.SOSError as e:
            # if we got an http error and
            # the string contains 401 or if the string contains the word cookie
            if (e.err_code == utils.SOSError.HTTP_ERR and
			    (e.err_text.find('401') != -1 or
				 e.err_text.lower().find('cookie') != -1)):
                retry = True
                CoprHDCLIDriver.AUTHENTICATED = False
            else:
                exception_message = "\nViPR Exception: %s\nStack Trace:\n%s" \
                    % (e.err_text, traceback.format_exc())
                raise utils.SOSError(utils.SOSError.SOS_FAILURE_ERR,"Exception is : "+exception_message)
        except Exception:
            exception_message = "\nGeneral Exception: %s\nStack Trace:\n%s" \
                % (sys.exc_info()[0], traceback.format_exc())
            raise utils.SOSError(utils.SOSError.SOS_FAILURE_ERR,"Exception is : "+exception_message)
        if retry:
            return func(*args, **kwargs)
    return try_and_retry


class CoprHDCLIDriver(object):

    AUTHENTICATED = False
    def __init__(self, coprhdhost, 
                 port, tenant, 
                 project, varray, cookiedir, vpool,vpool_platinum,vpool_gold,vpool_silver,vpool_bronze,hostexportgroup,coprhdcli_security_file):
        self.coprhdhost = coprhdhost
        self.port =  port
        self.tenant = tenant
        self.project = project
        self.varray = varray
        self.cookiedir = cookiedir
        self.vpool = vpool
        self.vpool_platinum=vpool_platinum
        self.vpool_gold=vpool_gold
        self.vpool_silver=vpool_silver
        self.vpool_bronze=vpool_bronze
        self.hostexportgroup = hostexportgroup
        self.coprhdcli_security_file = coprhdcli_security_file
        self.host = unicode(socket.gethostname())
        self.networkname = 'flockeripnetwork'
        self.volume_obj = volume.Volume(
            self.coprhdhost,
            self.port )
        
        self.exportgroup_obj = exportgroup.ExportGroup(
            self.coprhdhost,
            self.port)            

        self.project_obj = coprhdproject.Project(
            self.coprhdhost,
            self.port)

        self.host_obj = hosts.Host(
            self.coprhdhost,
            self.port)

        self.hostinitiator_obj = host_initiator.HostInitiator(
            self.coprhdhost,
            self.port)

        self.storagesystem_obj = storagesystem.StorageSystem(
            self.coprhdhost,
            self.port)

        self.storageport_obj = storageport.Storageport(
            self.coprhdhost,
            self.port)

        self.varray_obj = virtualarray.VirtualArray(
            self.coprhdhost,
            self.port)

        self.network_obj = network.Network(
            self.coprhdhost,
            self.port)
         
        self.create_project(self.project)

        self.create_host(name=self.host,label=self.host,hosttype="Other") 

        self.add_initiators(True, hostlabel=self.host, protocol='iSCSI', portwwn=None, initname=None)

        self.create_network(name=self.networkname,nwtype='IP')

        self.create_export_group(name=self.hostexportgroup,host=self.host,exportgrouptype="Host")
    @retry_wrapper
    def authenticate_user(self):
         
        # we should check to see if we are already authenticated before blindly
        # doing it again
        if CoprHDCLIDriver.AUTHENTICATED is False:
            utils.COOKIE = None
            objauth = auth.Authentication(
                self.coprhdhost,
                self.port)
            cookiedir = self.cookiedir
            if( (self.coprhdcli_security_file is not '')
               and (self.coprhdcli_security_file is not None)):
                from Crypto.Cipher import ARC4
                import getpass
                objarc = ARC4.new(getpass.getuser())
                security_file = open(self.coprhdcli_security_file, 'r')
                cipher_text = security_file.readline().rstrip()
                self.username = objarc.decrypt(cipher_text)
                cipher_text = security_file.readline().rstrip()
                self.password = objarc.decrypt(cipher_text)
                security_file.close()
            objauth.authenticate_user(self.username,
                                  self.password,
                                  cookiedir,
                                  None)
            CoprHDCLIDriver.AUTHENTICATED = True
    
    @retry_wrapper
    def get_volume_lunid(self, vol):
        self.authenticate_user()
        Message.new(Info="coprhd-get_volume_lunid" + vol).write(_logger)
        try:
           volumeuri = self.volume_obj.volume_query(
                         self.tenant +
                         "/" +
                         self.project
                         + "/" + vol)
           if not volumeuri:
            return
           volumedetails = self.volume_obj.show_by_uri(volumeuri)
           groupdetails = self.exportgroup_obj.exportgroup_show(
                         self.hostexportgroup,
                         self.project,
                         self.tenant)
           exportedvolumes =  groupdetails['volumes'] 
           Message.new(Info="coprhd-get_volume_lunid for loop").write(_logger)
           for evolumes in exportedvolumes:
              if volumeuri == evolumes['id']:
               return evolumes['lun']
           return 
        except utils.SOSError as e:
            if e.err_code == utils.SOSError.NOT_FOUND_ERR:
                Message.new(Debug="Volume : doesnot exist").write(_logger)
            elif(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd get volume lunid http error" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd get volume lunid failed" + e.err_text)
            else:
                Message.new(Debug="coprhd-get_volume_lunid failed").write(_logger)
    
    @retry_wrapper
    def get_volume_wwn(self, vol):
        self.authenticate_user()
        Message.new(Info="coprhd-get_volume_wwn" + vol).write(_logger)
        try:
           volumeuri = self.volume_obj.volume_query(
                         self.tenant +
                         "/" +
                         self.project
                         + "/" + vol)
           if not volumeuri:
            return
           volumedetails = self.volume_obj.show_by_uri(volumeuri)
           groupdetails = self.exportgroup_obj.exportgroup_show(
                         self.hostexportgroup,
                         self.project,
                         self.tenant)
           exportedvolumes =  groupdetails['volumes'] 
           Message.new(Info="coprhd-get_volume_wwn for loop").write(_logger)
           for evolumes in exportedvolumes:
              if volumeuri == evolumes['id']:
               return volumedetails['wwn']
           return 
        except utils.SOSError as e:
            if e.err_code == utils.SOSError.NOT_FOUND_ERR:
                Message.new(Debug="Volume : doesnot exist").write(_logger)
                return None
            elif(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd get volume wwn http error" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd get volume wwn details failed" + e.err_text)
            else:
                Message.new(Debug="coprhd-get_volume_wwn failed").write(_logger)
                    
    @retry_wrapper                
    def get_volume_details(self, vol):
        self.authenticate_user()
        volume_dict = {}
        Message.new(Info="coprhd-get-volume-details" + vol).write(_logger)
        try:
           volumeuri = self.volume_obj.volume_query(
                         self.tenant +
                         "/" +
                         self.project
                         + "/" + vol)
           if not volumeuri:
            return
           volumedetails = self.volume_obj.show_by_uri(volumeuri)
           groupdetails = self.exportgroup_obj.exportgroup_show(
                         self.hostexportgroup,
                         self.project,
                         self.tenant)
           exportedvolumes =  groupdetails['volumes'] 
           Message.new(Info="coprhd-get-volume-details for loop").write(_logger)
           for evolumes in exportedvolumes:
              if volumeuri == evolumes['id']:
               volume_dict[volumedetails['name'][8:]]={'size':volumedetails['provisioned_capacity_gb'],'attached_to':self.host}
               return volume_dict
           volume_dict[volumedetails['name'][8:]]={'size':volumedetails['provisioned_capacity_gb'],'attached_to':None}
           return volume_dict
        except utils.SOSError as e:
            if e.err_code == utils.SOSError.NOT_FOUND_ERR:
                Message.new(Debug="Volume : doesnot exist").write(_logger)
            elif(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd get volume http error" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd get volume details failed" + e.err_text)
            else:
                Message.new(Debug="coprhd get volume details failed").write(_logger)
    
    @retry_wrapper
    def list_volume(self):
        self.authenticate_user()
        flocker_volumes = {}
        try:
            project_uri = self.project_obj.project_query(self.project)
            volume_uris = self.volume_obj.search_volumes(project_uri)
            if not volume_uris:
             return None
            export_uris = self.exportgroup_obj.exportgroup_list(self.project, self.tenant)
            for v_uri in volume_uris:
             attach_to=None
             for e_uri in export_uris:
              groupdetails = self.exportgroup_obj.exportgroup_show(e_uri, self.project, self.tenant)
              exportedvolumes =  groupdetails['volumes']
              for evolumes in exportedvolumes:
                  #Message.new(Debug="coprhd list_volume for loop" + evolumes['id'] + v_uri).write(_logger)           
                  if evolumes['id'] == v_uri:
                    attach_to = socket.gethostbyaddr(groupdetails['name'])
                    attach_to = attach_to[0]
                    attach_to = unicode(attach_to.split('.')[0])
                    #Message.new(Debug="coprhd list_volume attached to" + attach_to).write(_logger)
                    showvolume = self.volume_obj.show_by_uri(v_uri)
                    if showvolume['name'].startswith('flocker'):
                        flocker_volumes[showvolume['name'][8:]] = {'size' : showvolume['allocated_capacity_gb'] , 'attached_to' : attach_to}
                    break
             if attach_to is None:
              showvolume = self.volume_obj.show_by_uri(v_uri)
              if showvolume['name'].startswith('flocker'):
                  flocker_volumes[showvolume['name'][8:]] = {'size' : showvolume['allocated_capacity_gb'] , 'attached_to' : None}
        except utils.SOSError as e:
            if e.err_code == utils.SOSError.NOT_FOUND_ERR:
                Message.new(Debug="no volumes for project").write(_logger)
            elif(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd list volumes http error" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd list_volumes failed" + e.err_text)
            else:
                Message.new(Debug="coprhd list volume failed").write(_logger)
        return flocker_volumes
        
    @retry_wrapper
    def create_volume(self, vol, size,profile_name=None):
        self.authenticate_user()
        Message.new(Debug="coprhd create_volume").write(_logger)
        if str(profile_name).lower() == 'platinum':
           self.vpool=self.vpool_platinum
        elif str(profile_name).lower() == 'gold':
           self.vpool=self.vpool_gold
        elif str(profile_name).lower() == 'silver':
           self.vpool=self.vpool_silver
        elif str(profile_name).lower() == 'bronze':
           self.vpool=self.vpool_bronze
        else:
           self.vpool=self.vpool
        try:
                self.volume_obj.create(
                self.tenant + "/" +
                self.project,
                vol, size, self.varray,
                self.vpool, protocol=None,
                # no longer specified in volume creation
                sync=True,
                number_of_volumes=1,
                thin_provisioned=None,
                # no longer specified in volume creation
                consistencygroup=None)
        except utils.SOSError as e:
            if(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd create volumes http error" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd create volume failed" + e.err_text)
            else:
                Message.new(Debug="coprhd create_volume failed").write(_logger)

    @retry_wrapper
    def unexport_volume(self, vol):
        self.authenticate_user()
        try:
               self.exportgroup_obj.exportgroup_remove_volumes(
                True,
                self.hostexportgroup,
                self.tenant,
                self.project,
                [vol],
                None,
                None)
        except utils.SOSError as e:
         if(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd unexport_volume http error" + e.err_text)
         elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd unexport_volume failed" + e.err_text)
         else:
                Message.new(Debug="coprhd unexport volume failed").write(_logger)

    @retry_wrapper
    def export_volume(self, vol):
        self.authenticate_user()
        Message.new(Info="coprhd export_volume").write(_logger)
        try:
                self.exportgroup_obj.exportgroup_add_volumes(
                True,
                self.hostexportgroup,
                self.tenant,
                self.project,
                [vol],
                None,
                None)
        except utils.SOSError as e:
         if(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd export_volume http error" + e.err_text)
         elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd export_volume failed" + e.err_text)
         else:
                Message.new(Debug="coprhd export_volume failed").write(_logger)
                
    @retry_wrapper
    def delete_volume(self, vol):
        self.authenticate_user()
        try:
               self.volume_obj.delete(
                self.tenant +
                "/" +
                self.project +
                "/" +
                vol,
                volume_name_list=None,
                sync=True)
        except utils.SOSError as e:
            if e.err_code == utils.SOSError.NOT_FOUND_ERR:
                Message.new(Debug="Volume : already deleted").write(_logger)
            elif e.err_code == utils.SOSError.SOS_FAILURE_ERR:
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "Volume " + name + ": Delete failed\n" + e.err_text)
            else:
                Message.new(Debug="Volume : delete failed").write(_logger)
    
    def create_project(self,name):
        self.authenticate_user()
        Message.new(Debug="coprhd create_project").write(_logger)
        try:
            self.project_obj.project_create(
                name,
                self.tenant)
        except utils.SOSError as e:
            if e.err_code == utils.SOSError.ENTRY_ALREADY_EXISTS_ERR:
                Message.new(Debug="Project with "+self.project+" already exists").write(_logger)
            elif(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd create project HTTP_ERR" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd create project failed" + e.err_text)
            else:
                Message.new(Debug="coprhd create project failed").write(_logger)

    def create_export_group(self,name,host,exportgrouptype="Host"):
        self.authenticate_user()
        try:
            self.exportgroup_obj.exportgroup_create(
                name,
                self.project,
                self.tenant,
                self.varray,
                exportgrouptype)
            
            '''
            Adding Host to Export Group
            '''
           
            sync = True
            self.exportgroup_obj.exportgroup_add_host(exportgroupname=name,tenantname=self.tenant,
                                                      projectname=self.project,hostlabels=[host],sync=sync)

            '''
            Adding Host Initiator to Export Group
            '''
            
            initator = None
            f = open ('/etc/iscsi/initiatorname.iscsi','r')
            for line in f:
               if ( line[0] != '#' ):
                  current_line=line.split('=')
                  initator = current_line[1]
                  if "\n" in initator:
                    initator = initator.split('\n')[0]
                  self.exportgroup_obj.exportgroup_add_initiator(name,self.tenant,self.project,[initator], host, sync)
        
        except utils.SOSError as e:
            if(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd create export groups HTTP_ERR" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd create export groups failed" + e.err_text)
            else:
                Message.new(Debug="coprhd create export groups failed").write(_logger)

    def create_host(self,name,label,hosttype="Other"):
        self.authenticate_user()
        hostname = self.host_obj.search_by_name(name)
        if(hostname):
         Message.new(Debug="host"+name+"already exists").write(_logger)
         return
        try:
            self.host_obj.create(
                 name,
                 hosttype=hosttype,
                 label=label,
                 tenant=self.tenant,
                 port=5985,
                 username=self.username,
                 passwd= None,
                 usessl=True,
                 osversion=None,
                 cluster=None,
                 datacenter=None,
                 vcenter=None,
                 autodiscovery=False,
                 project=None,
                 bootvolume=None,
                 testconnection=None)
        except utils.SOSError as e:
            if(e.err_code == utils.SOSError.HTTP_ERR):
                if(e.err_text.find('host with the same hostName already exists') != -1):
                 Message.new(Debug="coprhd add host already added").write(_logger)
                else:
                 raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd add initiators HTTP_ERR" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd create host failed" + e.err_text)
            else:
                Message.new(Debug="coprhd create host failed").write(_logger)

    def add_initiators(self,sync, hostlabel, protocol, portwwn,initname):
        self.authenticate_user()
        portwwn = None
        try:
           f = open ('/etc/iscsi/initiatorname.iscsi','r')
           for line in f:
              if ( line[0] != '#' ):
                s1=line.split('=')
                portwwn = str(s1[1])
                if "\n" in portwwn:
                   portwwn = portwwn.split('\n')[0]
                break
           initname = portwwn
           initiatorwwn = None
           self.hostinitiator_obj.create(sync,hostlabel,protocol,initiatorwwn,portwwn)
        except utils.SOSError as e:
            if(e.err_code == utils.SOSError.HTTP_ERR):
                if(e.err_text.find('same Initiator Port already exists') != -1):
                 Message.new(Debug="coprhd add initiators already added").write(_logger)
                else:
                 raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd add initiators HTTP_ERR" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd add initiators failed" + e.err_text)
            else:
                Message.new(Debug="coprhd add initiators failed").write(_logger)
    
    def create_network(self,name,nwtype):
        self.authenticate_user()
        try:
            networkid = self.network_obj.query_by_name(name)
            if networkid:
             Message.new(Debug="Network Already Exists").write(_logger)
            else: 
             self.network_obj.create(name,nwtype)
            
            "Adding Host Ports to Network"
            f = open ('/etc/iscsi/initiatorname.iscsi','r')
            for line in f:
               if line[0] != '#':
                  current_line=line.split('=')
                  host_port = current_line[1]
                  if "\n" in host_port[1]:
                    host_port = host_port.split('\n')[0]
                  tz = self.network_obj.show(name)
                  if ("endpoints" in tz):
                   endpoints = tz['endpoints']
                   if host_port not in endpoints:
                    self.network_obj.add_endpoint(name,endpoint=host_port)
                  break
        except utils.SOSError as e:
            if(e.err_code == utils.SOSError.HTTP_ERR):
                raise utils.SOSError(
                    utils.SOSError.HTTP_ERR,
                    "coprhd create network HTTP_ERR" + e.err_text)
            elif(e.err_code == utils.SOSError.SOS_FAILURE_ERR):
                raise utils.SOSError(
                    utils.SOSError.SOS_FAILURE_ERR,
                    "coprhd create network failed" + e.err_text)
            else:
                Message.new(Debug="coprhd create network failed").write(_logger)

@implementer(IProfiledBlockDeviceAPI)
@implementer(IBlockDeviceAPI)
class CoprHDBlockDeviceAPI(object):
    """
    A simulated ``IBlockDeviceAPI`` which creates volumes (devices) with COPRHD.
    """

    def __init__(self, coprhdcliconfig, allocation_unit=None):
        """
       :param configuration: Arrayconfiguration
       """
        self.coprhdcli = coprhdcliconfig
        self._compute_instance_id = unicode(socket.gethostname())
        self._allocation_unit = 1
    
    def compute_instance_id(self):
        """
        :return: Compute instance id
        """
        return self._compute_instance_id
        
    def allocation_unit(self):
        """
        Return allocation unit
        """
        return self._allocation_unit
        
    def create_volume(self, dataset_id, size):
        """
        Create a volume of specified size on the COPRHD.
        The size shall be rounded off to 1GB, as COPRHD
        volumes of these sizes.

        See ``IBlockDeviceAPI.create_volume`` for parameter and return type
        documentation.
        """
        Message.new(Info="coprhd create_volume size is " + str(size)).write(_logger)
        volumesdetails = self.coprhdcli.get_volume_details("flocker-{}".format(dataset_id))
        if not volumesdetails:
         self.coprhdcli.create_volume("flocker-{}".format(dataset_id),size)
         Message.new(Debug="coprhd create_volume done").write(_logger)
        return BlockDeviceVolume(
          size=size, attached_to=None, dataset_id=dataset_id, blockdevice_id=u"block-{0}".format(dataset_id)
        )
    def create_volume_with_profile(self,dataset_id, size, profile_name):
        """
        Create a volume of specified size and profile on the COPRHD.
        The size shall be rounded off to 1GB, as COPRHD
        volumes of these sizes.
        
        profile can either 'PLATINUM' or 'GOLD' or 'SILVER' or 'BRONZE'
        
        See `IProfiledBlockDeviceAPI.create_volume_with_profile` for parameter and return type
        documentation.
        """

        Message.new(Info="coprhd create_volume size is " + str(size)).write(_logger)
        Message.new(Info="coprhd create_volume profile is " + str(profile_name)).write(_logger)
       
        volumesdetails = self.coprhdcli.get_volume_details("flocker-{}".format(dataset_id))
        if not volumesdetails:
           self.coprhdcli.create_volume("flocker-{}".format(dataset_id),size,profile_name=profile_name)
           Message.new(Debug="coprhd create_volume_with_profile done").write(_logger)
        return BlockDeviceVolume(size=size, attached_to=None, dataset_id=dataset_id, blockdevice_id=u"block-{0}".format(dataset_id))

    def destroy_volume(self, blockdevice_id):
        """
        Destroy the storage for the given unattached volume.
        :param: blockdevice_id - the volume id
        :raise: UnknownVolume is not found
        """
        try:
         dataset_id = UUID(blockdevice_id[6:])
        except ValueError:
         raise UnknownVolume(blockdevice_id)
        volumesdetails = self.coprhdcli.get_volume_details("flocker-{}".format(dataset_id))
        if not volumesdetails:
         raise UnknownVolume(blockdevice_id)
        Message.new(Info="Destroying Volume" + str(blockdevice_id)).write(_logger)
        self.coprhdcli.delete_volume("flocker-{}".format(dataset_id))
   
    def attach_volume(self, blockdevice_id, attach_to):
        """
        Attach volume associates a volume with to a initiator group. The resultant of this is a
        LUN - Logical Unit Number. This association can be made to any number of initiator groups. Post of this
        attachment, the device shall appear in /dev/sd<1>.
        See ``IBlockDeviceAPI.attach_volume`` for parameter and return type
        documentation.
        """
        Message.new(Debug="coprhd attach_volume invoked").write(_logger)
        try:
         dataset_id = UUID(blockdevice_id[6:])
        except ValueError:
         raise UnknownVolume(blockdevice_id)
        volumesdetails = self.coprhdcli.get_volume_details("flocker-{}".format(dataset_id))
        Message.new(Info="coprhd got volume details").write(_logger)
        if not volumesdetails:
         raise UnknownVolume(blockdevice_id)
         
        if volumesdetails[volumesdetails.keys()[0]]['attached_to'] is not None:
           Message.new(Info="coprhd already attached volume").write(_logger)
           raise AlreadyAttachedVolume(blockdevice_id)
        else:
           Message.new(Info="coprhd invoking export_volume").write(_logger)
           self.coprhdcli.export_volume("flocker-{}".format(dataset_id))
        self.rescan_scsi()
        self.rescan_scsi()
        self.rescan_scsi()
        size = Decimal(volumesdetails[volumesdetails.keys()[0]]['size'])
        size = 1073741824 * int(size)
        check_output([b"iscsiadm", "-m", "node", "--logout"])
        check_output([b"iscsiadm", "-m", "node", "--login"])
        return BlockDeviceVolume(
          size=size, attached_to=attach_to,
          dataset_id=dataset_id,
          blockdevice_id=blockdevice_id,
        )
    
    def rescan_scsi(self):
        """
        Rescan SCSI bus. This is needed in situations:
            - Resize of volumes
            - Detach of volumes
            - Possibly creation of new volumes
        :return:none
        """
        channel_number = self._get_channel_number()
        # Check for error condition
        if channel_number < 0:
            Message.new(error="iSCSI login not done for VRAID bailing out").write(_logger)
            raise DeviceException
        else:
            check_output(["/usr/bin/rescan-scsi-bus.sh", "-r", "-c", channel_number])
        
    def _get_channel_number(self):
        """
        Query scsi to get channel number of XtremIO devices.
        Right now it supports only one XtremIO connected array
        :return: channel number
        """
        output = check_output([b"/usr/bin/lsscsi"])
        # lsscsi gives output in the following form:
        # [0:0:0:0]    disk    ATA      ST91000640NS     SN03  /dev/sdp
        # [1:0:0:0]    disk    DGC      LUNZ             0532  /dev/sdb
        # [1:0:1:0]    disk    DGC      LUNZ             0532  /dev/sdc
        # [8:0:0:0]    disk    MSFT     Virtual HD       6.3   /dev/sdd
        # [9:0:0:0]    disk XtremIO  XtremApp         2400     /dev/sde

        # We shall parse the output above and to give out channel number
        # as 9
        for row in output.split('\n'):
            if re.search(r'VRAID', row, re.I):
                channel_row = re.search('\d+', row)
                if channel_row:
                    channel_number = channel_row.group()
                    return channel_number

        # Did not find channel number of xtremIO
        # The number cannot be negative
        return -1
        
    def get_device_path(self, blockdevice_id):
        """
        :param blockdevice_id:
        :return:the device path
        """
        #[1:0:0:0]    cd/dvd                                  /dev/sr0
        #[2:0:0:0]    disk                                    /dev/sda
        #[3:0:0:0]    disk    0x600601608d2037004fb79f66c1e5e  /dev/sdb
        #[3:0:0:3]    disk    0x600601608d20370029ab9a2b1acfe  /dev/sde
        #[4:0:0:0]    disk                                    /dev/sdc
        #[4:0:0:3]    disk                                    /dev/sdd
        devicePath = " "
        self.rescan_scsi()
        try:
         dataset_id = UUID(blockdevice_id[6:])
        except ValueError:
         raise UnknownVolume(blockdevice_id)
        # Query WWN from CoprHD
        wwn = None
        wwn = self.coprhdcli.get_volume_wwn("flocker-{}".format(dataset_id))
        if not wwn:
         raise UnattachedVolume(blockdevice_id)
        wwn = wwn[:len(wwn)-3]
        lunid = self.coprhdcli.get_volume_lunid("flocker-{}".format(dataset_id))
        output = check_output([b"/usr/bin/lsscsi"])
        for row in output.split('\n'):
                if re.search(r'VRAID', row, re.I):
                    if re.search(r'\d:\d:\d:' + str(lunid), row, re.I):
                        device_name = re.findall(r'/\w+', row, re.I)
                        if device_name:
                            devicePath = device_name[0] + device_name[1]

        if devicePath:
            Message.new(value="get_device_path returned : " + devicePath).write(_logger)
            return FilePath(devicePath)
        raise UnknownVolume(blockdevice_id)
           
    def resize_volume(self, blockdevice_id, size):
        Message.new(Debug="coprhd resize_volume invoked").write(_logger)
        pass

    def detach_volume(self, blockdevice_id):
        """
        :param: volume id = blockdevice_id
        :raises: unknownvolume exception if not found
        """
        try:
         dataset_id = UUID(blockdevice_id[6:])
        except ValueError:
         raise UnknownVolume(blockdevice_id)
        volumesdetails = self.coprhdcli.get_volume_details("flocker-{}".format(dataset_id))
        if not volumesdetails:
         raise UnknownVolume(blockdevice_id)
        if volumesdetails[volumesdetails.keys()[0]]['attached_to'] is not None:
         Message.new(Info="coprhd detach_volume" + str(blockdevice_id)).write(_logger)
         dataset_id = UUID(blockdevice_id[6:])
         self.coprhdcli.unexport_volume("flocker-{}".format(dataset_id))
        else:
            Message.new(Info="Volume" + blockdevice_id + "not attached").write(_logger)
            raise UnattachedVolume(blockdevice_id)
               
    def list_volumes(self):
        """
        Return ``BlockDeviceVolume`` instances for all the files in the
        ``unattached`` directory and all per-host directories.

        See ``IBlockDeviceAPI.list_volumes`` for parameter and return type
        documentation.
        """
        volumes = []
        Message.new(Debug="coprhd list_volumes invoked").write(_logger)
        volumes_dict = self.coprhdcli.list_volume()
        if volumes_dict is None:
         return volumes
        for volume_name,volume_attr in volumes_dict.iteritems():
          attached_to = None
          if volume_attr['attached_to'] is None:
           Message.new(Debug="coprhd list_volumes attached None").write(_logger)
          else:
            attached_to = volume_attr['attached_to']
          size = Decimal(volume_attr['size'])
          size = 1073741824 * int(size)
          volume = BlockDeviceVolume(
                                    size=size, attached_to=attached_to,
                                    dataset_id=UUID(volume_name), blockdevice_id=u"block-{0}".format(volume_name)
                                    )
          volumes.append(volume)
        Message.new(Debug="coprhd list_volumes returning").write(_logger)
        return volumes
            

def configuration(coprhdhost, port, tenant,
                           project, varray, cookiedir, vpool,vpool_platinum,vpool_gold,vpool_silver,vpool_bronze,hostexportgroup,coprhdcli_security_file):
    """
    :return:CoprHDBlockDeviceAPI object
    """
    return CoprHDBlockDeviceAPI(
        coprhdcliconfig=CoprHDCLIDriver(coprhdhost, 
        port, tenant, 
        project, varray, cookiedir, vpool,vpool_platinum,vpool_gold,vpool_silver,vpool_bronze,hostexportgroup,coprhdcli_security_file),allocation_unit=1
    )
