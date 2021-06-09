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

"""Utilities for testing Motor with anyio."""

import anyio
import functools
import gc
import inspect
import unittest
import warnings
from unittest import SkipTest

from mockupdb import MockupDB

from motor import motor_anyio
from motor.frameworks.anyio import Session, as_future
from test.assert_logs_backport import AssertLogsMixin
from test.test_environment import env, CA_PEM, CLIENT_PEM
from test.utils import get_async_test_timeout


class _TestMethodWrapper(object):
    """Wraps a test method to raise an error if it returns a value.

    This is mainly used to detect undecorated generators (if a test
    method yields it must use a decorator to consume the generator),
    but will also detect other kinds of return values (these are not
    necessarily errors, but we alert anyway since there is no good
    reason to return a value from a test).

    Adapted from Tornado's test framework.
    """
    def __init__(self, orig_method):
        self.orig_method = orig_method

    def __call__(self):
        result = self.orig_method()
        if inspect.iscoroutine(result):
            # Cancel the undecorated task to avoid this warning:
            # RuntimeWarning: coroutine 'test_foo' was never awaited
            raise TypeError("Generator test methods should be decorated with "
                            "@anyio_test")
        elif result is not None:
            raise ValueError("Return value from test method ignored: %r" %
                             result)

    def __getattr__(self, name):
        """Proxy all unknown attributes to the original method.

        This is important for some of the decorators in the `unittest`
        module, such as `unittest.skipIf`.
        """
        return getattr(self.orig_method, name)


class AnyIOTestCase(AssertLogsMixin, unittest.TestCase):
    longMessage = True  # Used by unittest.TestCase
    ssl = False  # If True, connect with SSL, skip if mongod isn't SSL

    def __init__(self, methodName='runTest'):
        super().__init__(methodName)

        # It's easy to forget the @anyio_test decorator, but if you do
        # the test will silently be ignored because nothing will consume
        # the generator. Replace the test method with a wrapper that will
        # make sure it's not an undecorated generator.
        # (Adapted from Tornado's AsyncTestCase.)
        setattr(self, methodName, _TestMethodWrapper(
            getattr(self, methodName)))

    def setUp(self):
        self.loop = None  # idiots
        super().setUp()

        # Ensure that the event loop is passed explicitly in Motor.
        if self.ssl and not env.mongod_started_with_ssl:
            raise SkipTest("mongod doesn't support SSL, or is down")

        self.cx = self.anyio_client()
        self.db = self.cx.motor_test
        self.collection = self.db.test_collection
        anyio.run(self.collection.drop, backend="trio")

    def get_client_kwargs(self, **kwargs):
        if env.mongod_started_with_ssl:
            kwargs.setdefault('tlsCAFile', CA_PEM)
            kwargs.setdefault('tlsCertificateKeyFile', CLIENT_PEM)

        kwargs.setdefault('tls', env.mongod_started_with_ssl)
        kwargs.setdefault('io_loop', None)

        return kwargs

    def anyio_client(self, uri=None, *args, **kwargs):
        """Get an AnyIOMotorClient.

        Ignores self.ssl, you must pass 'ssl' argument.
        """
        return motor_anyio.AnyIOMotorClient(
            uri or env.uri,
            *args,
            **self.get_client_kwargs(**kwargs))

    def anyio_rsc(self, uri=None, *args, **kwargs):
        """Get an open MotorClient for replica set.

        Ignores self.ssl, you must pass 'ssl' argument.
        """
        return motor_anyio.AnyIOMotorClient(
            uri or env.rs_uri,
            *args,
            **self.get_client_kwargs(**kwargs))

    async def make_test_data(self):
        await self.collection.delete_many({})
        await self.collection.insert_many([{'_id': i} for i in range(200)])

    make_test_data.__test__ = False

    def tearDown(self):
        self.cx.close()
        gc.collect()


class AnyIOMockServerTestCase(AnyIOTestCase):
    def server(self, *args, **kwargs):
        server = MockupDB(*args, **kwargs)
        server.run()
        self.addCleanup(server.stop)
        return server

    def client_server(self, *args, **kwargs):
        server = self.server(*args, **kwargs)
        client = motor_anyio.AnyIOMotorClient(server.uri, io_loop=self.loop)
        self.addCleanup(client.close)

        return client, server

    async def run_thread(self, fn, *args, **kwargs):
        return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))

    def fetch_next(self, cursor):
        async def fetch_next():
            with warnings.catch_warnings(record=True):
                return await cursor.fetch_next

        return as_future(fetch_next)


# TODO: Spin off to a PyPI package.
def anyio_test(func=None, timeout=None, session=False):
    """Decorator for coroutine methods of AnyIOTestCase::

        class MyTestCase(AnyIOTestCase):
            @anyio_test
            def test(self):
                # Your test code here....
                pass

    Default timeout is 5 seconds. Override like::

        class MyTestCase(AnyIOTestCase):
            @anyio_test(timeout=10)
            def test(self):
                # Your test code here....
                pass

    You can also set the ASYNC_TEST_TIMEOUT environment variable to a number
    of seconds. The final timeout is the ASYNC_TEST_TIMEOUT or the timeout
    in the test (5 seconds or the passed-in timeout), whichever is longest.
    """
    def wrap(f):
        @functools.wraps(f)
        def wrapped(self, *args, **kwargs):
            if timeout is None:
                actual_timeout = get_async_test_timeout()
            else:
                actual_timeout = get_async_test_timeout(timeout)

            async def runner():
                with anyio.fail_after(actual_timeout):
                    if session:
                        async with Session():
                            await f(self, *args, **kwargs)
                    else:
                        await f(self, *args, **kwargs)

            anyio.run(runner, backend="trio")

        return wrapped

    if func is not None:
        # Used like:
        #     @gen_test
        #     def f(self):
        #         pass
        if not inspect.isfunction(func):
            msg = ("%r is not a test method. Pass a timeout as"
                   " a keyword argument, like @anyio_test(timeout=7)")
            raise TypeError(msg % func)
        return wrap(func)
    else:
        # Used like @gen_test(timeout=10)
        return wrap


async def get_command_line(client):
    command_line = await client.admin.command('getCmdLineOpts')
    assert command_line['ok'] == 1, "getCmdLineOpts() failed"
    return command_line


async def server_is_mongos(client):
    ismaster_response = await client.admin.command('ismaster')
    return ismaster_response.get('msg') == 'isdbgrid'


async def skip_if_mongos(client):
    is_mongos = await server_is_mongos(client)
    if is_mongos:
        raise unittest.SkipTest("connected to mongos")


async def remove_all_users(db):
    await db.command({"dropAllUsersFromDatabase": 1})
