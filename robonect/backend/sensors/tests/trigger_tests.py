import asyncio
import mock
import pickle
import unittest

from storage import redis
from sensors.trigger import Trigger
from sensors.tests.base import AsyncTestCase, async, mock_coroutine


class TriggerTestCase(AsyncTestCase):

    def setUp(self):
        super(TriggerTestCase, self).setUp()
        self.trigger = Trigger()
        self.trigger.tq_storage = mock.Mock()
        self.trigger.connection = mock.Mock()
        self.trigger.db_log = mock.Mock()

    def test_check_condition(self):
        """ Test check_condition method """
        # Numerical valid test
        self.assertTrue(self.trigger.check_condition('id', '20', 'gt', 42))
        self.assertTrue(self.trigger.check_condition('id', '20.22', 'gte', 42))
        self.assertTrue(self.trigger.check_condition('id', '42', 'gte', 42))
        self.assertTrue(self.trigger.check_condition('id', '200.1', 'lt', 42.1))
        self.assertTrue(self.trigger.check_condition('id', '200.12', 'lte', 42.1))
        self.assertTrue(self.trigger.check_condition('id', '42', 'lte', 42))
        self.assertTrue(self.trigger.check_condition('id', '42', 'eq', 42))
        self.assertTrue(self.trigger.check_condition('id', '24', 'neq', 42))

        self.assertTrue(self.trigger.check_condition('id', '20', 'gt', "42"))

        self.assertFalse(self.trigger.check_condition('id', '200', 'gt', 42))
        self.assertFalse(self.trigger.check_condition('id', '200', 'gte', 42))
        self.assertFalse(self.trigger.check_condition('id', '20', 'lt', 42))
        self.assertFalse(self.trigger.check_condition('id', '20', 'lte', 42))
        self.assertFalse(self.trigger.check_condition('id', '24', 'eq', 42))
        self.assertFalse(self.trigger.check_condition('id', '42', 'neq', 42))

        # Strings test
        self.assertTrue(self.trigger.check_condition('id', 'sub', 'contains', "this is substring container"))
        self.assertTrue(self.trigger.check_condition('id', '42', 'ncontains', "this is substring container"))
        self.assertTrue(self.trigger.check_condition('id', 'mystring', 'exact', "mystring"))
        self.assertTrue(self.trigger.check_condition('id', '42', 'exact', "42"))

        self.assertFalse(self.trigger.check_condition('id', '42', 'contains', "this is substring container"))
        self.assertFalse(self.trigger.check_condition('id', 'sub', 'ncontains', "this is substring container"))
        self.assertFalse(self.trigger.check_condition('id', 'not mystring', 'exact', "mystring"))
        self.assertFalse(self.trigger.check_condition('id', '24', 'exact', "42"))

        # Boolean tests
        self.assertTrue(self.trigger.check_condition('id', None, 'isTrue', True))
        self.assertTrue(self.trigger.check_condition('id', None, 'isFalse', False))

        # Если значение можно привести к целому и потом к boolean — то хорошо
        # (по хорошему мы принимаем только "1" и "0" типа)
        self.assertTrue(self.trigger.check_condition('id', None, 'isTrue', 42))
        self.assertTrue(self.trigger.check_condition('id', None, 'isTrue', "1"))
        self.assertTrue(self.trigger.check_condition('id', None, 'isFalse', "0"))
        self.assertTrue(self.trigger.check_condition('id', None, 'isFalse', "0"))

        self.assertFalse(self.trigger.check_condition('id', None, 'isTrue', "test"))
        self.assertFalse(self.trigger.check_condition('id', None, 'isTrue', False))
        self.assertFalse(self.trigger.check_condition('id', None, 'isFalse', True))

        # Check wrong input
        # We waiting for number, not string!
        self.assertFalse(self.trigger.check_condition('id', '42', 'eq', "me"))
        self.assertFalse(self.trigger.check_condition('id', 'me', 'eq', 42))
        self.assertFalse(self.trigger.check_condition('id', 'me', 'eq', None))
        self.assertFalse(self.trigger.check_condition('id', None, 'eq', 42))

        self.assertFalse(self.trigger.check_condition('id', 'sub', 'contains', 42))
        self.assertFalse(self.trigger.check_condition('id', 'sub', 'exact', 42))


        self.assertFalse(self.trigger.check_condition('id', '42', 'fake', "42"))

    @async
    def test_reload_triggers(self):
        """ Test reload triggers """
        with mock.patch.object(redis.ConfigStorage, 'list_triggers', return_value={}) as m:
            yield from self.trigger._reload_triggers()
            self.assertEquals(len(self.trigger.triggers), 0)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers.keys()), 0)

        triggers = {'T1': {'title': 'T1', 'conditions': [{'metric_id': 'M1', 'function': 'eq', 'value': '1'}]}}
        with mock.patch.object(redis.ConfigStorage, 'list_triggers', return_value=triggers) as m:
            yield from self.trigger._reload_triggers()
            self.assertEquals(len(self.trigger.triggers), 1)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers.keys()), 1)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers['M1']), 1)

        triggers = {'T1': {'title': 'T1', 'conditions': [{'metric_id': 'M1', 'function': 'eq', 'value': '1'},
                                                         {'metric_id': 'M2', 'function': 'eq', 'value': '2'}]}}
        with mock.patch.object(redis.ConfigStorage, 'list_triggers', return_value=triggers) as m:
            yield from self.trigger._reload_triggers()
            self.assertEquals(len(self.trigger.triggers), 1)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers.keys()), 2)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers['M1']), 1)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers['M2']), 1)

        triggers = {'T1': {'title': 'T1', 'conditions': [{'metric_id': 'M1', 'function': 'eq', 'value': '1'},
                                                         {'metric_id': 'M2', 'function': 'eq', 'value': '2'}]},
                    'T2': {'title': 'T2', 'conditions': [{'metric_id': 'M2', 'function': 'eq', 'value': '3'},
                                                         {'metric_id': 'M3', 'function': 'eq', 'value': '4'}]},}
        with mock.patch.object(redis.ConfigStorage, 'list_triggers', return_value=triggers) as m:
            yield from self.trigger._reload_triggers()
            self.assertEquals(len(self.trigger.triggers), 2)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers.keys()), 3)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers['M1']), 1)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers['M2']), 2)
            self.assertEquals(len(self.trigger.metrics_id_to_triggers['M3']), 1)

    @async
    def test_activate_trigger(self):
        action1 = {'title': 'Выполнить команду', '_id': 'exec', 'params': [{'param': 'Команда', 'value': 'V1'}]}
        action2 = {'title': 'Выполнить команду', '_id': 'act2', 'params': [{'param': 'Команда', 'value': 'V2'}]}
        trigger1 = {'_id': 'T1', 'scenario': [{'action_id': 'exec', 'params': [{'param': 'Команда', 'value': 'V1'}]}]}

        with mock.patch.object(redis.ConfigStorage, 'get_action', return_value=action1) as m1, \
            mock.patch.object(self.trigger.tq_storage, 'create_task', side_effect=mock_coroutine()) as m2, \
            mock.patch.object(self.trigger.tq_storage, 'schedule_task', side_effect=mock_coroutine()) as m3:
            yield from self.trigger._activate_trigger(trigger1)

            self.assertEquals(m1.call_count, 1)
            self.assertEquals(m2.call_count, 1)
            self.assertEquals(m2.call_count, 1)

        trigger2 = {'_id': 'T2', 'scenario': [{'action_id': 'exec', 'params': [{'param': 'Команда', 'value': 'V1'}]},
                                             {'action_id': 'act2', 'params': [{'param': 'Команда', 'value': 'V2'}]},]}
        with mock.patch.object(redis.ConfigStorage, 'get_action', side_effect=[action1, action2]) as m1, \
            mock.patch.object(self.trigger.tq_storage, 'create_task', side_effect=mock_coroutine()) as m2, \
            mock.patch.object(self.trigger.tq_storage, 'schedule_task', side_effect=mock_coroutine()) as m3:

            yield from self.trigger._activate_trigger(trigger2)

            self.assertEquals(m1.call_count, 2)
            self.assertEquals(m2.call_count, 2)
            self.assertEquals(m2.call_count, 2)

            self.assertEquals(m1.call_args_list[0][0][0], 'exec')
            self.assertEquals(m2.call_args_list[0][1]['name'], 'exec')

            self.assertEquals(m1.call_args_list[1][0][0], 'act2')
            self.assertEquals(m2.call_args_list[1][1]['name'], 'act2')


    @async
    def test_check_trigger(self):
        trigger1 = dict(conditions=[{'metric_id': 'M1', 'function': 'eq', 'value': '42'}],
                        scenario=[{'action_id': 'exec', 'params': [{'param': 'Команда', 'value': 'V1'}]}],
                        depends_on={'M1'})
        self.trigger.triggers['t1'] = trigger1
        last_values = {'M1': 42}

        # Should be triggered, then not triggered
        with mock.patch.object(self.trigger.tq_storage, 'get_metric_last_values', side_effect=mock_coroutine([last_values]*9)) as last_values_mock, \
            mock.patch.object(self.trigger.tq_storage, 'lock_trigger', side_effect=mock_coroutine(range(1,10))) as lock_mock, \
            mock.patch.object(self.trigger.tq_storage, 'unlock_trigger') as unlock_mock, \
            mock.patch.object(self.trigger, '_activate_trigger', side_effect=mock_coroutine()) as activate_trigger:

            # Should be triggered and locked
            yield from self.trigger.check_trigger('t1', 'M1')
            self.assertEquals(last_values_mock.call_count, 1)
            self.assertEquals(lock_mock.call_count, 1)
            self.assertEquals(unlock_mock.call_count, 0)
            self.assertEquals(activate_trigger.call_count, 1)

            for i in range(2, 10):
                yield from self.trigger.check_trigger('t1', 'M1')
                self.assertEquals(last_values_mock.call_count, i)
                self.assertEquals(lock_mock.call_count, i)
                self.assertEquals(unlock_mock.call_count, 0)
                self.assertEquals(activate_trigger.call_count, 1)

        # Should be never triggered
        last_values = {'M1': 24}
        with mock.patch.object(self.trigger.tq_storage, 'get_metric_last_values', side_effect=mock_coroutine([last_values]*9)) as last_values_mock, \
            mock.patch.object(self.trigger.tq_storage, 'lock_trigger', side_effect=mock_coroutine(range(2,11))) as lock_mock, \
            mock.patch.object(self.trigger.tq_storage, 'unlock_trigger') as unlock_mock, \
            mock.patch.object(self.trigger, '_activate_trigger', side_effect=mock_coroutine()) as activate_trigger:

            # Should be triggered and locked
            yield from self.trigger.check_trigger('t1', 'M1')
            self.assertEquals(last_values_mock.call_count, 1)
            self.assertEquals(lock_mock.call_count, 0)
            self.assertEquals(unlock_mock.call_count, 1)
            self.assertEquals(activate_trigger.call_count, 0)

            for i in range(2, 10):
                yield from self.trigger.check_trigger('t1', 'M1')
                self.assertEquals(last_values_mock.call_count, i)
                self.assertEquals(lock_mock.call_count, 0)
                self.assertEquals(unlock_mock.call_count, i)
                self.assertEquals(activate_trigger.call_count, 0)

        # Lock, unlock, lock test
        last_values = [{'M1': 42}, {'M1': 24}, {'M1': 42}]
        lock_trigger = [1, 0, 1]
        with mock.patch.object(self.trigger.tq_storage, 'get_metric_last_values', side_effect=mock_coroutine(last_values)) as last_values_mock, \
            mock.patch.object(self.trigger.tq_storage, 'lock_trigger', side_effect=mock_coroutine(lock_trigger)) as lock_mock, \
            mock.patch.object(self.trigger.tq_storage, 'unlock_trigger') as unlock_mock, \
            mock.patch.object(self.trigger, '_activate_trigger', side_effect=mock_coroutine()) as activate_trigger:

            # Should be triggered and locked
            yield from self.trigger.check_trigger('t1', 'M1')
            self.assertEquals(last_values_mock.call_count, 1)
            self.assertEquals(lock_mock.call_count, 1)
            self.assertEquals(unlock_mock.call_count, 0)
            self.assertEquals(activate_trigger.call_count, 1)

            # Unlocked
            yield from self.trigger.check_trigger('t1', 'M1')
            self.assertEquals(last_values_mock.call_count, 2)
            self.assertEquals(lock_mock.call_count, 1)
            self.assertEquals(unlock_mock.call_count, 1)
            self.assertEquals(activate_trigger.call_count, 1)

            # Locked
            yield from self.trigger.check_trigger('t1', 'M1')
            self.assertEquals(last_values_mock.call_count, 3)
            self.assertEquals(lock_mock.call_count, 2)
            self.assertEquals(unlock_mock.call_count, 1)
            self.assertEquals(activate_trigger.call_count, 2)

