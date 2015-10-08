import asyncio
import asyncio_redis
import codecs
import hashlib
import logging
import os
import pickle
import time
import signal
import ujson

from collections import defaultdict, OrderedDict
from functools import partial

from sensors.utils import (datetime_to_timestamp, timestamp_to_datetime, now,
                           parse_timetable)
from sensors.settings import SETTINGS

from storage.models import Task, SchedulerTaskHistory
from storage.redis import ConfigStorage, TaskStorage

logging.basicConfig()
log = logging.getLogger('taskqueue.scheduler')


class Scheduler(object):

    def __init__(self):
        self.current_loop = None
        self.connection = None

        self.run = True

        self.subscription = None
        self.sleep_task = None

        self.config_version = 0
        self.scheduler_tasks = dict()
        self.scheduler_tasks_history = defaultdict(dict)

        self._ttl_check_last_run = 0
        self._ttl_reload_config_last_run = 0

        self.config = ConfigStorage()
        self.tq_storage = None

    def install_bootstrap(self):
        try:
            # Check is it already installed
            objects = OrderedDict()
            for key in reversed(SETTINGS.BOOTSTRAP_TYPES):
                objects[key] = self.config.get_config(key)

            # Collect all bootstrap objects
            any_objects = False
            bootstrap_objects = []
            for key, items in objects.items():
                for item in items:
                    any_objects = True
                    if item.get('bootstrap'):
                        bootstrap_objects.append( (key, item) )

            if any_objects:
                if not bootstrap_objects:
                    # There are no bootstrap objects -- clean db, it's very old db
                    log.info("Bootstrap install: remove all objects in db, it's very old db")
                    for key in reversed(SETTINGS.BOOTSTRAP_TYPES):
                        self.config.del_config(key)
                else:
                    # We should remove only bootstrap objects
                    log.info('Bootstrap install: remove {} old bootstrap objects in db'.format(len(bootstrap_objects)))
                    for key, obj in bootstrap_objects:
                        self.config.del_object(key, obj['_id'])

            # Install bootstrap update
            filename = os.path.join(SETTINGS.BASE_DIR, SETTINGS.BOOTSTRAP_FILE)
            bootstrap = ujson.load(open(filename, 'br'))
            log.info("Install new bootstrap objects")
            for key, objects in ( (key, bootstrap.get(key.capitalize(), [])) for key in SETTINGS.BOOTSTRAP_TYPES ):
                for obj in objects:
                    obj['bootstrap'] = True
                    self.config.add_object(key, obj)

            if not self.config.connection.get(SETTINGS.DEVCONFIG):
                self.config.connection.set(SETTINGS.DEVCONFIG, ujson.dumps(SETTINGS.DEVCONFIG_DATA))
            log.info("Install bootstrap objects finished")
        except:
            log.error("Failed to install bootstrap", exc_info=True)

    @asyncio.coroutine
    def schedule_task(self, name, task_type, run_at, ttl, kwargs):
        """ Create Task object and add to Scheduled queue """
        # Create and store Task object
        task = yield from self.tq_storage.create_task(name, task_type,
                                                      run_at, ttl, kwargs,
                                                      store_to=Task.STORE_TO_METRICS)

        yield from self.tq_storage.schedule_task(task)

        # Store next_run and scheduled_task_id in TaskHistory
        task = yield from self.tq_storage.create_scheduler_task_history(task,
                                                                        last_run=self.scheduler_tasks_history.get(task.name).get('last_run', 0),
                                                                        next_run=datetime_to_timestamp(run_at),
                                                                        scheduled_task_id=task.id)

    @asyncio.coroutine
    def _reload_config_tasks_list(self):
        """ Load list of tasks, details """
        time_now = int(now())
        if time_now - self._ttl_reload_config_last_run < 1000:  # 1000 = 1sec
            return
        self._ttl_reload_config_last_run = time_now

        config_version = self.config.get_config_version()
        if config_version != self.config_version:
            log.info('Changes in actions list, update.')
            new_scheduler_tasks = self.config.get_scheduled_actions()
            new_keys = set(new_scheduler_tasks.keys()) - set(self.scheduler_tasks.keys())
            deleted_keys = set(self.scheduler_tasks.keys()) - set(new_scheduler_tasks.keys())
            if new_keys or deleted_keys:
                log.info('New actions list, new_keys={}, deleted_keys={}'.format(new_keys, deleted_keys))
            self.scheduler_tasks = new_scheduler_tasks

            yield from self._load_scheduler_tasks_history()
            # Check scheduler_tasks_history here, please
            # Возможно, интервал запуска изменился с длинного на короткий
            # А у нас уже next_run стоит далеко в будущем
            for scheduled_task_name, scheduled_task_history in self.scheduler_tasks_history.items():
                # Смотри все таски, для которых сохранена инфорамция по шедулингу
                if scheduled_task_history.get('next_run', 0):  # and (scheduled_task_name in self.scheduler_tasks):
                    # Если есть запланированный таск
                    if scheduled_task_name in self.scheduler_tasks:
                        # Если у таска осталось расписание
                        possible_next_run = datetime_to_timestamp(self._get_next_run_time(scheduled_task_name, self.scheduler_tasks[scheduled_task_name], int(now())))
                    else:
                        # У таска не осталось расписания, next_run надо привести к 0 и больше ничего не делать
                        possible_next_run = 0

                    if scheduled_task_history.get('next_run', 0) != possible_next_run:
                        # Cancel scheduled task
                        # Reset next_run
                        task_id = scheduled_task_history.get('scheduled_task_id')
                        log.info('Schedule changed for task with id={}, name={}, reschedule next_task'.format(task_id, scheduled_task_name))
                        key = SETTINGS.TASK_STORAGE_KEY.format(task_id).encode('utf-8')
                        task_obj = yield from self.connection.delete([key])

                        scheduled_task_history['next_run'] = 0
                        scheduled_task_history['scheduled_task_id'] = 0

                        try:
                            task_scheduler_obj = yield from self.connection.hget(SETTINGS.SCHEDULER_HISTORY_HASH, scheduled_task_name.encode('utf-8'))
                            task_scheduler = SchedulerTaskHistory.deserialize(task_scheduler_obj)
                            task_scheduler = task_scheduler._replace(next_run=0, scheduled_task_id=None)
                            yield from self.connection.hset(SETTINGS.SCHEDULER_HISTORY_HASH, task_scheduler.name.encode('utf-8'), task_scheduler.serialize())
                        except:
                            log.error('Broken SchedulerTaskHistory object for task id={}, delete it'.format(scheduled_task_name))
                            yield from self.connection.hdel(SETTINGS.SCHEDULER_HISTORY_HASH, task_scheduler.name.encode('utf-8'))

            # Удалился какой-то таск? Удалим его из мониторинга выполнения
            for key in deleted_keys:
                if key in self.scheduler_tasks_history:
                    del self.scheduler_tasks_history[key]
            self.config_version = config_version


    @asyncio.coroutine
    def _load_scheduler_tasks_history(self):
        """ Load list of scheduled tasks tasks run times """
        # Load run history for scheduled tasks
        tasks_history = yield from self.connection.hgetall(SETTINGS.SCHEDULER_HISTORY_HASH)
        new_keys = set()
        for f in tasks_history:
            key, value = yield from f
            key = key.decode('utf-8')
            new_keys.add(key)
            # Iterate over all tasks in history
            if key in self.scheduler_tasks:
                # Is task still in crontab?
                # Deserialize
                try:
                    task_history = SchedulerTaskHistory.deserialize(value)
                except (pickle.UnpicklingError, EOFError, TypeError, ImportError):
                    log.error('Cannot deserialize SchedulerTaskHistory for {}'.format(key), exc_info=True)
                    continue
                self.scheduler_tasks_history[key].update(dict(last_run=task_history.last_run,
                                                      next_run=task_history.next_run,
                                                      scheduled_task_id=task_history.scheduled_task_id))
        for key in set(self.scheduler_tasks_history.keys()) - new_keys:
            del self.scheduler_tasks_history[key]

    def _get_next_run_time(self, scheduler_task_name, scheduler_task, current_time):
        interval = parse_timetable(scheduler_task['schedule'])
        if not interval:
            return timestamp_to_datetime(0)

        scheduled_task_history = self.scheduler_tasks_history[scheduler_task_name]
        next_run = scheduled_task_history.get('last_run', 0) + interval
        return timestamp_to_datetime(next_run if next_run > current_time else current_time)

    @asyncio.coroutine
    def _check_expired_tasks(self):
        time_now = int(now())
        if time_now - self._ttl_check_last_run < 1000:  # 1000 = 1sec
            return
        self._ttl_check_last_run = time_now

        TTL = SETTINGS.WORKER_TASK_TIMEOUT * 1000
        for scheduled_task_name, scheduled_task_history in self.scheduler_tasks_history.items():
            scheduled_task = self.scheduler_tasks.get(scheduled_task_name)
            if (scheduled_task_history.get('next_run')
              and scheduled_task_history.get('scheduled_task_id')
              and (time_now - scheduled_task_history.get('next_run')) > (scheduled_task.get('ttl') or SETTINGS.WORKER_TASK_TIMEOUT)*1000):
                task_id = scheduled_task_history.get('scheduled_task_id')
                log.info('Fix broken task id={}, name={}'.format(task_id, scheduled_task_name))
                # Get task object from redis key
                key = SETTINGS.TASK_STORAGE_KEY.format(scheduled_task_history.get('scheduled_task_id')).encode('utf-8')
                task_obj = yield from self.connection.get(key)
                # Deserialize task object
                try:
                    if not task_obj:
                        raise TypeError()
                    task = Task.deserialize(task_obj)
                    if task.status != Task.SUCCESSFUL:
                        # Update task object status
                        task = task._replace(status=Task.FAILED)
                        # Set new status to redis
                        yield from self.connection.set(key, task.serialize(), expire=SETTINGS.TASK_STORAGE_EXPIRE)
                except TypeError as ex:
                    task = None
                    log.error("Wrong task id={}".format(scheduled_task_history.get('scheduled_task_id')), exc_info=True)
                    yield from self.connection.delete([key])

                # Publish message about finish (FAILED)
                if task:
                    yield from self.connection.publish(SETTINGS.TASK_CHANNEL.format(task_id).encode('utf-8'), task.status.encode('utf-8'))
                else:
                    yield from self.connection.publish(SETTINGS.TASK_CHANNEL.format(task_id).encode('utf-8'), Task.FAILED.encode('utf-8'))

                # Update scheduler information
                # Store next_run in scheduled
                try:
                    task_scheduler_obj = yield from self.connection.hget(SETTINGS.SCHEDULER_HISTORY_HASH, scheduled_task_name.encode('utf-8'))
                    task_scheduler = SchedulerTaskHistory.deserialize(task_scheduler_obj)
                    if task and task.status == Task.SUCCESSFUL:
                        scheduled_task_history['last_run'] = scheduled_task_history.get('next_run', 0)
                        scheduled_task_history['next_run'] = 0
                        task_scheduler = task_scheduler._replace(last_run=task_scheduler.next_run, next_run=0, scheduled_task_id=None)
                    else:
                        scheduled_task_history['next_run'] = 0
                        scheduled_task_history['scheduled_task_id'] = None
                        task_scheduler = task_scheduler._replace(next_run=0, scheduled_task_id=None)
                    yield from self.connection.hset(SETTINGS.SCHEDULER_HISTORY_HASH, task_scheduler.name.encode('utf-8'), task_scheduler.serialize())
                except:
                    # We lost SCHEDULER_HISTORY_HASH in db
                    if task and task.status == Task.SUCCESSFUL:
                        scheduled_task_history['last_run'] = scheduled_task_history.get('next_run', 0)
                        scheduled_task_history['next_run'] = 0
                    else:
                        scheduled_task_history['next_run'] = 0
                        scheduled_task_history['scheduled_task_id'] = None

    @asyncio.coroutine
    def _ping_disptacher(self):
        # Publish message about new scheduled task
        yield from self.connection.publish(SETTINGS.SCHEDULER_TO_DISPATCHER_CHANNEL, b'')

    @asyncio.coroutine
    def sleep(self):
        try:
            reply = yield from self.subscription.next_published()
        except GeneratorExit:
            log.info('Stop subscription')
            return
        except:
            log.error("Broker sleep timer, problems with read from subscription", exc_info=True)
            pass
        self.sleep_task = asyncio.Task(self.sleep())

    @asyncio.coroutine
    def _cleanup_scheduled_history(self):
        # Clean hash table in redis for task with very old last-run and without next_run
        log.info("Run cleanup task for table Scheduled History")
        tasks_history = yield from self.connection.hgetall(SETTINGS.SCHEDULER_HISTORY_HASH)
        for f in tasks_history:
            key, value = yield from f
            # Iterate over all tasks in history and deserialize
            try:
                task_history = SchedulerTaskHistory.deserialize(value)
            except (pickle.UnpicklingError, EOFError, TypeError, ImportError):
                log.error('Cannot deserialize SchedulerTaskHistory for {}'.format(key), exc_info=True)
                continue
            if not task_history.next_run and (int(now()) - task_history.last_run) > (SETTINGS.SCHEDULED_HISTORY_CLEANUP_MAX_TTL * 1000):
                # task is too old, remove it
                log.info('Cleanup for Scheduled History table. Remove task, name={}'.format(task_history.name))
                yield from self.connection.hdel(SETTINGS.SCHEDULER_HISTORY_HASH, [key])
        self.current_loop.call_later(SETTINGS.SCHEDULED_HISTORY_CLEANUP_PERIOD, self._create_asyncio_task, self._cleanup_scheduled_history)

    def _create_asyncio_task(self, f, args=None, kwargs=None):
        # XXX Should be at BaseEventLoop, but i can't find it!!!
        args = args or ()
        kwargs = kwargs or {}
        asyncio.Task(f(), *args, **kwargs)

    def bootstrap(self):
        log.info("Running scheduler loop")
        self.connection = yield from asyncio_redis.Pool.create(host='localhost', port=6379, encoder=asyncio_redis.encoders.BytesEncoder(), poolsize=5)

        self.tq_storage = TaskStorage(self.current_loop, self.connection)

        # Update objects in storage
        self.install_bootstrap()

        # Initialize worker-scheduler feedback subscription
        self.subscription = yield from self.connection.start_subscribe()
        yield from self.subscription.subscribe([SETTINGS.WORKER_TO_SCHEDULER_CHANNEL])
        self.sleep_task = asyncio.Task(self.sleep())

        # Run scheduled history cleanup
        yield from self._cleanup_scheduled_history()

    def start(self, loop):
        self.current_loop = loop
        loop.add_signal_handler(signal.SIGINT, partial(self.stop, 'SIGINT'))
        loop.add_signal_handler(signal.SIGTERM, partial(self.stop, 'SIGTERM'))
        asyncio.Task(self.loop())

    def stop(self, sig):
        log.info("Got {} signal, we should finish all tasks and stop daemon".format(sig))
        self.run = False
        self.current_loop.stop()

    @asyncio.coroutine
    def loop(self):
        yield from self.bootstrap()
        while self.run:
            try:
                # Inside a while loop, fetch scheduled tasks
                t_start = time.time()

                # May be reload config (limited to 1 per second)
                yield from self._reload_config_tasks_list()

                # Refresh scheduler run history
                yield from self._load_scheduler_tasks_history()

                # Kill expired tasks (broken worker)
                yield from self._check_expired_tasks()

                current_time = now()
                for scheduler_task_name, scheduler_task in self.scheduler_tasks.items():
                    scheduled_task_history = self.scheduler_tasks_history[scheduler_task_name]
                    # Iterate over all recurrent tasks
                    if (scheduled_task_history.get('next_run', 0) <= scheduled_task_history.get('last_run', 0)):
                        log.debug('Got unscheduled task {}'.format(scheduler_task_name))
                        # Task is not scheduled/executed now, so need to schedule
                        next_run_dt = self._get_next_run_time(scheduler_task_name, scheduler_task, int(current_time))
                        log.debug('Next run {} for task {}'.format(next_run_dt, scheduler_task_name))
                        yield from self.schedule_task(name=scheduler_task_name,
                                                    task_type=Task.TYPE_REGULAR,
                                                    run_at=next_run_dt,
                                                    ttl=scheduler_task.get('ttl') or SETTINGS.WORKER_TASK_TIMEOUT,
                                                    kwargs=scheduler_task)
                        yield from self._ping_disptacher()

                t_end = time.time()
                delay = SETTINGS.SCHEDULER_PULL_TIMEOUT - (t_end - t_start)
                if delay > 0:
                    # Sleep for timeout or new push from scheduler
                    try:
                        yield from asyncio.wait([self.sleep_task], timeout=delay)
                    except GeneratorExit:
                        break
            except:
                log.error("Unexpected error in scheduler loop!", exc_info=True)

        self.current_loop.stop()
        self.connection.close()
        log.info('Bye-bye!')


def run():
    try:
        scheduler = Scheduler()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.call_soon(scheduler.start, loop)
        loop.run_forever()
        loop.close()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Stopping daemon...")
        loop.stop()
        loop.close()

