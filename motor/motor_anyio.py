# Copyright 2011-2015 MongoDB, Inc.
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

"""AnyIO support for Motor, an asynchronous driver for MongoDB."""

from . import core, motor_gridfs
from .frameworks import anyio as anyio_framework
from .metaprogramming import create_class_with_framework

__all__ = ['AnyIOMotorClient','AnyIOMotorClientEncryption']


def create_anyio_class(cls):
    return create_class_with_framework(cls, anyio_framework,
                                       'motor.motor_anyio')


AnyIOMotorClient = create_anyio_class(core.AgnosticClient)


AnyIOMotorClientSession = create_anyio_class(core.AgnosticClientSession)


AnyIOMotorDatabase = create_anyio_class(
    core.AgnosticDatabase)


AnyIOMotorCollection = create_anyio_class(
    core.AgnosticCollection)


AnyIOMotorCursor = create_anyio_class(
    core.AgnosticCursor)


AnyIOMotorCommandCursor = create_anyio_class(
    core.AgnosticCommandCursor)


AnyIOMotorLatentCommandCursor = create_anyio_class(
    core.AgnosticLatentCommandCursor)


AnyIOMotorChangeStream = create_anyio_class(
    core.AgnosticChangeStream)


AnyIOMotorGridFSBucket = create_anyio_class(
    motor_gridfs.AgnosticGridFSBucket)


AnyIOMotorGridIn = create_anyio_class(
    motor_gridfs.AgnosticGridIn)


AnyIOMotorGridOut = create_anyio_class(
    motor_gridfs.AgnosticGridOut)


AnyIOMotorGridOutCursor = create_anyio_class(
    motor_gridfs.AgnosticGridOutCursor)


AnyIOMotorClientEncryption = create_anyio_class(
    core.AgnosticClientEncryption)
