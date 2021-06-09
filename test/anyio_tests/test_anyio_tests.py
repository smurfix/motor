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

"""Test Motor's anyio test utilities."""

import anyio
import contextlib
import io
import os
import unittest
import concurrent.futures
import warnings

from test.anyio_tests import AnyIOTestCase, anyio_test


def run_test_case(case, suppress_output=True):
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(case)
    if suppress_output:
        stream = io.StringIO()
    else:
        stream = None

    runner = unittest.TextTestRunner(stream=stream)
    return runner.run(suite)


@contextlib.contextmanager
def set_environ(name, value):
    old_value = os.environ.get(name)
    os.environ[name] = value

    try:
        yield
    finally:
        if old_value is None:
            del os.environ[name]
        else:
            os.environ[name] = old_value


class TestAnyIOTests(unittest.TestCase):
    def test_basic(self):
        class Test(AnyIOTestCase):
            @anyio_test
            async def test(self):
                pass

        result = run_test_case(Test)
        self.assertEqual(1, result.testsRun)
        self.assertEqual(0, len(result.errors))

    def test_decorator_with_no_args(self):
        class TestPasses(AnyIOTestCase):
            @anyio_test
            async def test_decorated_with_no_args(self):
                pass

        result = run_test_case(TestPasses)
        self.assertEqual(0, len(result.errors))

        class TestFails(AnyIOTestCase):
            @anyio_test()
            async def test_decorated_with_no_args(self):
                self.fail()

        result = run_test_case(TestFails)
        self.assertEqual(1, len(result.failures))

    def test_timeout_passed_as_positional(self):
        with self.assertRaises(TypeError):
            class _(AnyIOTestCase):
                # Should be "timeout=10".
                @anyio_test(10)
                def test_decorated_with_no_args(self):
                    pass

    def test_timeout(self):
        class Test(AnyIOTestCase):
            @anyio_test(timeout=0.01)
            async def test_that_is_too_slow(self):
                await self.middle()

            async def middle(self):
                await self.inner()

            async def inner(self):
                await anyio.sleep(1)

        with set_environ('ASYNC_TEST_TIMEOUT', '0'):
            result = run_test_case(Test)

        self.assertEqual(1, len(result.errors))
        case, text = result.errors[0]
        self.assertTrue('TimeoutError' in text)

    def test_timeout_environment_variable(self):
        @anyio_test
        async def default_timeout(self):
            await anyio.sleep(0.1)

        with set_environ('ASYNC_TEST_TIMEOUT', '0.2'):
            # No error, sleeps for 0.1 seconds and the timeout is 0.2 seconds.
            default_timeout(self)

        @anyio_test(timeout=0.1)
        async def custom_timeout(self):
            await anyio.sleep(0.2)

        with set_environ('ASYNC_TEST_TIMEOUT', '0'):
            # No error, default timeout of 5 seconds overrides '0'.
            default_timeout(self)

        with set_environ('ASYNC_TEST_TIMEOUT', '0'):
            with self.assertRaises(TimeoutError):
                custom_timeout(self)

        with set_environ('ASYNC_TEST_TIMEOUT', '1'):
            # No error, 1-second timeout from environment overrides custom
            # timeout of 0.1 seconds.
            custom_timeout(self)

    def test_failure(self):
        class Test(AnyIOTestCase):
            @anyio_test
            async def test_that_fails(self):
                await self.middle()

            async def middle(self):
                await self.inner()

            async def inner(self):
                assert False, 'expected error'

        result = run_test_case(Test)
        self.assertEqual(1, len(result.failures))
        case, text = result.failures[0]
        self.assertFalse('CancelledError' in text)
        self.assertTrue('AssertionError' in text)
        self.assertTrue('expected error' in text)

        # The traceback shows where the coroutine raised.
        self.assertTrue('test_that_fails' in text)
        self.assertTrue('middle' in text)
        self.assertTrue('inner' in text)

    def test_undecorated(self):
        class Test(AnyIOTestCase):
            async def test_that_should_be_decorated(self):
                await anyio.sleep(0.01)

        with warnings.catch_warnings(record=True) as w:
            result = run_test_case(Test)
        self.assertEqual(1, len(result.errors))
        self.assertEqual(1, len(w))
        self.assertIn("was never awaited", str(w[0].message))
        case, text = result.errors[0]
        self.assertFalse('CancelledError' in text)
        self.assertTrue('TypeError' in text)
        self.assertTrue('should be decorated with @anyio_test' in text)

    def test_other_return(self):
        class Test(AnyIOTestCase):
            def test_other_return(self):
                return 42

        result = run_test_case(Test)
        self.assertEqual(len(result.errors), 1)
        case, text = result.errors[0]
        self.assertIn('Return value from test method ignored', text)


if __name__ == '__main__':
    unittest.main()
