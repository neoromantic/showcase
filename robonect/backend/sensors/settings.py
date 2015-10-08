import json
import logging.config
import operator
import os
import re
from collections import namedtuple

__all__ = 'SETTINGS',

SETTINGS_DICT = dict(
    BASE_DIR=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../')),

    SCHEDULED_QUEUE=b'queue:scheduled',
    DISPATCHED_QUEUE=b'queue:dispatched',
    INPROGRESS_QUEUE=b'queue:inprogress',
    INPROGRESS_TASKS_SET=b'queue:set:inprogress',

    LAST_VALUES_HASH=b'robonect:metrics-last_values',  # Store pickled last_value for metrics (key=metric_id)
    TRIGGER_STATES=b'queue:triggers:states',  # Store trigger lock/uncloked state

    WORKER_THROTTLE_LOCKS='queue:actions-throttle:{}',

    TASK_CHANNEL='tasks:{}',
    METRICS_CHANNEL='robonect:metrics-results:{}',
    ACTION_RESULTS_CHANNEL='robonect:actions-results:{}',
    CONNECTION_RESULTS_CHANNEL='robonect:connections-results:{}',
    SCHEDULER_TO_DISPATCHER_CHANNEL=b'queue:scheduler-dispatcher-notifications',
    WORKER_TO_SCHEDULER_CHANNEL=b'queue:worker-scheduler-notifications',

    DISPATCHER_PULL_TIMEOUT=1,
    DISPATCHED_QUEUE_LIMIT=4000,

    SCHEDULER_PULL_TIMEOUT=1,
    SCHEDULER_HISTORY_HASH=b'scheduler:queue:scheduler-tasks-history',
    SCHEDULED_HISTORY_CLEANUP_PERIOD=7200,  # (sec) 2 hours (too often)
    SCHEDULED_HISTORY_CLEANUP_MAX_TTL=1209600,  # (sec) 14 days

    COMPORT_STATE_HASH=b'robonect:comports-state',
    COMPORT_LOCK_HASH=b'robonect:comports-lock',
    COMPORT_SOCKET_HASH=b'robonect:comports-socket',

    TASK_STORAGE_EXPIRE=900,  # 15m
    TASK_STORAGE_KEY='tasks:queue:{}:task',
    TASK_RESULTS_STORAGE_KEY='tasks:queue:{}:result',

    WORKER_BPOP_TIMEOUT=1,  # How long to wait in blocking redis pop (keep small, 'cause it blocks worker loop, block expire tasks, cleanup tasks)
    WORKER_TASK_TIMEOUT=30,  # How long task can be executed, default value for TTL of scheduled action
    WORKER_TASKS_LIMIT=50,  # How many tasks can take worker in parallel processing
    WORKER_PULL_SLEEP=0.05,  # How long to sleep after unsuccesfull blocking pop (50ms)

    METRICS_TYPES_MAP={'string': str,
                       'float': float,
                       'integer': lambda x: int(float(x)),
                       'boolean': bool},
    METRIC_NUMERICAL_TYPES=('float', 'integer'),

    METRIC_STRING_LIMIT = 4096,  # Trim string value of metric to 4096 unicode characters

    # For trigger and metrics
    CONDITIONS_NUMBERIC={'gt', 'gte', 'lt', 'lte', 'eq', 'neq'},
    CONDITIONS_STRINGS={'contains', 'ncontains', 'exact'},
    CONDITIONS_BOOLEAN={'isTrue', 'isFalse'},
    CONDITIONS_CMP_FUNCTIONS={
        'gt': operator.gt,
        'gte': operator.ge,
        'lt': operator.lt,
        'lte': operator.le,
        'eq': operator.eq,
        'neq': operator.ne,
        'contains': operator.contains,
        'ncontains': lambda x, y: not operator.contains(x, y),
        'exact': operator.eq,
        'isTrue': lambda x, y: x is True,
        'isFalse': lambda x, y: x is False,
    },

    SHARD_CONFIG={
        "retentionPolicy": "60d",
        "shardDuration": "7d",
        "regex": "/.*/",
        "replicationFactor": 1,
        "split": 1
    },
    LOGGING_SHARD_CONFIG={
        "retentionPolicy": "7d",
        "shardDuration": "1d",
        "regex": "/.*/",
        "replicationFactor": 1,
        "split": 1
    },

    SYSCONFIG_HASH=b'robonect:sysconfig-values',
    DEVCONFIG=b'robonect:config',
    DEVCONFIG_DATA={'password': '3183a42f31529522641b2296e23ea85723afa8ba',
                    'login_timeout': 30,
                    'username': 'admin',
                    'snmp_prefix': '.1.3.6.1.4.1.43674.2.'},

    UPDATE_FIRMWARE_TIMEOUT=60,
    UPDATE_FIRMWARE_CHECK_SCRIPT='/srv/robonect/robonect/scripts/update/update.sh',
    UPDATE_FIRMWARE_RUN_SCRIPT='sudo /srv/robonect/robonect/do_update.sh 2>&1 >> /data/log/robonect-update.log',

    GSM_RESTART_MODEM_PIN='gpio20',
    GSM_CHECK_MODEM_PIN='gpio26',
    GSM_COMPORT_MODEM_DEV='/dev/ttyPS1',

    BOOTSTRAP_FILE='bootstrap/bootstrap_arm.json',
    BOOTSTRAP_TYPES=('connection', 'action', 'metric', 'trigger', 'widget'),
)

ALLOW_OVERRIDE_SETTINGS = {'GSM_RESTART_MODEM_PIN': r'gpio\d+$',
                           'GSM_CHECK_MODEM_PIN': r'gpio\d+$',
                           'BOOTSTRAP_FILE': r'bootstrap/[\w.-]+$',
                           'GSM_COMPORT_MODEM_DEV': r'/dev/\w+$'}

if os.path.exists('/etc/robonect.conf'):
    try:
        _RAW_LOCAL_SETTINGS = json.loads(open('/etc/robonect.conf').read())
        # Filter keys and validate values by regexp
        LOCAL_SETTINGS = dict(filter(lambda x: x[0] in ALLOW_OVERRIDE_SETTINGS.keys() and re.match(ALLOW_OVERRIDE_SETTINGS[x[0]], x[1]), _RAW_LOCAL_SETTINGS.items()))
        SETTINGS_DICT.update(LOCAL_SETTINGS)
        del _RAW_LOCAL_SETTINGS
    except:
        pass


_type_settings = namedtuple('Settings', SETTINGS_DICT.keys())
SETTINGS = _type_settings(**SETTINGS_DICT)


LOGGING = {
    'version': 1,
    'root': {
        'level': 'WARNING',
        'handlers': ['console'],
    },
    'formatters': {
        'verbose': {
            'format': '[%(levelname)s] %(asctime)s [%(name)s] %(message)s'
        },
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
        },
    },
    'loggers': {
        'taskqueue': {
            'handlers': ['console'],
            'propagate': False,
            'level': 'INFO',
        },
        'robonect': {
            'handlers': ['console'],
            'propagate': False,
            'level': 'INFO',
        },
        'comport': {
            'handlers': ['console'],
            'propagate': False,
            'level': 'INFO',
        },
        'storage': {
            'handlers': ['console'],
            'propagate': False,
            'level': 'INFO',
        },
    }
}

logging.config.dictConfig(LOGGING)
