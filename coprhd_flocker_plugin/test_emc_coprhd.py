# Copyright Hybrid Logic Ltd.
# Copyright 2015 EMC Corporation
# See LICENSE file for details.

"""
Functional tests for
``flocker.node.agents.blockdevice.CoprHDBlockDeviceAPI``
"""

import os
import socket
from uuid import uuid4

import functools

COPRHD_ALLOCATION_UNIT = int(1073741824)

from twisted.trial.unittest import SynchronousTestCase, SkipTest

from flocker.node.agents.test.test_blockdevice import make_iblockdeviceapi_tests

from testtools_emc_coprhd import (
    tidy_coprhd_client_for_test
)


def emccoprhdblockdeviceapi_for_test(test_case):
    """
    Create a ``CoprHDBlockDeviceAPI`` instance for use in tests.
    :returns: A ``CoprHDBlockDeviceAPI`` instance
    """
    user_id = os.getuid()
    if user_id != 0:
        raise SkipTest(
            "``CoprHDBlockDeviceAPI`` queries for iSCSI initiator name which is owned by root, "
            "Required UID: 0, Found UID: {!r}".format(user_id)
        )
    coprhd = tidy_coprhd_client_for_test(test_case)
    return coprhd


class CoprHDBlockDeviceAPIInterfaceTests(
    make_iblockdeviceapi_tests(
        blockdevice_api_factory=functools.partial(emccoprhdblockdeviceapi_for_test),
        minimum_allocatable_size=COPRHD_ALLOCATION_UNIT,
        device_allocation_unit=None,
        unknown_blockdevice_id_factory=lambda test: u"vol-00000000"
    )
):

    """
	Interface adherence Tests for ``CoprHDBlockDeviceAPI``
    """