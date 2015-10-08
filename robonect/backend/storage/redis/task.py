import asyncio
import codecs
import hashlib
import logging
import os
import pickle
import ujson


from sensors.settings import SETTINGS
from sensors.utils import datetime_to_timestamp
from storage.models import Task, SchedulerTaskHistory


__all__ = 'StorageException', 'TaskStorage'


class StorageException(Exception):

    def __init__(self, value, extra):
        self.value = value
        self.extra = extra

    def __str__(self):
        return repr(self.value)


class TaskStorage():

    def __init__(self, loop, connection):
        self.loop = loop
        self.log = logging.getLogger('storage.redis.config')
        self.connection = connection

        if self.connection:
            self.log.info('Storage connected')

    @asyncio.coroutine
    def create_task(self, name, task_type, run_at, ttl, kwargs, store_to):
        task_id = hashlib.md5(ujson.dumps([codecs.encode(os.urandom(16), 'hex_codec'),
                                           name, task_type, run_at, ttl, kwargs, store_to]).encode('utf-8')).hexdigest()
        if store_to == Task.STORE_TO_KEY:
            store_to = 'STORE_TO_KEY:' + SETTINGS.TASK_RESULTS_STORAGE_KEY.format(task_id)
        task = Task(id=task_id, name=name, type=task_type, kwargs=kwargs,
                    run_at=run_at, ttl=ttl, status=Task.SCHEDULED,
                    store_to=store_to)
        return task

    @asyncio.coroutine
    def schedule_task(self, task):
        self.log.info('Schedule task id={}, name={}, run_at={}'.format(task.id, task.name, task.run_at))
        # Create task
        yield from self.connection.set(SETTINGS.TASK_STORAGE_KEY.format(task.id).encode('utf-8'), task.serialize(), expire=SETTINGS.TASK_STORAGE_EXPIRE)
        # Add tasks to scheduled queue
        yield from self.connection.zadd(SETTINGS.SCHEDULED_QUEUE, {task.bid(): datetime_to_timestamp(task.run_at)})

    @asyncio.coroutine
    def create_scheduler_task_history(self, task, last_run, next_run, scheduled_task_id):
        obj = SchedulerTaskHistory(name=task.name, last_run=last_run, next_run=next_run, scheduled_task_id=scheduled_task_id)
        yield from self.connection.hset(SETTINGS.SCHEDULER_HISTORY_HASH, task.name.encode('utf-8'), obj.serialize())

    @asyncio.coroutine
    def lock_trigger(self, trigger_id):
        assert isinstance(trigger_id, str)
        return (yield from self.connection.hincrby(SETTINGS.TRIGGER_STATES, trigger_id.encode('utf-8'), 1))

    @asyncio.coroutine
    def unlock_trigger(self, trigger_id):
        assert isinstance(trigger_id, str)
        yield from self.connection.hset(SETTINGS.TRIGGER_STATES, trigger_id.encode('utf-8'), b'0')

    @asyncio.coroutine
    def get_metric_last_values(self, metric_ids):
        assert isinstance(metric_ids, (list, tuple, set))
        keys = list(metric_ids)
        values_obj = yield from self.connection.hmget_aslist(SETTINGS.LAST_VALUES_HASH, list(map(lambda m: str(m).encode('utf-8'), metric_ids)))

        values = None
        if values_obj:
            values = []
            for value in values_obj:
                try:
                    values.append(ujson.loads(value).get('value'))
                except:
                    values.append(None)

        if values and len(keys) == len(values):
            return dict(zip(keys, values))
        return dict(zip(keys, [None]*len(keys)))
