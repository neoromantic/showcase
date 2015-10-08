import asyncio_redis
import asyncio
import datetime
import logging
import pickle
import re
import signal
import time

from collections import defaultdict
from functools import partial

from sensors.utils import now
from sensors.settings import SETTINGS

from storage.influx import LoggingStorage
from storage.redis import ConfigStorage, TaskStorage
from storage.models import Task

logging.basicConfig()
log = logging.getLogger('taskqueue.trigger')

class Trigger(object):

    def __init__(self):
        self.connection = None
        self.subscription = None
        self.current_loop = None
        self.config_version = 0

        self.run = True

        self.config = ConfigStorage()
        self.db_log = LoggingStorage()
        self.tq_storage = None

        self.triggers = {}
        self.metrics_id_to_triggers = defaultdict(list)

        self._reload_triggers_config_last_run = 0

    def bootstrap(self):
        log.info("Running trigger loop")
        self.connection = yield from asyncio_redis.Pool.create(host='localhost', port=6379, encoder=asyncio_redis.encoders.BytesEncoder(), poolsize=3)
        self.tq_storage = TaskStorage(self.current_loop, self.connection)

        # Setup subscription to action results
        self.subscription = yield from self.connection.start_subscribe()
        yield from self.subscription.psubscribe([ SETTINGS.METRICS_CHANNEL.format('*').encode('utf-8') ])

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
    def get_new_message(self):
        reply = yield from self.subscription.next_published()

    @asyncio.coroutine
    def loop(self):
        yield from self.bootstrap()
        while self.run:
            # Load triggers list
            yield from self._reload_config()

            # Wait for new message
            try:
                reply = yield from self.subscription.next_published()
            except GeneratorExit:
                log.info('Stop subscription')
                break
            log.debug('Got new message, channel={}'.format(reply.channel))
            # Decode new message
            try:
                _, metric_id = yield from self._decode_message(reply)
            except Exception:
                log.error("Cannon load data from message in channel={}".format(reply.channel), exc_info=True)

            # Process triggers
            triggers = self.metrics_id_to_triggers.get(metric_id, [])
            for trigger_id in triggers:
                asyncio.Task(self.check_trigger(trigger_id, metric_id))

        self.current_loop.stop()
        self.connection.close()
        log.info('Bye-bye!')

    @asyncio.coroutine
    def _decode_message(self, msg):
        metrics_mask = SETTINGS.METRICS_CHANNEL.replace("{}", "")

        channel = msg.channel.decode('utf-8')
        if channel.startswith(metrics_mask):
            return 'metrics-results', channel[len(metrics_mask):]
        else:
            raise Exception()
            # return '', channel

    @asyncio.coroutine
    def _reload_config(self):
        time_now = int(now())
        if time_now - self._reload_triggers_config_last_run < 1000:  # 1000 = 1sec
            return
        self._reload_triggers_config_last_run = time_now
        config_version = self.config.get_config_version()
        if config_version != self.config_version:
            yield from self._reload_triggers()
            self.config_version = config_version

    @asyncio.coroutine
    def _reload_triggers(self):
        new_triggers = self.config.list_triggers()
        self.triggers = new_triggers
        self.metrics_id_to_triggers = defaultdict(list)
        for trigger_id, trigger in new_triggers.items():
            for condition in trigger.get('conditions', []):
                self.metrics_id_to_triggers[condition.get('metric_id')].append(trigger_id)
        log.info('Loaded {} triggers'.format(len(new_triggers)))

    @asyncio.coroutine
    def _activate_trigger(self, trigger):
        self.db_log.info("Триггер был запущен", None, "trigger", trigger['_id'])
        log.debug("_activare_trigger for {}".format(trigger['_id']))
        for action_obj in trigger['scenario']:
            # Extract values from trigger into dict (param_name -> param_value)
            params_values = {param.get('param'): param.get('value') for param in action_obj['params']}
            # Get action with binded params
            action = self.config.get_action(action_obj['action_id'],
                                            initial_param_values=params_values,
                                            connection_id=trigger.get('connection_id'))

            log.debug('Trigger {}: create task for action {} with params {}'.format(trigger['_id'], action['_id'], params_values))
            task = yield from self.tq_storage.create_task(name=action['_id'],
                                                          task_type=Task.TYPE_TRIGGERED,
                                                          run_at=datetime.datetime.now(),
                                                          ttl=action.get('ttl') or SETTINGS.WORKER_TASK_TIMEOUT,
                                                          kwargs=action,
                                                          store_to=Task.STORE_TO_METRICS)
            yield from self.tq_storage.schedule_task(task)

    """ TASKS """

    @asyncio.coroutine
    def check_trigger(self, trigger_id, metric_id):
        log.info('Check trigger {} for metric {}'.format(trigger_id, metric_id))
        trigger = self.triggers[trigger_id]

        last_values = yield from self.tq_storage.get_metric_last_values(trigger['depends_on'])
        log.debug('Trigger {}: last values is {}'.format(trigger_id, last_values))

        checks = ((trigger_id, cond.get('value', ''), cond['function'], last_values.get(cond['metric_id'])) for cond in trigger['conditions'])
        is_triggered = all(map(lambda check: self.check_condition(*check), checks))

        if is_triggered:
            # Check lock
            log.info('Trigger {} is activated!'.format(trigger_id))
            locked = yield from self.tq_storage.lock_trigger(trigger_id)
            if locked > 1:
                log.info('Trigger {} is locked {} times, do not perform action'.format(trigger_id, locked))
                return
            # Perform action on trigger, it's not locked
            yield from self._activate_trigger(trigger)
        else:
            # Unlock trigger here
            log.debug('Trigger {} is NOT activated, try to unlock!'.format(trigger_id))
            yield from self.tq_storage.unlock_trigger(trigger_id)

    def check_condition(self, trigger_id, cmp_value, condition, value):
        if condition not in SETTINGS.CONDITIONS_CMP_FUNCTIONS.keys():
            log.error("Cannot determine condition for trigger '{}': wrong function '{}'".format(trigger_id, condition))
            return False

        if condition in SETTINGS.CONDITIONS_NUMBERIC:
            try:
                value = float(value)
            except (ValueError, TypeError):
                log.error("Wrong value for trigger '{}', cannot convert metric value '{}' to float before comparasion".format(trigger_id, cmp_value), exc_info=True)
                self.db_log.error("Cannot convert metric value to float before comparasion", str(value), "trigger", trigger_id)
                return False
            try:
                cmp_value = float(cmp_value)
            except (ValueError, TypeError):
                log.error("Wrong value for trigger '{}', cannot convert comparasion value '{}' to float before comparasion".format(trigger_id, cmp_value), exc_info=True)
                self.db_log.error("Cannot convert comparasion value to float before comparasion", str(cmp_value), "trigger", trigger_id)
                return False
        elif condition in SETTINGS.CONDITIONS_BOOLEAN:
            try:
                value = bool(int(value))
            except:
                log.error("Wrong value for trigger '{}', can't cast value to boolean '{}'".format(trigger_id, value))
                self.db_log.error("Can't cast value to boolean '{}'".format(value), str(value), "trigger", trigger_id)
                return False
        elif condition in SETTINGS.CONDITIONS_STRINGS and not isinstance(value, str):
            log.error("Wrong value for trigger '{}', for strings comparasion it should be string, not '{}'".format(trigger_id, value))
            self.db_log.error("For strings comparasion value should be strings, not '{}'".format(value), str(value), "trigger", trigger_id)
            return False

        try:
            result = SETTINGS.CONDITIONS_CMP_FUNCTIONS[condition](value, cmp_value)
            log.debug("Compare values: '{}' {} '{}'".format(value, condition, cmp_value))
        except:
            log.error("Cannot compare values: '{}' {} '{}'".format(value, condition, cmp_value))
            self.db_log.error("Cannot compare values: '{}' {} '{}'".format(value, condition, cmp_value), None, "trigger", trigger_id)
            return False
        return result

def run():
    try:
        trigger = Trigger()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.call_soon(trigger.start, loop)
        loop.run_forever()
        loop.close()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Stopping daemon...")
        loop.stop()
        loop.close()
