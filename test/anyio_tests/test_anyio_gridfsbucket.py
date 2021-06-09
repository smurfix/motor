# -*- coding: utf-8 -*-
# Copyright 2016 MongoDB, Inc.
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

"""Test AnyIOMotorGridFSBucket."""

import anyio
from io import BytesIO

from gridfs.errors import NoFile
from pymongo.write_concern import WriteConcern
from pymongo.read_preferences import ReadPreference
from motor.motor_anyio import AnyIOMotorGridFSBucket
from test.anyio_tests import AnyIOTestCase, anyio_test
from test.utils import ignore_deprecations
from motor.frameworks.anyio import Session


class TestAnyIOGridFSBucket(AnyIOTestCase):
    async def _reset(self):
        async with Session():
            await self.db.drop_collection("fs.files")
            await self.db.drop_collection("fs.chunks")
            await self.db.drop_collection("alt.files")
            await self.db.drop_collection("alt.chunks")

    def setUp(self):
        super().setUp()
        anyio.run(self._reset, backend="trio")
        self.bucket = AnyIOMotorGridFSBucket(self.db)

    def tearDown(self):
        anyio.run(self._reset, backend="trio")
        super().tearDown()

    @anyio_test
    async def test_basic(self):
        oid = await self.bucket.upload_from_stream("test_filename",
                                                        b"hello world")
        gout = await self.bucket.open_download_stream(oid)
        self.assertEqual(b"hello world", (await gout.read()))
        self.assertEqual(1, (await self.db.fs.files.count_documents({})))
        self.assertEqual(1, (await self.db.fs.chunks.count_documents({})))

        dst = BytesIO()
        await self.bucket.download_to_stream(gout._id, dst)
        self.assertEqual(b"hello world", dst.getvalue())

        await self.bucket.delete(oid)
        with self.assertRaises(NoFile):
            await self.bucket.open_download_stream(oid)
        self.assertEqual(0, (await self.db.fs.files.count_documents({})))
        self.assertEqual(0, (await self.db.fs.chunks.count_documents({})))

    def test_init(self):
        name = 'bucket'
        wc = WriteConcern(w='majority', wtimeout=1000)
        rp = ReadPreference.SECONDARY
        size = 8
        bucket = AnyIOMotorGridFSBucket(
            self.db, name, disable_md5=True, chunk_size_bytes=size,
            write_concern=wc, read_preference=rp)
        self.assertEqual(name, bucket.collection.name)
        self.assertEqual(wc, bucket.collection.write_concern)
        self.assertEqual(rp, bucket.collection.read_preference)
        self.assertEqual(wc, bucket.delegate._chunks.write_concern)
        self.assertEqual(rp, bucket.delegate._chunks.read_preference)
        self.assertEqual(size, bucket.delegate._chunk_size_bytes)

    @ignore_deprecations
    def test_collection_param(self):
        bucket = AnyIOMotorGridFSBucket(self.db, collection='collection')
        self.assertEqual('collection', bucket.collection.name)
