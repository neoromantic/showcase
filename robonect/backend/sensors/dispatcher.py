import asyncio_redis
import asyncio
import logging
import signal
import time

from functools import partial

from sensors.utils import now
from sensors.settings import SETTINGS

logging.basicConfig()
log = logging.getLogger('taskqueue.dispatcher')

# Lua script for redis to move tasks from scheduled queue to dispatched in transaction
SCRIPT_CODE = """
local scheduled_queue = KEYS[1]
local dispatched_queue = KEYS[2]
local ctime = ARGV[1]
local jobs_limit = ARGV[2]
local jobs

local tcount = function(T)
  local count = 0
  for _ in pairs(T) do count = count + 1 end
  return count
end

local not_empty = function(x)
  return (type(x) == "table") and (not x.err) and (#x ~= 0)
end

jobs = redis.pcall('zrangebyscore', scheduled_queue, '-inf', ctime, 'LIMIT', '0', '1000')

if not_empty(jobs) then
  redis.call('ZREM', scheduled_queue, unpack(jobs))
  redis.call('LPUSH', dispatched_queue, unpack(jobs))
  redis.call('LTRIM', dispatched_queue, 0, jobs_limit)

  return tcount(jobs)
else
  return 0
end
"""


class Dispatcher(object):

    def __init__(self):
        self.connection = None
        self.current_loop = None
        self.script = None
        self.run = True

        self.subscription = None
        self.sleep_task = None

    @asyncio.coroutine
    def bootstrap(self):
        log.info("Running dispatcher loop")
        self.connection = yield from asyncio_redis.Pool.create(host='localhost', port=6379, encoder=asyncio_redis.encoders.BytesEncoder(), poolsize=3)
        yield from self.reload_script()

        # Initialize scheduler-dispatcher feedback subscription
        self.subscription = yield from self.connection.start_subscribe()
        yield from self.subscription.subscribe([SETTINGS.SCHEDULER_TO_DISPATCHER_CHANNEL])
        self.sleep_task = asyncio.Task(self.sleep())

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
        # Inside a while loop, fetch scheduled tasks
        while self.run:
            # move tasks from scheduled to dispatched queue
            try:
                script_reply = yield from self.script.run(keys=[SETTINGS.SCHEDULED_QUEUE, SETTINGS.DISPATCHED_QUEUE], args=[now(), str(SETTINGS.DISPATCHED_QUEUE_LIMIT).encode('utf-8')])
                result = yield from script_reply.return_value()
                if result > 0:
                    log.info("Dispatched {} tasks".format(result))
            except asyncio_redis.ScriptKilledError as ex:
                log.error('Unexpected exception!', exc_info=True)
                yield from self.reload_script()

            # Sleep for timeout or new push from scheduler
            try:
                yield from asyncio.wait([self.sleep_task], timeout=SETTINGS.DISPATCHER_PULL_TIMEOUT)
            except GeneratorExit:
                pass
        # yield from self.connection.script_flush()
        self.current_loop.stop()
        self.connection.close()
        log.info('Bye-bye!')

    @asyncio.coroutine
    def reload_script(self):
        """ Load lua-script into redis """
        script_in_redis = [False]
        try:
            if self.script:
                # Check that our script in redis
                script_in_redis = yield from self.connection.script_exists([self.script.sha])
            if not script_in_redis or not all(script_in_redis):
                # Load lua script to redis and store sha in object
                self.script = yield from self.connection.register_script(SCRIPT_CODE)
                log.debug("Registered lua-script sha1: {}".format(self.script.sha))
        except:
            log.error('Unexpected exception!', exc_info=True)

    @asyncio.coroutine
    def sleep(self):
        try:
            reply = yield from self.subscription.next_published()
        except GeneratorExit:
            log.info('Stop subscription')
        except:
            log.error("Broker sleep timer, problems with read from subscription", exc_info=True)
        self.sleep_task = asyncio.Task(self.sleep())


def run():
    try:
        dispatcher = Dispatcher()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.call_soon(dispatcher.start, loop)
        loop.run_forever()
        loop.close()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Stopping daemon...")
        loop.stop()
        loop.close()
