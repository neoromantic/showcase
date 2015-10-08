import mock
import unittest
from storage.redis import ConfigStorage, ActionResursion


actions_example2 = [{'title': 'Выполнить команду', '_id': 'exec', 'params': [{'param': 'Команда'}], },

                    {'title': 'PING', '_id': 'ping',
                     'params': [{'param': 'Хост'}, {'param': 'Сколько раз'}, {'param': 'Интервал'}],
                     'scenario': [{'action_id': 'exec', 'params': [{'value': 'ping -c $2 -i $3 $1', 'param': 'Команда'}]}]},

                    {'title': 'ping ya.ru', '_id': 'ping-ya-ru', 'schedule': '10s',
                     'scenario': [{'action_id': 'ping', 'params': [{'value': 'ya.ru', 'param': 'Хост'},
                                                                  {'value': '2', 'param': 'Сколько раз'},
                                                                  {'value': '2', 'param': 'Интервал'}, ]}]},

                    {'title': 'ping denyamsk.ru', '_id': 'ping-denyamsk-ru', 'schedule': '1m', 'connection_id': 'CC',
                     'scenario': [{'action_id': 'ping', 'params': [{'value': 'denyamsk.ru', 'param': 'Хост'},
                                                                  {'value': '4', 'param': 'Сколько раз'},
                                                                  {'value': '2', 'param': 'Интервал'}, ]}]},
]

actions_example1 = [{'title': 'Выполнить команду', '_id': 'exec', 'params': [{'param': 'Команда'}], },
                    {'title': 'B1', '_id': 'b1', 'connection_id': 'B1C',
                    'scenario': [{'action_id': 'exec', 'params': [{'value': 'B1_PARAM_VAL', 'param': 'Команда'}]}]},
                    {'title': 'B2', '_id': 'b2', 'params': [{'param': 'B2_PARAM'}], 'connection_id': 'B2C',
                    'scenario': [{'action_id': 'exec', 'params': [{'value': 'xxx $1 yyy', 'param': 'Команда'}]}]},
                    {'title': 'C1', '_id': 'c1', 'schedule': '1u', 'connection_id': 'C1C',
                     'scenario': [{'action_id': 'b1'},
                                {'action_id': 'b2', 'params': [{'value': 'B2_PARAM_VAL', 'param': 'B2_PARAM'}]}]}
]

actions_example3 = [{'title': 'Выполнить команду', '_id': 'exec', 'params': [{'param': 'Команда'}], },
                    {'title': 'B1', '_id': 'b1',
                    'scenario': [{'action_id': 'exec', 'params': [{'value': 'B1_PARAM_VAL', 'param': 'Команда'}]}]},
]

actions_recursion = [{'title': 'B1', '_id': 'b1', 'scenario': [{'action_id': 'b2'}], 'schedule': '1u'},
                     {'title': 'B2', '_id': 'b2', 'scenario': [{'action_id': 'b1'}]},
]

actions_wrong_ref = [{'title': 'B1', '_id': 'b1', 'scenario': [{'action_id': 'no-action'}], 'schedule': '1u'}, ]


send_sms_actions = [
  {'title': 'Выполнить команду', '_id': 'exec', 'params': [{'param': 'Команда'}]},
  {'scenario': [{'action_id': 'Gp5tGsQmfd6Bz425x',
   'params': [{'param': 'Номер телефона', 'value': '+79265225983'},
    {'param': 'Сообщение', 'value': 'test sms'}]}],
 '_id': 'WRkMC5vPiWPjoT7LJ',
 'title': 'Тест СМС',
 'ttl': 30,
 'createdAt': {'$date': 1411725500100},
 'params': []},

{'scenario': [{'action_id': 'exec',
   'params': [{'param': 'Команда', 'value': 'AT+CMGF=1'}]},
  {'action_id': 'exec',
   'params': [{'param': 'Команда', 'value': 'AT+CMGS="$1"'}]},
  {'action_id': 'exec',
   'params': [{'param': 'Команда', 'value': '$2<CTRL+Z>'}]}],
 '_id': 'Gp5tGsQmfd6Bz425x',
 'connection_id': 'HgoBiz58GJYNiTZy4',
 'title': 'Отправить СМС сообщение',
 'ttl': 30,
 'createdAt': {'$date': 1409853615101},
 'params': [{'param': 'Номер телефона', 'value': '+79060876498'},
  {'param': 'Сообщение', 'value': 'Тест'}]}
]


class ConfigStorageTestCase(unittest.TestCase):

    def setUp(self):
        self.storage = ConfigStorage()

    def tearDown(self):
        del self.storage

    def test_parse_action(self):
        """ Test _parse_action method """
        # Example:
        #    o---> B1 ---o
        #   /             \
        # C1               +--> EXEC
        #   \             /
        #    o---> B2 ---o
        #
        actions_dict = {action.get('_id'): action for action in actions_example1}
        result = self.storage._parse_action(actions_dict, actions_dict.get('c1'))

        self.assertEquals(len(result.get('scenario')), 2)
        for (test, action) in zip(('b1', 'b2'), result.get('scenario')):
            # Из айди получился экшн
            self.assertTrue(action.get('action'))
            self.assertTrue(action.get('action').get('_id'), test)

        b1_inner = result.get('scenario')[0].get('action')
        self.assertEquals(len(b1_inner.get('scenario')), 1)
        for action in b1_inner.get('scenario'):
            # Из айди получился экшн
            self.assertTrue(action.get('action'))
            self.assertEquals(action.get('action').get('_id'), 'exec')
            self.assertEquals(action.get('action').get('connection_id'), 'B1C')
        self.assertEquals(b1_inner.get('connection_id'), b1_inner.get('scenario')[0]['action']['connection_id'])

        b2_inner = result.get('scenario')[1].get('action')
        self.assertEquals(len(b2_inner.get('scenario')), 1)
        for action in b2_inner.get('scenario'):
            # Из айди получился экшн
            self.assertTrue(action.get('action'))
            self.assertEquals(action.get('action').get('_id'), 'exec')
            self.assertEquals(action.get('action').get('connection_id'), 'B2C')
        self.assertEquals(b1_inner.get('connection_id'), b1_inner.get('scenario')[0]['action']['connection_id'])

        self.assertEquals(result['scenario'][1]['action']['scenario'][0]['action']['params'][0]['value'], 'xxx B2_PARAM_VAL yyy')

        # Example 2:
        actions_dict = {action.get('_id'): action for action in actions_example2}
        result = self.storage._parse_action(actions_dict, actions_dict.get('ping-ya-ru'))

        self.assertEquals(result['scenario'][0]['action']['scenario'][0]['action']['params'][0]['value'], 'ping -c 2 -i 2 ya.ru')

        # Example 3, empty connection:
        actions_dict = {action.get('_id'): action for action in actions_example3}
        result = self.storage._parse_action(actions_dict, actions_dict.get('b1'))
        self.assertIsNone(result['scenario'][0]['action'].get('connection_id'))

    def test_parse_action_resursion(self):
        actions_dict = {action.get('_id'): action for action in actions_recursion}
        with self.assertRaises(ActionResursion):
            self.storage._parse_action(actions_dict, actions_dict.get('b1'))

    def test_parse_action_wrong_ref(self):
        actions_dict = {action.get('_id'): action for action in actions_wrong_ref}
        with mock.patch.object(self.storage.log, 'error') as m:
            result = self.storage._parse_action(actions_dict, actions_dict.get('b1'))
            self.assertEquals(m.call_count, 1)
        self.assertFalse('action' in result['scenario'][0])

    def test_get_scheduled_actions(self):
        """ Test get_scheduled_actions method """
        # For example1 actions
        with mock.patch('storage.redis.ConfigStorage.get_config', return_value=actions_example1) as m:
            result = self.storage.get_scheduled_actions()
            self.assertEquals(m.call_count, 1)
        self.assertEquals(len(result.items()), 1)
        self.assertTrue('c1' in result)
        self.assertEquals(result['c1']['schedule'], '1u')

        # For actions with recursion
        with mock.patch('storage.redis.ConfigStorage.get_config', return_value=actions_recursion) as m:
            result = self.storage.get_scheduled_actions()
            self.assertEquals(m.call_count, 1)
        self.assertEquals(len(result.items()), 0)

    def test_get_action(self):
        """ Test get_action method """
        with mock.patch('storage.redis.ConfigStorage.get_config', return_value=actions_example1) as m:
            result = self.storage.get_action('c1')
            self.assertEquals(m.call_count, 1)
        self.assertEquals(result['_id'], 'c1')

        with mock.patch('storage.redis.ConfigStorage.get_config', return_value=actions_example1) as m:
            result = self.storage.get_action('no-action')
            self.assertEquals(m.call_count, 1)
        self.assertEquals(result, None)

        with mock.patch('storage.redis.ConfigStorage.get_config', return_value=actions_example1) as m:
            result = self.storage.get_action('exec',
                                             initial_param_values={"Команда": "ps -aux"},
                                             connection_id="C1")
            self.assertEquals(m.call_count, 1)
        self.assertEquals(result['params'][0]['param'], 'Команда')
        self.assertEquals(result['params'][0]['value'], 'ps -aux')
        self.assertEquals(result['connection_id'], 'C1')


    def test_regression_sms(self):
        # action = send_sms_actions['WRkMC5vPiWPjoT7LJ']
        with mock.patch('storage.redis.ConfigStorage.get_config', return_value=send_sms_actions) as m:
            result = self.storage.get_action('WRkMC5vPiWPjoT7LJ')
            self.assertEquals(m.call_count, 1)
        self.assertEquals(result['scenario'][0]['action']['scenario'][0]['action']['params'][0]['value'], 'AT+CMGF=1')
        self.assertEquals(result['scenario'][0]['action']['scenario'][1]['action']['params'][0]['value'], 'AT+CMGS="+79265225983"')
        self.assertEquals(result['scenario'][0]['action']['scenario'][2]['action']['params'][0]['value'], 'test sms<CTRL+Z>')
