import asyncio
import asyncio_redis
import mock
import pickle
import unittest
import ujson

from storage.redis import TaskStorage
from sensors.tests.base import AsyncTestCase, async, mock_coroutine
from sensors.settings import SETTINGS


class RedisTaskStorageTestCase(AsyncTestCase):

    def setUp(self):
        super(RedisTaskStorageTestCase, self).setUp()

    @async
    def test_get_metric_last_values(self):
        connection = yield from asyncio_redis.Pool.create(host='localhost', port=6379, db=2, encoder=asyncio_redis.encoders.BytesEncoder(), poolsize=3)
        yield from connection.flushdb()
        tq_storage = TaskStorage(self.loop, connection)


        yield from connection.hset(SETTINGS.LAST_VALUES_HASH, 'M1'.encode('utf-8'), ujson.dumps({'value': 36.6, 'timestamp': 1}).encode('utf-8'))
        values = yield from tq_storage.get_metric_last_values(['M1'])
        self.assertDictEqual(values, {'M1': 36.6})

        yield from connection.hset(SETTINGS.LAST_VALUES_HASH, 'M2'.encode('utf-8'), ujson.dumps({'value': True, 'timestamp': 2}).encode('utf-8'))
        values = yield from tq_storage.get_metric_last_values(['M1', 'M2'])
        self.assertDictEqual(values, {'M1': 36.6, 'M2': True})

        yield from connection.hset(SETTINGS.LAST_VALUES_HASH, 'M3'.encode('utf-8'), 'wrong bytes'.encode('utf-8'))
        values = yield from tq_storage.get_metric_last_values(['M1', 'M2', 'M3'])
        self.assertDictEqual(values, {'M1': 36.6, 'M2': True, 'M3': None})

        values = yield from tq_storage.get_metric_last_values(['X1', 'M2', 'X3'])
        self.assertDictEqual(values, {'X1': None, 'M2': True, 'X3': None})

    @async
    def test_lock_trigger(self):
        connection = yield from asyncio_redis.Pool.create(host='localhost', port=6379, db=2, encoder=asyncio_redis.encoders.BytesEncoder(), poolsize=3)
        yield from connection.flushdb()
        tq_storage = TaskStorage(self.loop, connection)
        value = yield from tq_storage.lock_trigger('T1')
        self.assertEquals(value, 1)
        value = yield from tq_storage.lock_trigger('T1')
        self.assertEquals(value, 2)
        value = yield from tq_storage.lock_trigger('T1')
        self.assertEquals(value, 3)

    @async
    def test_unlock_trigger(self):
        connection = yield from asyncio_redis.Pool.create(host='localhost', port=6379, db=2, encoder=asyncio_redis.encoders.BytesEncoder(), poolsize=3)
        yield from connection.flushdb()
        tq_storage = TaskStorage(self.loop, connection)
        value = yield from tq_storage.lock_trigger('T2')
        value = yield from tq_storage.lock_trigger('T2')
        value = yield from tq_storage.lock_trigger('T2')
        self.assertEquals(value, 3)

        yield from tq_storage.unlock_trigger('T2')
        value = yield from connection.hget(SETTINGS.TRIGGER_STATES, 'T2'.encode('utf-8'))
        self.assertEquals(value, b'0')

        value = yield from tq_storage.lock_trigger('T2')
        self.assertEquals(value, 1)
