# Copyright 2014-2016 MongoDB, Inc.
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

"""anyio compatibility layer for Motor, an asynchronous MongoDB driver.

See "Frameworks" in the Developer Guide.
"""


import anyio
import multiprocessing
import os
import warnings
import contextvars
import outcome
from contextlib import asynccontextmanager
from functools import wraps, partial
from inspect import iscoroutine

CLASS_PREFIX = 'AnyIO'


call_later = contextvars.ContextVar("call_later", default=None)
session_tg = contextvars.ContextVar("session_tg", default=None)

@asynccontextmanager
async def Session(client=None):
    async with anyio.create_task_group() as tg:
        wrq, rdq = anyio.create_memory_object_stream(999)
        tcl = call_later.set(wrq)
        ttg = session_tg.set(tg)
        tg.start_soon(_call_later, tg, rdq)

        try:
            yield client
        finally:
            evt = anyio.Event()
            await wrq.send((evt.set,None))
            await wrq.aclose()
            with anyio.move_on_after(1):
                await evt.wait()

            call_later.reset(tcl)
            session_tg.reset(ttg)
            tg.cancel_scope.cancel()


async def _call_later(tg, rdq):
    """
    """
    async for cb, ctx in rdq:
        async def _call(cb):
            # Wrapper: the context must stay established during the `await`
            res = cb()
            if iscoroutine(res):
                res = await res
            return res
        if ctx is None:
            tg.start_soon(_call, cb)
        else:
            tg.start_soon(ctx.run, _call, cb)

def as_future(proc, *a, **k):
    async def _run(f,proc,a,k):
        try:
            res = await proc(*a,**k)
        except Exception as exc:
            f.set_exception(exc)
        except BaseException as exc:
            f.set_exception(FutureCancelled())
            raise
        else:
            f.set_result(res)

    f = Future()
    session_tg.get().start_soon(_run,f,proc,a,k)
    return f


class FutureCancelled(Exception):
    pass


class Future:
    """
    A somewhat-asyncio-compatible but severely mangled Future class.
    """
    def __init__(self):
        self.event = anyio.Event()
        self._res = None
        self._exc = None
        self._callbacks = []

    def __await__(self):
        # *sigh*
        async def _waiter():
            await self.event.wait()
            return self.result()
        return _waiter().__await__()

    def is_set(self):
        return self.event.is_set()

    def result(self):
        """
        Get the result.
        """
        if not self.is_set():
            raise RuntimeError("not set")
        if self._exc is not None:
            exc, self._exc = self._exc, RuntimeError("duplicate %r" % (self._exc,))
            raise exc
        return self._res

    def exception(self):
        """
        Get the exception.
        """
        if not self.is_set():
            raise RuntimeError("not set")
        return self._exc

    def set_result(self, value):
        if self.event.is_set():
            raise RuntimeError("future already set")
        self._res = value
        self.event.set()
        call_later.get().send_nowait((self._run_callbacks, None))

    def set_exception(self, exc):
        if self.event.is_set():
            raise RuntimeError("future already set")
        if isinstance(exc, type):
            exc = exc()
        self._exc = exc
        self.event.set()
        call_later.get().send_nowait((self._run_callbacks, None))

    def _run_callbacks(self, _=None):
        while self._callbacks:
            fn,ctx = self._callbacks.pop(0)
            call_later.get().send_nowait((partial(fn,self), ctx))

    def cancel(self):
        try:
            raise FutureCancelled()
        except FutureCancelled as exc:
            self.set_exception(exc)

    def done(self):
        return self.event.is_set()

    def add_done_callback(self, fn, *, context=None):
        if context is None:
            context = contextvars.copy_context()
        if self.event.is_set():
            call_later.get().send_nowait((partial(fn,self), context))
        else:
            self._callbacks.append((fn, context))


def get_event_loop():
    return None


def is_event_loop(loop):
    return loop is None


def check_event_loop(loop):
    if not is_event_loop(loop):
        raise TypeError(
            "io_loop must be instance of asyncio-compatible event loop,"
            "not %r" % loop)


def get_future(loop):
    return Future()


if 'MOTOR_MAX_WORKERS' in os.environ:
    max_workers = int(os.environ['MOTOR_MAX_WORKERS'])
else:
    max_workers = multiprocessing.cpu_count() * 5

_sema = None

def run_on_executor(loop, fn, *args, **kwargs):
    if contextvars:
        context = contextvars.copy_context()
        fn = partial(context.run, fn)

    global _sema
    if _sema is None:
        _sema = anyio.Semaphore(max_workers)

    async def _run(fn, args, kwargs):
        async with _sema:
            return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs))

    return as_future(_run, fn, args, kwargs)

# Adapted from tornado.gen.
def chain_future(a, b):
    def copy(future):
        assert future is a
        if b.done():
            return
        if a.exception() is not None:
            b.set_exception(a.exception())
        else:
            b.set_result(a.result())

    a.add_done_callback(copy)


def chain_return_value(future, loop, return_value):
    """Compatible way to return a value in all Pythons.

    PEP 479, raise StopIteration(value) from a coroutine won't work forever,
    but "return value" doesn't work in Python 2. Instead, Motor methods that
    return values resolve a Future with it, and are implemented with callbacks
    rather than a coroutine internally.
    """
    chained = Future()

    def copy(_future):
        # Return early if the task was cancelled.
        if chained.done():
            return
        if _future.exception() is not None:
            chained.set_exception(_future.exception())
        else:
            chained.set_result(return_value)

    future.add_done_callback(copy)
    return chained


def call_soon(loop, callback, *args, **kwargs):
    context = contextvars.copy_context()
    call_later.get().send_nowait((partial(callback, *args, **kwargs), context))


def add_future(loop, future, callback, *args):
    future.add_done_callback(partial(callback, *args))


def pymongo_class_wrapper(f, pymongo_class):
    """Executes the coroutine f and wraps its result in a Motor class.

    See WrapAsync.
    """
    @wraps(f)
    async def _wrapper(self, *args, **kwargs):
        result = await f(self, *args, **kwargs)

        # Don't call isinstance(), not checking subclasses.
        if result.__class__ is pymongo_class:
            # Delegate to the current object to wrap the result.
            return self.wrap(result)
        else:
            return result

    return _wrapper


def platform_info():
    return 'anyio'
