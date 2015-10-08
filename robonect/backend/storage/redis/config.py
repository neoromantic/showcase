import copy
import hashlib
import logging
import math
import random
import redis
import time
import ujson


from sensors.settings import SETTINGS
from sensors.utils import parse_timetable


__all__ = 'StorageException', 'ActionResursion', 'ConfigStorage'

assert SETTINGS


class StorageException(Exception):

    def __init__(self, value, extra):
        self.value = value
        self.extra = extra

    def __str__(self):
        return repr(self.value)


class ActionResursion(StorageException):
    pass


class ConfigStorage(object):
    _connection = None
    _settings = {
        'host': 'localhost',
        'port': 6379,
        'db': 0,
    }
    log = None

    NAMESPACE = "robonect"
    CONFIGURATION_VERSION_KEY_TPL = "lastChanged"

    def __init__(self):
        self.log = logging.getLogger('storage.redis')

        self.CONFIGURATION_VERSION_KEY = ":".join([self.NAMESPACE, self.CONFIGURATION_VERSION_KEY_TPL]).encode('utf-8')
        if self.connection:
            self.log.info('Storage connected')

    @property
    def connection(self):
        if not self._connection:
            self._connection = redis.StrictRedis(**self._settings)
        return self._connection

    # General config methods
    def get_config_version(self):
        return self.connection.get(self.CONFIGURATION_VERSION_KEY)

    def update_config_version(self):
        return self.connection.set(self.CONFIGURATION_VERSION_KEY, time.time())

    def get_config(self, key):
        db_key = ":".join([self.NAMESPACE, key, '*'])
        db_keys = self.connection.keys(db_key)
        if not db_keys:
            return []
        vals = self.connection.mget(db_keys)
        return [ujson.loads(val) for val in vals if val]

    def del_config(self, key):
        db_key = ":".join([self.NAMESPACE, key, '*'])
        db_keys = self.connection.keys(db_key)
        l = 20
        for i in range(int(math.ceil(len(db_keys)*1.0/l))):
            self.connection.delete(*db_keys[i*l:(i+1)*l])

    def add_object(self, key, obj):
        if not obj.get('_id'):
            obj['_id'] = hashlib.md5(obj.get('title', '') + str(random.random())).hexdigest()
            db_key = ":".join([self.NAMESPACE, key, obj['_id']])
        # Fuck the system
        db_key = obj['_id']
        self.connection.set(db_key, ujson.dumps(obj))
        self.update_config_version()
        return True

    def del_object(self, key, id):
        # Fuck the system!
        # db_key = ":".join([self.NAMESPACE, key, id])
        # db_key = ":".join([self.NAMESPACE, key, id])
        # self.connection.delete(db_key)
        self.connection.delete(id)

    # About Actions (get actions with schedule)
    def list_actions(self):
        actions = self.get_config('action')
        actions_dict = {action.get('_id'): action for action in actions}

        return actions_dict

    def get_scheduled_actions(self):
        """ get_scheduled_actions -- fetch list of scheduled actions

        :returns: (dict) id -> parsed action with schedule """
        actions = self.get_config('action')
        actions_dict = {action.get('_id'): action for action in actions}

        # Filter list of regular tasks
        scheduled = filter(lambda action: parse_timetable(action.get('schedule', '')), actions)
        scheduled_dict = {}
        for action in scheduled:
            try:
                parsed = self._parse_action(actions_dict, action)
                scheduled_dict[action.get('_id')] = parsed
            except ActionResursion as ex:
                self.log.error(ex.value)
        return scheduled_dict

    def get_action(self, _id, initial_param_values={}, connection_id=None):
        actions_dict = self.list_actions()
        action = copy.deepcopy(actions_dict.get(_id))
        if action and connection_id:
            action['connection_id'] = connection_id
        return self._parse_action(actions_dict, action, initial_param_values=initial_param_values)

    def _parse_action(self, actions_dict, action, initial_param_values={}):
        """ _parse_action -- replaces _id reference to action by action object
                             with params substition.

            :param actions_dict: (dict) of all actions objects, key - id,
                                 value - aciton

            :param action: (dict) action for parsing

            :returns: (dict) action without references
        """
        if not action:
            return action

        waction = copy.deepcopy(action)
        # In stack: (action, params, visited, connection_id)
        stack = [(waction, initial_param_values, [], action.get('connection_id'))]
        while stack:
            cur_action, input_params, visited_orig, connection_id = stack.pop(0)

            # Propogate connection
            if cur_action.get('connection_id'):
                connection_id = cur_action['connection_id']
            else:
                cur_action['connection_id'] = connection_id

            cur_action['ttl'] = int(cur_action.get('ttl', 0)) or None

            # Вытащить все входные параметры по порядку, подставить значения
            for param_obj in cur_action.get('params', []):
                param_key = param_obj.get('param')
                if param_key in input_params:
                    param_obj['value'] = input_params[param_key]

            inner_actions = cur_action.get('scenario', [])
            # Пройти по всем включенным экшнам и поставить в очередь на обработку
            for inner_action in inner_actions[::-1]:
                visited = copy.copy(visited_orig)
                _id = inner_action.get('action_id')

                if _id in visited:
                    raise ActionResursion('Recursion detected for action {}! Chain: {}'.format(cur_action.get('_id'), visited), extra=visited)

                ref_action = copy.deepcopy(actions_dict.get(_id))
                if not ref_action:
                    self.log.error('Reference to undefined aciton with id={}'.format(_id))
                    continue
                # Set action property
                inner_action['action'] = ref_action
                visited.append(_id)

                # Вытащить список параметров для передачи во включенный экшн
                param_values = inner_action.pop('params') if 'params' in inner_action else []

                # Сделать подстановку в каждом параметре для каждого позиционного параметра
                for param in param_values:
                    for i, param_obj in enumerate(cur_action.get('params', []), 1):
                        param['value'] = param['value'].replace("${}".format(i), str(param_obj.get('value', '')))

                param_values_dict = {param.get('param'): param.get('value') for param in param_values}
                stack.insert(0, (ref_action, param_values_dict, visited, connection_id))
                # Remove unusable values
                del inner_action['action_id']
                # cur_action.pop('params') if 'params' in cur_action else None
        return waction

    def list_metrics(self):
        """ list metrics -- fetch list of metrics

        :returns: (dict) id -> parsed metric """
        metrics = self.get_config('metric')
        metrics_dict = {metric.get('_id'): metric for metric in metrics}

        return metrics_dict

    def list_triggers(self):
        """ list triggers -- fetch list of triggers

        :returns: (dict) id -> parsed trigger """
        triggers = self.get_config('trigger')
        triggers_dict = {trigger.get('_id'): trigger for trigger in triggers}
        for trigger in triggers_dict.values():
            trigger['depends_on'] = {condition.get('metric_id') for condition in trigger.get('conditions', [])}

        return triggers_dict

    def list_connections(self):
        """ list connections -- fetch list of connections

        :returns: (dict) id -> parsed conncetion """
        connections = self.get_config('connection')
        connections_dict = {connection.get('_id'): connection for connection in connections}

        return connections_dict

    def get_connection(self, _id=None, local=None):
        assert _id or local
        connections = self.list_connections()

        if _id:
            return connections.get(_id)
        elif local:
            for connection in connections.values():
                if connection['type'] == 'local':
                    return connection
