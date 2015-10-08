import asyncio
import logging
import unittest

from collections import Sequence, Iterable, Iterator
from functools import wraps


logging.disable(logging.CRITICAL)


def async(function):
    """
    Wraps the coroutine inside `run_until_complete`.
    """
    function = asyncio.coroutine(function)

    @wraps(function)
    def wrapper(self, *args, **kwargs):
        @asyncio.coroutine
        def c():
            # Run test
            yield from function(self, *args, **kwargs)
        self.loop.run_until_complete(c())
    return wrapper


def mock_coroutine(vals=True):
    if isinstance(vals, (Sequence, Iterable)):
        vals_it = iter(vals)
    elif isinstance(vals, Iterator):
        vals_it = vals
    else:
        vals_it = None

    @asyncio.coroutine
    def co(*args, **kwargs):
        if vals_it:
            return next(vals_it)
        return vals
    return co


class AsyncTestCase(unittest.TestCase):

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()
