import asyncio_redis
import asyncio
import asyncssh
import datetime
import logging
import pickle
import re
import signal

from abc import ABCMeta, abstractmethod
from asyncio import subprocess
from copy import deepcopy
from collections import defaultdict
from functools import partial

from comport.state import ComPortState

from sensors.utils import TasksList, datetime_to_timestamp
from sensors.settings import SETTINGS

from storage.influx import LoggingStorage
from storage.redis import ConfigStorage
from storage.models import Task, SchedulerTaskHistory

from roboutils import parse_host


__all__ = 'BaseWorker', 'MultiActionRunnerWorker'


log = logging.getLogger('taskqueue.worker')


PARSE_COMMAND_RE = re.compile(r'\<CTRL\+(.)\>', flags=re.I)
PARSE_COMMAND_NEWLINE_RE = re.compile(r'\<ENTER\>')
PARSE_COMMAND_WAIT_RE = re.compile(r'%robo\(pause=(\d+)\)%')


class BaseWorker(metaclass=ABCMeta):

    def __init__(self):
        self.current_loop = None
        self.connection = None
        self.comport_state = None
        self.config = None
        self.db_log = None

        self.run = True

        # List of current worker tasks; we use it for tasks per worker limitation
        self.TASKS = TasksList()

        # List for temporary storage completed task for clenup
        self.COMPLETED_TASKS = TasksList()

    @asyncio.coroutine
    def bootstrap(self):
        log.info("Running worker loop")
        self.connection = yield from asyncio_redis.Pool.create(host='localhost', port=6379, encoder=asyncio_redis.encoders.BytesEncoder(), poolsize=3)
        self.config = ConfigStorage()
        self.comport_state = ComPortState()
        self.db_log = LoggingStorage()

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
        """ Main event loop of worker

        :param loop: current event loop
        :return: None
        """
        yield from self.bootstrap()
        # Inside a while loop, wait for incoming events.
        while self.run:
            # Limit tasks per worker, wait for task complete, do not fetch new
            if len(self.TASKS) > SETTINGS.WORKER_TASKS_LIMIT:
                log.debug("Too much tasks in local queue, wait for complete, timeout {}s".format(SETTINGS.WORKER_TASK_TIMEOUT))
                try:
                    done, pending = yield from asyncio.wait(self.TASKS, return_when=asyncio.FIRST_COMPLETED, timeout=SETTINGS.WORKER_TASK_TIMEOUT)
                    continue
                except GeneratorExit:
                    break

            # Pop new task from dispatched queue
            try:
                raw_task = yield from self._pop_task()
            except GeneratorExit:
                break
            if not raw_task:
                continue

            # Deserialize
            task = yield from self._deserialize_task(raw_task)
            if not task:
                continue

            # Set new status
            task = yield from self._move_to_inprogress(task)

            # Run task
            try:
                task_future = yield from self._run_task(task)
            except Exception as ex:
                log.error(ex, exc_info=True)
                pass
        # When finished, close the connection.
        self.current_loop.stop()
        self.connection.close()
        log.info('Bye-bye!')

    @asyncio.coroutine
    def _pop_task(self):
        # Blocking pop task from dispatched list (and atomic push to inprogress list)
        try:
            raw_task = yield from self.connection.brpoplpush(SETTINGS.DISPATCHED_QUEUE, SETTINGS.INPROGRESS_QUEUE, SETTINGS.WORKER_BPOP_TIMEOUT)
            log.debug("Got new tasks from queue {}".format(raw_task))
            return raw_task
        except asyncio_redis.TimeoutError:
            # No new tasks? Sleep for a while
            yield from asyncio.sleep(SETTINGS.WORKER_PULL_SLEEP)
            return
        except Exception:
            log.error('Unexpected error', exc_info=True)

    @asyncio.coroutine
    def _deserialize_task(self, raw_task):
        try:
            task_obj = yield from self.connection.get(SETTINGS.TASK_STORAGE_KEY.format(raw_task.decode('utf-8')).encode('utf-8'))
            if not task_obj:
                raise TypeError()
            task = Task.deserialize(task_obj)
            log.info("Got new task id={}, type={}, status={}".format(task.id, task.type, task.status))
            if not task.status == Task.SCHEDULED:
                log.error("Wrong status={} for task id={}, type={}; Should be SCHEDULED".format(task.status, task.id, task.type))
                return
            return task
        except TypeError as ex:
            log.error("Wrong task_id {}".format(raw_task))
            return
        except (pickle.UnpicklingError, EOFError, TypeError, ImportError):
            yield from self.connection.lrem(SETTINGS.INPROGRESS_QUEUE, value=raw_task)
            log.error("Wrong message in queue", exc_info=True)
            return

    @asyncio.coroutine
    def _move_to_inprogress(self, task):
        """ move_to_inprogress -- Change task status to 'in progress'
        Store task in sorted set with TTL

        :param task: `sensors.models.Task` instance
        """
        ttl = task.ttl or SETTINGS.WORKER_TASK_TIMEOUT
        expires_at = datetime.datetime.now() + datetime.timedelta(seconds=ttl)
        new_task = task._replace(status=Task.INPROGRESS)

        # XXX may be transaction here?
        yield from self.connection.zadd(SETTINGS.INPROGRESS_TASKS_SET, {task.bid(): datetime_to_timestamp(expires_at)})
        yield from self.connection.set(SETTINGS.TASK_STORAGE_KEY.format(new_task.id).encode('utf-8'), new_task.serialize(), expire=SETTINGS.TASK_STORAGE_EXPIRE)

        return new_task

    @asyncio.coroutine
    def _throttle(self, task):
        try:
            freq = int(task.kwargs.get('execution_limit', 0))
        except:
            freq = 0

        if freq == 0:
            return False, 0
        key = SETTINGS.WORKER_THROTTLE_LOCKS.format(task.name).encode('utf-8')
        ttl = yield from self.connection.ttl(key)
        if ttl <= 0:
            # No throttle, no key
            yield from self.connection.set(key, b'', expire=freq)
            return False, 0
        else:
            # Throttled
            return True, ttl

    @asyncio.coroutine
    def _run_task(self, task):
        """ run_task -- Runs tasks

        :param task: `sensors.models.Task` instance
        """
        log.debug("_run_task {}".format(task.id))

        if task.type == Task.TYPE_TRIGGERED:
            is_throttled, expiration = yield from self._throttle(task)
            if is_throttled:
                task_future = asyncio.Future()
                self.TASKS.append(task_future)
                task_future.set_result(None)
                log.info("Task id={}, name={} throttled for {} seconds.".format(task.id, task.name, expiration))
                self.db_log.info("Сценарий не был запущен из-за превышения частоты запуска", None, 'action', task.id)
                self._mark_as_completed_callback(task, task_future)
                return
        # Create future to store Process
        pid = asyncio.Future()
        stopper = asyncio.Future()
        ttl = task.ttl or SETTINGS.WORKER_TASK_TIMEOUT
        # Call runner, pass pid there (need to fill in process!)
        task_future = asyncio.Task(self.runner(task, _pid=pid, stopper=stopper, ttl=ttl, kwargs=task.kwargs))
        # Run expire timer task, pass pid there for ability to kill process
        expire_timer_future = asyncio.Task(self._expire_timer_task(task=task, task_future=task_future, stopper=stopper, _pid=pid, timeout=ttl))

        # Store task in local worker cache list (need to limit tasks per worker)
        self.TASKS.append(task_future)

        # Add callbacks for completed tasks cleanup and remove expire timer
        task_future.add_done_callback(partial(self._mark_as_completed_callback, task))
        task_future.add_done_callback(partial(self._remove_expire_timer_callback, task, expire_timer_future))

    ### TASKS

    @abstractmethod
    @asyncio.coroutine
    def runner(self, task, _pid, stopper, ttl, kwargs):
        """ runner -- Abstarct method, you should implement it in concrete
        Worker class.

        Runner should be a coroutine. System should run it as Task.

        Runner should accept only keyword arguments.

        Runner should accept `_pid` argument (Future of Process) and set_result
        for the _pid variable -- asyncio.subprocess.Process instance.

        Runner should accept kwargs argument.
        """
        pass

    @abstractmethod
    @asyncio.coroutine
    def _store_results(self, task, task_results):
        """ _store_results -- Abstarct method, you should implement it in concrete
        Worker class.

        Runner should be a coroutine.
        """
        pass

    @asyncio.coroutine
    def _cleanup_task(self, task):
        """ clenaup_task -- Task for cleanup completed tasks from redis queue.

        :param task: `sensors.models.Task` instance
        :return: None
        """
        log.debug("_cleanup_task task_id={}".format(task.id))
        # Remove task from inprogress queue
        # XXX may be transaction here?
        cnt1 = yield from self.connection.lrem(SETTINGS.INPROGRESS_QUEUE, value=task.bid())
        # Remove task from sorted set
        cnt2 = yield from self.connection.zrem(SETTINGS.INPROGRESS_TASKS_SET, [task.bid()])
        # Update scheduler information
        # Store next_run in scheduled
        task_scheduler_obj = yield from self.connection.hget(SETTINGS.SCHEDULER_HISTORY_HASH, task.name.encode('utf-8'))
        try:
            task_scheduler = SchedulerTaskHistory.deserialize(task_scheduler_obj)
        except (pickle.UnpicklingError, EOFError, TypeError, ImportError):
            task_scheduler = None
        if task_scheduler and task_scheduler.scheduled_task_id == task.id:
            #if task.status == Task.SUCCESSFUL:
            #    # Update last_run only on success
            #    last_run = datetime_to_timestamp(task.run_at)
            #else:
            #    # If task failed, do not update last_run (last_run is about SUCCESSFUL task exectuion)
            #    last_run = task_scheduler.last_run
            last_run = datetime_to_timestamp(task.run_at)
            task_scheduler = task_scheduler._replace(last_run=last_run, next_run=0, scheduled_task_id=None)
            yield from self.connection.hset(SETTINGS.SCHEDULER_HISTORY_HASH, task.name.encode('utf-8'), task_scheduler.serialize())

        # Publish message about finish
        yield from self.connection.publish(SETTINGS.TASK_CHANNEL.format(task.id).encode('utf-8'), task.status.encode('utf-8'))
        log.debug('Publish message about task {} to {}'.format(task.id, SETTINGS.TASK_CHANNEL.format(task.id)))
        log.debug("_cleanup_task lrem result {}".format(cnt1))
        log.debug("_cleanup_task zrem result {}".format(cnt2))

        # Ping scheduler
        yield from self._ping_scheduler(task)

    @asyncio.coroutine
    def _ping_scheduler(self, task):
        # Publish message about new finished task
        if task.type == Task.TYPE_REGULAR:
            yield from self.connection.publish(SETTINGS.WORKER_TO_SCHEDULER_CHANNEL, b'')

    @asyncio.coroutine
    def _expire_timer_task(self, task, task_future, _pid, stopper, timeout):
        """ expire_timer -- Task for check timeouted processes and kill it.

        :param task: `sensors.models.Task` instance
        :param task_future: `asyncio.Future instance` -- (Future of) runned
                            task we should cancel() after `timeout`
        :param _pid: `asyncio.Future instance` -- (Future of) instance of
                     asyncio.subprocess.Process -- proces we should kill() after
                     `timeout`
        :param timeout: int, timeout in seconds
        :return: None
        """
        log.debug("Run expire timer for task {}".format(task.id))
        yield from asyncio.sleep(timeout)
        try:
            stopper.set_result(True)
            task_future.cancel()
            killers = _pid.result()
            for killer in killers:
                try:
                    killer()
                except ProcessLookupError:
                    pass
                except:
                    log.error("What is this? I try to kill my action process", exc_info=True)
        except:
            log.error("Unexpected error in _expire_timer", exc_info=True)
        log.debug('EXPIRE TIMER for task {}, killing process {}...'.format(task.id, _pid))
        self.db_log.error("Сценарий был остановлен по превышению лимита времени исполнения", None, 'action', task.kwargs.get('_id'))

    ### CALLBACKS

    def _mark_as_completed_callback(self, task, task_future):
        # Store results, change status, remove task from local list
        log.debug('Mark as completed callback is here!')
        try:
            if task_future.result() is not None:
                asyncio.Task(self._store_results(task, task_future.result()))
                new_task = task._replace(status=Task.SUCCESSFUL)
            else:
                new_task = task._replace(status=Task.FAILED)
        except asyncio.CancelledError:
            new_task = task._replace(status=Task.FAILED)
        finally:
            del task
        log.info("Finish task id={}, status={}".format(new_task.id, new_task.status))

        log.debug("Update task status as COMPLETED <id={}> status={}".format(new_task.id, new_task.status))
        asyncio.Task(self.connection.set(SETTINGS.TASK_STORAGE_KEY.format(new_task.id).encode('utf-8'), new_task.serialize(), expire=SETTINGS.TASK_STORAGE_EXPIRE))
        asyncio.Task(self._cleanup_task(new_task))

        # Callback вызывается thread-safe — можно выпилить локи и юзать просто лист
        self.TASKS.remove(task_future)

    def _remove_expire_timer_callback(self, task, expire_timer_future, task_future):
        # Remove exire time checker if task is successfully completed
        log.debug("Cancel expire timer Task for task {}".format(task.id))
        expire_timer_future.cancel()

    ## Helpers
    @staticmethod
    def _get_esc_char(matchobj):
        char = matchobj.group(1).upper()
        if ord(char) in range(65, 96):
            code = ord(char) - 64
            return chr(code)
        return matchobj.group(0)

    @classmethod
    def _parse_command(cls, command):
        # Convert command like <CTRL+X> to escape character
        tmp = command
        tmp = PARSE_COMMAND_RE.sub(cls._get_esc_char, tmp)
        tmp = PARSE_COMMAND_NEWLINE_RE.sub(lambda x: '\r', tmp)
        return tmp


class TelnetReader():

    @asyncio.coroutine
    def _read_stream_with_ttl(self, reader, ttl=1):
        buf = []
        while True and not reader.at_eof():
            done, pending = yield from asyncio.wait([reader.readline()], timeout=ttl)
            if done:
                result = yield from done.pop()
                buf.append(result.decode('utf-8', 'ignore'))
            else:
                reader._waiter = None
                pending.pop().cancel()
                break
        return ''.join(buf).replace('\r', '')

    def _telnet_runner(self, connection, task, killers, command, streams):
        if streams and streams['stdin']:
            stdin, stdout, stderr, conn = streams['stdin'], streams['stdout'], streams['stderr'], streams['connection']
            log.debug('Reuse telnet connection')
        else:
            try:
                ip, port = parse_host(connection['ip'], 23)
                process = yield from asyncio.create_subprocess_exec('telnet', '-E', ip, str(port),
                                                                    stdin=subprocess.PIPE,
                                                                    stdout=subprocess.PIPE,
                                                                    stderr=subprocess.STDOUT)
                stdin, stdout, stderr = process.stdin, process.stdout, process.stderr
            except Exception as ex:
                log.error("Cannot open telnet session", exc_info=True)
                self.db_log.error("Не удалось открыть telnet соединение", str(ex), 'connection', connection['_id'])
                return -999, "", {}

            streams = dict(stdin=stdin, stdout=stdout, stderr=stderr, connection=process)
            log.debug('Open new telnet connection host={}'.format(connection.get('ip')))
            killers.append(process.terminate)

        try:
            stdin.write("{}\r".format(command).encode('utf-8'))
            results = yield from self._read_stream_with_ttl(stdout)
        except:
            log.error("Cannot communicate with TELNET-session", exc_info=True)
            return -999, "", {}

        log.debug('Run telnet command "{}", output:\n--\n{}--'.format(command, results))

        return 0, results, streams

class SSHReader():

    @asyncio.coroutine
    def _read_ssh_with_ttl(self, reader, ttl=1):
        buf = []
        while True and not reader.at_eof():
            done, pending = yield from asyncio.wait([reader.readline()], timeout=ttl)
            if done:
                result = yield from done.pop()
                buf.append(result)
            else:
                reader._session._unblock_read(reader._datatype)
                pending.pop().cancel()
                break
        return ''.join(buf).replace('\r', '')

    def _ssh_runner(self, connection, task, killers, command, streams):
        if streams and streams['stdin'].channel._session:
            stdin, stdout, stderr, conn = streams['stdin'], streams['stdout'], streams['stderr'], streams['connection']
            log.debug('Reuse ssh connection')
        else:
            try:
                ip, port = parse_host(connection['ip'], 22)
                conn, client = yield from asyncssh.create_connection(None, host=ip,
                                                                     port=port,
                                                                     username=connection.get('login'),
                                                                     password=connection.get('password'),
                                                                     server_host_keys=None)
                stdin, stdout, stderr = yield from conn.open_session(term_type='xterm-color', term_size=(80, 24))
            except asyncio.CancelledError:
                log.error("Cannot open SSH-session", exc_info=False)
                self.db_log.error("Не удалось открыть ssh соединение", str(ex), 'connection', connection['_id'])
                return -999, "", {}
            except Exception as ex:
                log.error("Cannot open SSH-session", exc_info=True)
                self.db_log.error("Не удалось открыть ssh соединение", str(ex), 'connection', connection['_id'])
                return -999, "", {}

            streams = dict(stdin=stdin, stdout=stdout, stderr=stderr, connection=conn)
            log.debug('Open new ssh connectionm host={}'.format(connection.get('ip')))
            killers.append(conn.close)

        try:
            stdin.write("{}\r".format(command))
            results = yield from self._read_ssh_with_ttl(stdout)
        except:
            log.error("Cannot communicate with SSH-session", exc_info=True)
            return -999, "", {}

        log.debug('Run ssh command "{}", output:\n--\n{}--'.format(command, results))

        return 0, results, streams


class COMPortConnection():

    def __init__(self, comport_state, settings, ttl):
        self.run = True
        self.ttl = ttl
        self.comport_state = comport_state
        self.settings = settings
        self.lock = None
        self.writer = None
        self.device = None

    @asyncio.coroutine
    def open(self):
        device = self.settings['device']
        # Get UNIX socket
        self.socket = self.comport_state.get_socket(self.settings['_id'])

        # Try to lock COM-port for write
        self.lock = self.comport_state.lock(device, ttl=self.ttl)
        while self.run and not self.lock:
            log.debug("COM-Port is locked, device={}".format(device))
            try:
                yield from asyncio.sleep(1)
                self.lock = self.comport_state.lock(device, ttl=self.ttl)
            except:
                log.error("COM-Port is locked, device={}".format(device))
                return None, None
        if not self.run:
            log.error("COM-Port is locked, device={}".format(device))
            return None, None

        # Connect to socket
        stdout, stdin = yield from asyncio.open_unix_connection(path=self.socket)

        self.device = device
        self.writer = stdin
        return stdout, stdin

    def close(self):
        self.run = False
        if self.writer:
            self.writer.close()
        if self.lock:
            lock = self.comport_state.unlock(self.settings['device'])


class COMPortReader():

    def _comport_runner(self, connection, task, killers, command, streams):
        if streams and streams['stdin']:
            stdin, stdout = streams['stdin'], streams['stdout']
            log.debug('Reuse com-port connection')
        else:
            try:
                conn = COMPortConnection(self.comport_state, connection, ttl=task.ttl or SETTINGS.WORKER_TASK_TIMEOUT)
                killers.append(conn.close)
                stdout, stdin = yield from conn.open()
                if not all([stdout, stdin]):
                    return -999, "", {}
            except Exception as ex:
                log.error("Cannot start COM session with socket={}".format(conn.socket))
                self.db_log.error("Не удалось установить соединение с COM-портом", str(ex), 'connection', connection['_id'])
                return -999, "", {}

            streams = dict(stdin=stdin, stdout=stdout, connection=conn)
            log.debug('Open new COM session with socket={}'.format(conn.socket))

        try:
            stdin.write("{}\r".format(command).encode('utf-8'))
            results = yield from self._read_stream_with_ttl(stdout)
        except:
            log.error("Cannot communicate with COM-session", exc_info=True)
            return -999, "", streams

        log.debug('Run COM command "{}", output:\n--\n{}--'.format(command, results))

        return 0, results, streams


class MultiActionRunnerWorker(BaseWorker, TelnetReader, SSHReader, COMPortReader):

    @asyncio.coroutine
    def runner(self, task, _pid, stopper, ttl, kwargs):
        start_time = datetime.datetime.now()
        action_to_run = kwargs
        log.debug('Start action processing for task {}, action {}'.format(task.id, action_to_run.get('_id')))
        commands = []
        killers = []
        _pid.set_result(killers)

        try:
            # Prepare command_objs:
            stack = [(action_to_run, [])]
            while stack:
                cur_action, return_queue = stack.pop(0)
                return_queue = deepcopy(return_queue)
                return_queue.append(cur_action.get('_id'))
                if cur_action.get('title') == 'Выполнить команду':
                    if not cur_action.get('connection_id'):
                        self.db_log.error("У действия не определено соединение", cur_action.get('title'), 'action', action_to_run.get('_id'))
                        raise Exception('action {} has no resolved connection!'.format(cur_action['_id']))

                    commands.append((cur_action, self._parse_command(cur_action['params'][0]['value']), return_queue))
                    continue
                for in_action in cur_action.get('scenario', [])[::-1]:
                    if 'action' in in_action:
                        stack.insert(0, (in_action.get('action'), return_queue) )

            # Store results here
            results = defaultdict(list)

            # For non-local actions
            # Pool of opened connections
            connections_pool = set()
            # stdout readers from connections, we should drain it at the end
            drain_readers = []
            connections = self.config.list_connections()

            for cur_action, command, return_queue in commands:
                if stopper.done():
                    raise asyncio.CancelledError()
                # run command step-by-step
                connection = connections.get(cur_action['connection_id'])
                if not connection:
                    self.db_log.error("Указанное у действия соединение не существует",
                                      "Action_id: {}\nConnection_id: {}".format(cur_action.get('_id'), cur_action.get('connection_id')),
                                      'action',
                                      action_to_run.get('_id'))
                    raise Exception('Wrong connection_id {}'.format(cur_action['connection_id']))

                pause = PARSE_COMMAND_WAIT_RE.findall(command)
                if pause:
                    try:
                        yield from asyncio.sleep(int(pause[0]))
                        continue
                    except:
                        # XXX Raise, please
                        pass

                if connection['type'] == 'local':
                    exit_code, stdout = yield from self._local_process_runner(task, killers, command)
                elif connection['type'] in ('ssh', 'com', 'telnet'):
                    if connection['type'] == 'ssh':
                        runner = self._ssh_runner
                    elif connection['type'] == 'com':
                        runner = self._comport_runner
                    elif connection['type'] == 'telnet':
                        runner = self._telnet_runner
                    # Это SSH/COM
                    # Набор stdin/stdout'ов от соединения
                    streams = None
                    new_connection = True
                    if connection['_id'] in connections_pool:
                        # Соединение уже открыто
                        streams = connection.get('streams')
                        new_connection = False
                    connections_pool.add(connection['_id'])

                    exit_code, stdout, streams = yield from runner(connection, task, killers, command, streams)
                    if exit_code == -999:
                        continue

                    connection['streams'] = streams
                    if new_connection:
                        drain_readers.append( (return_queue, streams['stdout']) )

                if exit_code == -999:
                    # return None
                    continue
                for _id in return_queue:
                    results[_id].append(dict(exit_code=exit_code, stdout=stdout))
            drain_time = 0
            if drain_readers:
                drain_time = ((ttl - (datetime.datetime.now() - start_time).total_seconds()) / len(drain_readers)) * 0.5
                drain_time = min(drain_time, SETTINGS.WORKER_TASK_TIMEOUT*1.0/3, 1.5)
            for return_queue, reader in drain_readers:
                stdout = yield from self._drain_reader(reader, drain_time)
                if stdout is not None:
                    for _id in return_queue:
                        results[_id].append(dict(exit_code=0, stdout=stdout))
            for connection_id in connections_pool:
                connection = connections.get(connection_id)
                # Close SSH connections, unlock COM-ports
                if 'streams' in connection:
                    if 'connection' in connection['streams']:
                        if hasattr(connection['streams']['connection'], 'terminate'):
                            try:
                                connection['streams']['connection'].terminate()
                            except:
                                pass
                        elif hasattr(connection['streams']['connection'], 'close'):
                            connection['streams']['connection'].close()

            log.debug('Task output Results: {}'.format(results))
        except asyncio.CancelledError as ex:
            log.error('Task {} for action {} was stopped by expire timer!'.format(task.id, action_to_run.get('_id')))
            return None
        except Exception as ex:
            log.error(ex, exc_info=True)
            return None
        log.debug('Finish action processing for task {}, action {}'.format(task.id, action_to_run.get('_id')))

        try:
            results2 = {}
            for key, values in results.items():
                stdout = []
                for x in values:
                    s = x.get('stdout', '')
                    if len(s) and not s.endswith('\n'):
                        stdout.extend([s, '\n'])
                    else:
                        stdout.extend([s])
                # stdout = ('\n'.join(x.get('stdout', '') for x in values)).strip()
                res = {'exit_codes': [x.get('exit_code') for x in values],
                    'stdout': ''.join(stdout).strip()}
                results2[key] = res
        except:
            log.error("Internal error", exc_info=True)
            results2 = {}

        try:
            if not all((x == 0) for x in results2.get(action_to_run['_id'], {}).get('exit_codes', [])):
                self.db_log.error("Код возврата одного из действий <> 0", results2.get(action_to_run['_id'], {}).get('stdout'), 'action', action_to_run.get('_id'))
        except:
            log.error('Handle error', exc_info=True)
        return results2

    @asyncio.coroutine
    def _local_process_runner(self, task, killers, command):
        log.debug('Run locally cmd for task {}'.format(task.id))
        try:
            process = yield from asyncio.create_subprocess_shell(command,
                                                                 stdout=subprocess.PIPE,
                                                                 stderr=subprocess.STDOUT)
            # Add process to list of pids (it is shared object, cool)
            # Add killer method to list
            killers.append(process.kill)
            lines = []
            stdout = ''
            try:
                while not process.stdout.at_eof():
                    line = yield from process.stdout.readline()
                    lines.append(line)

                stdout = ''.join([line.decode('utf-8', 'ignore') for line in lines])
            except asyncio.CancelledError as ex:
                log.error('Task {} was stopped by expire timer!'.format(task.id))
                try:
                    process.kill()
                except:
                    return (-999, '')
                yield from process.wait()
                return (-999, '')
            except Exception as ex:
                log.error('Unexpected error in runner', exc_info=True)
                try:
                    process.kill()
                except:
                    return (-999, '')
                yield from process.wait()
                return (-999, '')
            exitcode = yield from process.wait()
            return (exitcode, stdout)
        except Exception as ex:
            log.error(ex, exc_info=True)
            return (-999, '')

    @asyncio.coroutine
    def _drain_reader(self, reader, ttl):
        if isinstance(reader, asyncssh.SSHReader):
            res = yield from self._read_ssh_with_ttl(reader, ttl=ttl)
            return res
        elif isinstance(reader, asyncio.StreamReader):
            res = yield from self._read_stream_with_ttl(reader, ttl=ttl)
            return res

    @asyncio.coroutine
    def _store_results(self, task, task_results):
        log.debug('Store results for task={}'.format(task))
        results = dict(task=dict(id=task.id, run_at=task.run_at), result=task_results)

        if task.store_to == Task.STORE_TO_METRICS:
            # Store to metrics, send signals about actions complete
            for action_id, result in task_results.items():
                # Publish message with results
                if not result.get('stdout', '').strip():
                    continue
                data = pickle.dumps(dict(task=dict(id=task.id, run_at=task.run_at), result=result))
                yield from self.connection.publish(SETTINGS.ACTION_RESULTS_CHANNEL.format(action_id).encode('utf-8'), data)
        elif task.store_to.startswith(Task.STORE_TO_KEY):
            key = task.store_to.split(':', 1)[1]
            data = pickle.dumps(results)
            yield from self.connection.set(key.encode('utf-8'), data, expire=SETTINGS.TASK_STORAGE_EXPIRE)


def run():
    try:
        worker = MultiActionRunnerWorker()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.call_soon(worker.start, loop)
        loop.run_forever()
        loop.close()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("Stopping daemon...")
        loop.stop()
        loop.close()
