# Copyright 2014 MongoDB, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Test replica set AnyIOClient."""

import unittest

import pymongo
import pymongo.errors
import pymongo.mongo_replica_set_client

import test
from motor import motor_anyio
from test import env, SkipTest
from test.anyio_tests import AnyIOTestCase, anyio_test
from test.test_environment import env


class TestAnyIOReplicaSet(AnyIOTestCase):
    def setUp(self):
        if not test.env.is_replica_set:
            raise SkipTest('Not connected to a replica set')

        super().setUp()

    @anyio_test
    async def test_connection_failure(self):
        # Assuming there isn't anything actually running on this port.
        client = motor_anyio.AnyIOMotorClient(
            'localhost:8765', replicaSet='rs', io_loop=self.loop,
            serverSelectionTimeoutMS=10)

        with self.assertRaises(pymongo.errors.ConnectionFailure):
            await client.admin.command('ismaster')


class TestReplicaSetClientAgainstStandalone(AnyIOTestCase):
    """This is a funny beast -- we want to run tests for a replica set
    AnyIOMotorClient but only if the database at DB_IP and DB_PORT is a
    standalone.
    """
    def setUp(self):
        super().setUp()
        if test.env.is_replica_set:
            raise SkipTest(
                "Connected to a replica set, not a standalone mongod")

    @anyio_test
    async def test_connect(self):
        client = motor_anyio.AnyIOMotorClient(
            '%s:%s' % (env.host, env.port), replicaSet='anything',
            serverSelectionTimeoutMS=10, io_loop=self.loop)

        with self.assertRaises(pymongo.errors.ServerSelectionTimeoutError):
            await client.test.test.find_one()


if __name__ == '__main__':
    unittest.main()
