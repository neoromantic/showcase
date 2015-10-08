import copy
import logging
import requests
import ujson

from sensors.utils import datetime_to_timestamp
from sensors.settings import SETTINGS

assert SETTINGS


class InfluxStorageException(Exception):

    def __init__(self, value, extra):
        self.value = value
        self.extra = extra

    def __str__(self):
        return repr(self.value)


class InfluxStorage(object):
    log = None

    proto = 'http'
    host = 'localhost'
    port = '8086'

    user = 'robonect'
    password = 'robonect'

    timeout = 1
    read_timeout = 5

    BASE_URL = None
    URLS_TPL = {'CREATE_DB': 'cluster/database_configs/{}',
                'CREATE_USER': 'db/{}/users',
                'STORE_VALUES': 'db/{}/series',
                'CONFIGURE_SHARD': 'cluster/shard_spaces/{}/{}',
                'QUERY': 'db/{}/series'}
    URLS = None

    GET_PARAMS = None
    GET_PARAMS_DATA = None
    TIME_PRECISION = {'time_precision': 'ms'}

    OK_STATUSES = (200, 201)

    db = None

    def __init__(self, db, shard_config):
        self.db = db
        self.shard_config = shard_config
        self.log = logging.getLogger('storage.influx')
        self.BASE_URL = '{}://{}:{}/'.format(self.proto, self.host, self.port)

        self.GET_PARAMS = {'u': self.user, 'p': self.password}
        self.GET_PARAMS_DATA = self.GET_PARAMS.copy()
        self.GET_PARAMS_DATA.update(self.TIME_PRECISION)

        self.URLS = {}

        assert self.db

        self._init_urls(self.db)
        self._create_db(self.db, self.shard_config)
        self._create_user(self.db, self.user, self.password)

        for key, cfg in self.shard_config.items():
            try:
                self.configure_shard(key, cfg)
            except:
                self.log.error('Error in shard configuration', exc_info=True)

        self.log.info('Storage connected')

    def _init_urls(self, db):
        for key, value in self.URLS_TPL.items():
            self.URLS[key] = self.BASE_URL + value
        self.URLS['STORE_VALUES'] = self.URLS['STORE_VALUES'].format(db)
        self.URLS['QUERY'] = self.URLS['QUERY'].format(db)
        self.URLS['CREATE_USER'] = self.URLS['CREATE_USER'].format(db)

    def _create_db(self, db, shard_config):
        spaces = []
        for key, cfg in shard_config.items():
            spaces.append(copy.copy(cfg))
            spaces[-1]['name'] = key
        url = self.URLS['CREATE_DB'].format(db)
        data = {'spaces': spaces}
        params = copy.copy(self.GET_PARAMS)
        params.update({'u': 'root', 'p': 'root'})
        try:
            resp = requests.post(url, params=params, data=ujson.dumps(data), timeout=self.timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            self.log.error('Cannot connect to influxdb, timeout ({}s)'.format(self.timeout))
            return False
        if resp.status_code == 400:
            self.log.info("Initialization: all ok, influx DB '{}' already exists".format(db))
            return False
        if resp.status_code not in self.OK_STATUSES:
            self.log.error("Code: {}. Error: {}".format(resp.status_code, str(resp.content)))
            return False
        self.log.info("Initialization: all ok, influx DB '{}' successfully created".format(db))
        return True

    def _create_user(self, db, user, password):
        data = {'name': user, 'password': password}
        params = copy.copy(self.GET_PARAMS)
        params.update({'u': 'root', 'p': 'root'})
        try:
            resp = requests.post(self.URLS['CREATE_USER'], params=params, data=ujson.dumps(data), timeout=self.timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            self.log.error('Cannot connect to influxdb, timeout ({}s)'.format(self.timeout))
            return False
        if resp.status_code == 400:
            self.log.info("Initialization: all ok, influx USER '{}' already exists in db '{}'".format(user, db))
            return False
        if resp.status_code not in self.OK_STATUSES:
            self.log.error("Code: {}. Error: {}".format(resp.status_code, str(resp.content)))
            return False
        self.log.info("Initialization: all ok, influx USER '{}' successfully created for DB '{}'".format(user, db))
        return True

    def configure_shard(self, shard, config):
        params = copy.copy(self.GET_PARAMS)
        params.update({'u': 'root', 'p': 'root'})
        try:
            resp = requests.post(self.URLS['CONFIGURE_SHARD'].format(self.db, shard), params=params, data=ujson.dumps(config), timeout=self.timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            self.log.error('Cannot connect to influxdb, timeout ({}s)'.format(self.timeout))
            return False
        if resp.status_code not in self.OK_STATUSES:
            self.log.error("Code: {}. Error: {}".format(resp.status_code, str(resp.content)))
            return False
        self.log.info("Shard configuration: all ok")
        return True

    def _store_values(self, table, fields, values):
        assert isinstance(fields, (tuple, list))
        assert isinstance(values, (tuple, list))
        data = [{'name': table, 'columns': fields, 'points': values}]
        try:
            resp = requests.post(self.URLS['STORE_VALUES'], params=self.GET_PARAMS_DATA, data=ujson.dumps(data), timeout=self.timeout)
        except requests.exceptions.Timeout:
            self.log.error('Cannot connect to influxdb, timeout ({}s)'.format(self.timeout))
            return False
        except:
            self.log.error('Unexpected error', exc_info=True)
            return False
        if resp.status_code not in self.OK_STATUSES:
            raise InfluxStorageException(resp.content, extra=resp)
        self.log.debug("Stored into table='{}' for columns '{}' values '{}'".format(table, fields, values))
        return True

    def list_series(self):
        params = copy.copy(self.GET_PARAMS)
        params.update({'q': 'list series;'})
        try:
            resp = requests.get(self.URLS['QUERY'], params=params, timeout=self.read_timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            self.log.error('Cannot connect to influxdb, timeout ({}s)'.format(self.read_timeout))
            raise
        if resp.status_code not in self.OK_STATUSES:
            raise InfluxStorageException(resp.content, extra=resp)

        try:
            data = ujson.loads(resp.content)
            i = data[0].get('columns', []).index('name')
            series = [x[i] for x in data[0].get('points')]
        except:
            raise InfluxStorageException(resp.content, extra=resp)
        return series

    def drop_series(self, serie):
        params = copy.copy(self.GET_PARAMS)
        params.update({'u': 'root', 'p': 'root'})
        params.update({'q': 'drop series "{}";'.format(serie)})
        try:
            resp = requests.get(self.URLS['QUERY'], params=params, timeout=self.read_timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            self.log.error('Cannot connect to influxdb, timeout ({}s)'.format(self.read_timeout))
            raise
        if resp.status_code not in self.OK_STATUSES:
            raise InfluxStorageException(resp.content, extra=resp)
        return True

    def select(self, table, fields=None, limit=None, where=None):
        if not fields:
            fields_s = "*"
        else:
            fields_s = ','.join(fields)
        query = 'select {fields} from "{table}"'.format(fields=fields_s, table=table)
        if where:
            query += " where {}".format(where)
        if limit:
            query += " limit {}".format(limit)
        query += ";"

        params = copy.copy(self.GET_PARAMS)
        params.update({'q': query})
        try:
            resp = requests.get(self.URLS['QUERY'], params=params, timeout=self.read_timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            self.log.error('Cannot connect to influxdb, timeout ({}s)'.format(self.read_timeout))
            raise
        if resp.status_code not in self.OK_STATUSES:
            raise InfluxStorageException(resp.content, extra=resp)

        result = None
        try:
            data = ujson.loads(resp.content)
            columns = data[0].get('columns', [])
            result = [dict(zip(columns, x)) for x in data[0].get('points')]
        except:
            return None

        return result


class MetricsStorage(InfluxStorage):
    METRIC_TABLE_NAME_TPL = 'metric-{}.raw'

    def __init__(self):
        super(MetricsStorage, self).__init__(db='robonect-metrics', shard_config={'default': SETTINGS.SHARD_CONFIG})

    def store_metric(self, metric, value, time=None):
        if time:
            fields = ('value', 'time')
            values = (value, datetime_to_timestamp(time))
        else:
            fields = ('value', )
            values = (value, )
        return self._store_values(table=self.METRIC_TABLE_NAME_TPL.format(metric),
                          fields=fields,
                          values=(values,))

    def query_metric(self, metric, limit=None, where=None):
        table = 'metric-{}.raw'.format(metric)
        return self.select(table=table, fields=('value',), limit=limit, where=where)


class LoggingStorage(InfluxStorage):
    table_name = 'log'

    def __init__(self):
        super(LoggingStorage, self).__init__(db='robonect-logging', shard_config={'default': SETTINGS.LOGGING_SHARD_CONFIG})

    def error(self, message, extra=None, object_type=None, object_id=None):
        self.emit("ERROR", message, extra, object_type, object_id)

    def info(self, message, extra=None, object_type=None, object_id=None):
        self.emit("INFO", message, extra, object_type, object_id)

    def warning(self, message, extra=None, object_type=None, object_id=None):
        self.emit("WARNING", message, extra, object_type, object_id)

    def emit(self, level, message, extra=None, object_type=None, object_id=None):
        fields = ['level', 'message']
        values = [level, message]
        if extra:
            fields += ['extra']
            values += [extra]
        if object_type and object_id:
            fields += ['object_type', 'object_id']
            values += [object_type, object_id]
        return self._store_values(table=self.table_name,
                          fields=fields,
                          values=(values,))
