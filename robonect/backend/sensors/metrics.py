import asyncio_redis
import asyncio
import logging
import pickle
import re
import signal
import time
import ujson

from collections import defaultdict
from functools import partial

from sensors.utils import now, datetime_to_timestamp, parse_timetable
from sensors.settings import SETTINGS

from storage.redis import ConfigStorage
from storage.influx import MetricsStorage, LoggingStorage

SPLIT_RE = re.compile(r"( +|\t+|\(|\)|\.|\:|\=|,|\%|\/|\\|\[|\]|;|\"|\')|(-(?!\d))")
SPLIT_NEG_RE = re.compile(r"(.+)(-)")
SKIP_RE = re.compile(r"( +|\t+)$")


logging.basicConfig()
log = logging.getLogger('taskqueue.metrics')

class MetricsCollector(object):

    def __init__(self):
        self.connection = None
        self.subscription = None
        self.current_loop = None
        self.config_version = 0
        self.run = True

        self.storage = ConfigStorage()
        self.metrics_storage = MetricsStorage()
        self.db_log = LoggingStorage()

        self._lcache = {}

        self.metrics = {}
        self.actions_id_to_metrics = defaultdict(list)

        self._reload_metrics_config_last_run = 0

    @asyncio.coroutine
    def bootstrap(self):
        log.info("Running metrics collector loop")
        self.connection = yield from asyncio_redis.Pool.create(host='localhost', port=6379, encoder=asyncio_redis.encoders.BytesEncoder(), poolsize=3)

        # Setup subscription to action results
        self.subscription = yield from self.connection.start_subscribe()
        yield from self.subscription.psubscribe([SETTINGS.ACTION_RESULTS_CHANNEL.format("*").encode('utf-8'),
                                                 SETTINGS.CONNECTION_RESULTS_CHANNEL.format("*").encode('utf-8')])
        yield from self._reload_config()

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
            metrics = []
            # Wait for new message
            try:
                reply = yield from self.subscription.next_published()
            except GeneratorExit:
                break
            log.debug('Got new message, channel={}'.format(reply.channel))

            # Load metrics list
            yield from self._reload_config()

            # Decode new message
            try:
                channel_type, object_id = yield from self._decode_message(reply)
                results = pickle.loads(reply.value)
                task = results['task']
                values = results['result']
            except Exception:
                log.error("Cannon load data from message in channel={}, data={}".format(reply.channel, reply.value), exc_info=True)
                continue
            # Process metrics
            if channel_type == 'actions-results':
                metrics = self.actions_id_to_metrics.get(object_id, [])
            elif channel_type == 'connections-results':
                # Skip empty lines for connection grep
                if not values.get('stdout'):
                    continue
                metrics = self.connections_id_to_metrics.get(object_id, [])
            else:
                log.error('Unexpected metric-channel type={}'.format(channel_type))
                continue

            for metric_id in metrics:
                asyncio.Task(self.store_metric_value(metric_id, object_id, task, values))

        self.current_loop.stop()
        self.connection.close()
        log.info('Bye-bye!')

    @asyncio.coroutine
    def _decode_message(self, msg):
        action_mask = SETTINGS.ACTION_RESULTS_CHANNEL.replace("{}", "")
        connection_mask = SETTINGS.CONNECTION_RESULTS_CHANNEL.replace("{}", "")

        channel = msg.channel.decode('utf-8')
        if channel.startswith(action_mask):
            return 'actions-results', channel[len(action_mask):]
        elif channel.startswith(connection_mask):
            return 'connections-results', channel[len(connection_mask):]
        else:
            return '', channel

    @asyncio.coroutine
    def _reload_config(self):
        time_now = int(now())
        if time_now - self._reload_metrics_config_last_run < 1000:  # 1000 = 1sec
            return
        self._reload_metrics_config_last_run = time_now
        config_version = self.storage.get_config_version()
        if config_version != self.config_version:
            yield from self._reload_metrics()
            self.config_version = config_version

    @asyncio.coroutine
    def _reload_metrics(self):
        new_metrics = self.storage.list_metrics()
        self.metrics = new_metrics
        self.actions_id_to_metrics = defaultdict(list)
        self.connections_id_to_metrics = defaultdict(list)
        for metric_id, metric in new_metrics.items():
            if 'action_id' in metric:
                self.actions_id_to_metrics[metric.get('action_id')].append(metric_id)
            elif 'connection_id' in metric:
                self.connections_id_to_metrics[metric.get('connection_id')].append(metric_id)
        self._lcache = {}
        log.info('Loaded {} metrics'.format(len(new_metrics)))


    """ TASKS """

    @asyncio.coroutine
    def store_metric_value(self, metric_id, object_id, task, values):
        log.debug('store_metric_value {} for action/connection {} by task {}'.format(metric_id, object_id, task['id']))
        exit_codes = values.get('exit_codes')
        stdout = values.get('stdout')

        metric = self.metrics.get(metric_id)
        value = self.parse_value(metric, stdout)
        log.debug('Metric (id={}) parsed value: {}'.format(metric_id, value))
        if value is None:
            logging.error("No parser match for metric {}, nothing to store".format(metric_id))
            self.db_log.error("Пустое значение после фильтрации", stdout, "metric", metric_id)
            return

        converter = lambda x: x
        # Convert metric type
        if metric['type'] == 'boolean':
            value = self.cast_to_boolean(metric_id, metric, value)
        else:
            converter = SETTINGS.METRICS_TYPES_MAP[metric['type']]
            try:
                value = converter(value)
            except ValueError:
                log.error("Wrong value for metric '{}', cannot convert to {}".format(metric_id, metric['type']), exc_info=True)
                self.db_log.error("Не удалось привести тип значения к {}".format(metric['type']), str(value), "metric", metric_id)
                return

        # Trim strings
        if isinstance(value, str):
            value = value[:SETTINGS.METRIC_STRING_LIMIT]

        # Apply multiplier
        multiplier = metric.get('multiplier', None)
        try:
            if multiplier and metric['type'] in SETTINGS.METRIC_NUMERICAL_TYPES:
                multiplier = float(multiplier)
                value = value * multiplier

                # If it is int, convert to int
                value = converter(value)
        except:
            log.error('Cannot apply multiplier', exc_info=True)
            self.db_log.error("Не удалось применить множитель", str(value), "metric", metric_id)
            return

        timestamp = datetime_to_timestamp(task['run_at'])
        skip_interval = parse_timetable(metric.get('limit_duplicate_save', ''))
        if skip_interval:
            prev_val, prev_timestamp = self._lcache.get(metric_id, (None, 0))
            if (prev_val == value) and (timestamp - prev_timestamp) < skip_interval:
                return True
            else:
                self._lcache[metric_id] = (value, datetime_to_timestamp(task['run_at']))

        log.info('Store value="{}" for metric {}'.format(value, metric_id))
        try:
            self.metrics_storage.store_metric(metric_id, value, time=task['run_at'])
            yield from self.connection.hset(SETTINGS.LAST_VALUES_HASH, metric_id.encode('utf-8'), ujson.dumps({'value': value, 'timestamp': timestamp}).encode('utf-8'))
        except:
            log.error('Cannot store metric value, storage exception', exc_info=True)
            return

        # Publish message about finish
        yield from self.connection.publish(SETTINGS.METRICS_CHANNEL.format(metric_id).encode('utf-8'), b'')
        return True

    def parse_value(self, metric, stdout):
        stdout_lines = stdout.split('\n')
        line_regexp = metric.get('line_regexp')
        line_numbers = str(metric.get('line_numbers', ''))
        word_regexp = metric.get('word_regexp')
        word_numbers = str(metric.get('word_numbers', ''))

        lines_str = None
        lines_no = set()
        if line_regexp:
            regexp = re.compile(line_regexp)
            for i, stdout_line in enumerate(stdout_lines, 1):
                if regexp.search(stdout_line):
                    lines_no.add(i)
        if line_numbers:
            line_values = line_numbers.split(',')
            for line_value in line_values:
                if ':' in line_value:
                    start, finish = map(int, line_value.split(':'))
                    for i in range(start, finish+1):
                        lines_no.add(i)
                else:
                    lines_no.add(int(line_value))

        if (line_regexp or line_numbers):
            if lines_no:
                lines_no = sorted(list(lines_no))
                lines = []
                total_lines = len(stdout_lines)
                for line_no in lines_no:
                    if line_no > total_lines:
                        continue
                    lines.append(stdout_lines[line_no-1])
                lines_str = '\n'.join(lines)
        else:
            lines_str = stdout

        if not lines_str:
            return None

        if word_regexp:
            match = re.findall(word_regexp, lines_str)
            if not match:
                return None
            return match[0]
        elif word_numbers:
            words_range = None
            if ':' in word_numbers:
                start, finish = map(int, word_numbers.split(':'))
                words_range = int(start)-1, int(finish)-1
            else:
                words_range = int(word_numbers)-1, int(word_numbers)-1
        else:
            return lines_str

        stdout_words = list(filter(lambda x: x is not None, SPLIT_RE.split(lines_str)))
        stdout_words = [x for sublist in map(lambda word: SPLIT_NEG_RE.split(word), stdout_words) for x in sublist]
        # Frontend do not count \t, ' ' and '' words :(
        skip_cnt = 0
        words_no_map = {}
        for i, word in enumerate(stdout_words):
            if word == '' or SKIP_RE.match(word):
                skip_cnt += 1
                continue
            words_no_map[i-skip_cnt] = i

        start = words_no_map.get(words_range[0], 0)
        finish = words_no_map.get(words_range[1], len(stdout_words)-1) + 1

        result_words = stdout_words[start:finish]
        words_str = ''.join(result_words)

        return words_str

    def cast_to_boolean(self, metric_id, metric, value):
        try:
            condition = metric['function']
            cmp_value = metric['value']
        except Exception:
            log.error('Boolean metric (id={}) without condition!'.format(metric_id))
            return

        if condition not in SETTINGS.CONDITIONS_CMP_FUNCTIONS.keys():
            log.error("Cannot convert value for metric '{}' to bool: wrong function '{}'".format(metric_id, condition))
            self.db_log.error("Не удалось привести значение к булевой метрике, невреная функция '{}'".format(condition), str(value), "metric", metric_id)
            return

        if condition in SETTINGS.CONDITIONS_NUMBERIC:
            # Cast values to float
            try:
                value = float(value)
            except (ValueError, TypeError):
                log.error("Wrong value for metric '{}', cannot convert '{}' to float before comparasion".format(metric_id, value), exc_info=True)
                self.db_log.error("Не удалось привести значение метрики к дробному типу для проведения сравнения", str(value), "metric", metric_id)
                return
            try:
                cmp_value = float(cmp_value)
            except (ValueError, TypeError):
                log.error("Wrong value for metric '{}', cannot convert comparasion value '{}' to float before comparasion".format(metric_id, cmp_value), exc_info=True)
                self.db_log.error("Cannot convert comparasion value to float before comparasion", str(cmp_value), "metric", metric_id)
                return
        elif condition in SETTINGS.CONDITIONS_BOOLEAN and not isinstance(value, bool):
            log.error("Wrong value for metric '{}', for booleans comparasion it should be boolean, not '{}'".format(metric_id, value))
            self.db_log.error("For boolean comparasion value should be boolean, not '{}'".format(value), str(value), "metric", metric_id)
            return
        elif condition in SETTINGS.CONDITIONS_STRINGS and not isinstance(value, str):
            log.error("Wrong value for metric '{}', for strings comparasion it should be string, not '{}'".format(metric_id, value))
            self.db_log.error("For strings comparasion value should be strings, not '{}'".format(value), str(value), "metric", metric_id)
            return

        try:
            result = SETTINGS.CONDITIONS_CMP_FUNCTIONS[condition](value, cmp_value)
        except:
            log.error("Cannot compare values: '{}' {} '{}'".format(value, condition, cmp_value))
            self.db_log.error("Не удалось сравнить значения: '{}' {} '{}'".format(value, condition, cmp_value), None, "metric", metric_id)
            return None
        return (1 if result else 0)

def run():
    try:
        metrics = MetricsCollector()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.call_soon(metrics.start, loop)
        loop.run_forever()
        loop.close()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Stopping daemon...")
        loop.stop()
        loop.close()
