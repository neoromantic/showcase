import datetime
import mock

from sensors.metrics import MetricsCollector
from sensors.tests.base import AsyncTestCase, async, mock_coroutine


class MetricsCollectorTestCase(AsyncTestCase):

    def setUp(self):
        super(MetricsCollectorTestCase, self).setUp()
        self.metrics = MetricsCollector()
        self.metrics.connection = mock.Mock()
        self.metrics.metrics_storage = mock.Mock()

        self.metrics.db_log = mock.Mock()

    def test_cast_to_boolean(self):
        """ Test cast_to_boolean method """
        # Numerical valid test
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='gt', value='20'), "42"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='gte', value='20.22'), "42"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='gte', value='42'), "42"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='lt', value='200.1'), "42.1"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='lte', value='200.12'), "42.1"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='lte', value='42'), "42"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='eq', value='42'), "42"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='neq', value='24'), "42"))

        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='gt', value='200'), "42"))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='gte', value='200'), "42"))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='lt', value='20'), "42"))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='lte', value='20'), "42"))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='eq', value='24'), "42"))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='neq', value='42'), "42"))

        # Strings test
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='contains', value='sub'), "this is substring container"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='ncontains', value='42'), "this is substring container"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='exact', value='mystring'), "mystring"))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='exact', value='42'), "42"))

        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='contains', value='42'), "this is substring container"))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='ncontains', value='sub'), "this is substring container"))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='exact', value='not mystring'), "mystring"))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='exact', value='24'), "42"))

        # Boolean tests
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='isTrue', value=None), True))
        self.assertTrue(self.metrics.cast_to_boolean('id', dict(function='isFalse', value=None), False))

        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='isTrue', value=None), False))
        self.assertFalse(self.metrics.cast_to_boolean('id', dict(function='isFalse', value=None), True))

        # Check wrong input
        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(function='eq', value='42'), "me"))
        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(function='eq', value='me'), "42"))
        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(function='eq', value=None), "42"))
        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(function='eq', value='me'), None))

        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(function='contains', value='sub'), 42))
        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(function='exact', value='sub'), 42))

        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(function='isTrue', value=None), 42))

        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(function='fake', value='42'), "42"))

        self.assertIsNone(self.metrics.cast_to_boolean('id', dict(), "42"))

    def test_parse_value(self):
        metric = {}
        stdout = "This is full string"
        self.assertEquals(self.metrics.parse_value(metric, stdout), stdout)

        metric = {'line_regexp': '\d'}
        stdout = "First line\nActive 2 line\nThird line"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'Active 2 line')

        metric = {'line_regexp': '\d', 'line_numbers': "3"}
        stdout = "First line\nActive 2 line\nThird line"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'Active 2 line\nThird line')

        metric = {'line_numbers': "3"}
        stdout = "First line\nActive 2 line\nThird line"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'Third line')

        metric = {'line_numbers': "1"}
        stdout = "First line\nActive 2 line\nThird line\nLine no4"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'First line')

        metric = {'line_numbers': "1,2"}
        stdout = "First line\nActive 2 line\nThird line\nLine no4"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'First line\nActive 2 line')

        metric = {'line_numbers': "1:2"}
        stdout = "First line\nActive 2 line\nThird line\nLine no4"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'First line\nActive 2 line')

        metric = {'line_numbers': "1:3"}
        stdout = "First line\nActive 2 line\nThird line\nLine no4"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'First line\nActive 2 line\nThird line')

        metric = {'line_numbers': "1:3,3"}
        stdout = "First line\nActive 2 line\nThird line\nLine no4"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'First line\nActive 2 line\nThird line')

        metric = {'word_regexp': '(\d+)'}
        stdout = "This is full string\nhello, 42, world!\nagain 100\n"
        self.assertEquals(self.metrics.parse_value(metric, stdout), '42')

        metric = {'word_regexp': '(\d+)', 'word_numbers': '1'}
        stdout = "This is full string\nhello, 42, world!\nagain 100\n"
        self.assertEquals(self.metrics.parse_value(metric, stdout), '42')

        metric = {'word_numbers': '1'}
        stdout = "This is full string\nhello, 42, world!\nagain 100\n"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'This')

        metric = {'word_numbers': '1:6', 'line_numbers': '1'}
        stdout = "This   is:full-string\nhello, 42, world!\nagain 100\n"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'This   is:full-string')

        metric = {'word_numbers': '1:27', 'line_numbers': '1'}
        stdout = "a a\t\t\tb(c)c.d:e=f,g%h/i\\j-k[l]m zzz aaa\nnew line"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'a a\t\t\tb(c)c.d:e=f,g%h/i\\j-k[l]m')

        metric = {'word_numbers': '1:3', 'line_numbers': '1'}
        stdout = "a : b c"
        self.assertEquals(self.metrics.parse_value(metric, stdout), 'a : b')


    def test_parse_values_regression(self):
        metric = {'line_numbers': '1', 'action_id': 'Ynzor5eXB5gtnKXBN', 'createdAt': {'$date': 1408994904884}, '_id': '3cwmearjuysoGpDg5', 'word_numbers': 1, 'title': 'Количество процессов'}
        stdout = '97'
        self.assertEquals(self.metrics.parse_value(metric, stdout), '97')

        stdout = 'RX bytes:3718409748 (3.7 GB) TX bytes:1118099075 (1.1 GB)'
        metric2 = {'line_numbers': '1', 'action_id': 'A2', 'createdAt': {'$date': 1408994904884}, '_id': 'M2', 'word_numbers': 4, 'title': 'RX'}
        metric3 = {'line_numbers': '1', 'action_id': 'A3', 'createdAt': {'$date': 1408994904884}, '_id': 'M3', 'word_numbers': 14, 'title': 'TX'}
        metric4 = {'line_numbers': '1', 'action_id': 'A3', 'createdAt': {'$date': 1408994904884}, '_id': 'M3', 'word_numbers': '14:14', 'title': 'TX'}
        metric5 = {'line_numbers': '1', 'action_id': 'A3', 'createdAt': {'$date': 1408994904884}, '_id': 'M3', 'word_numbers': '14:9999', 'title': 'TX'}
        self.assertEquals(self.metrics.parse_value(metric2, stdout), '3718409748')
        self.assertEquals(self.metrics.parse_value(metric3, stdout), '1118099075')
        self.assertEquals(self.metrics.parse_value(metric4, stdout), '1118099075')
        self.assertEquals(self.metrics.parse_value(metric5, stdout), '1118099075 (1.1 GB)')

    def test_parse_values_regression_2(self):
        metric = {'type': 'string',
                    'title': 'Контроль перезагрузки роутера',
                    'createdAt': {'$date': 1409885489743},
                    'connection_id': 'HgoBiz58GJYNiTAy2',
                    '_id': 'NEk39dD8pGprHYeNE',
                    'line_regexp': 'ZELAX, BIOS v4.2, E',
                    'line_numbers': '',
                    'function': 'eq',
                    'value': 'ZELAX, BIOS v4.2, E',
                    'aggregate': 'mean',
                    'word_regexp': '(.*)'}

        self.assertEquals(self.metrics.parse_value(metric, "Hello, world"), None)
        self.assertEquals(self.metrics.parse_value(metric, "ZELAX, BIOS v4.2, E"), "ZELAX, BIOS v4.2, E")
        self.assertEquals(self.metrics.parse_value(metric, "---ZELAX, BIOS v4.2, E"), "---ZELAX, BIOS v4.2, E")
        self.assertEquals(self.metrics.parse_value(metric, "ZELAX, BIOS v4.2, E---"), "ZELAX, BIOS v4.2, E---")
        self.assertEquals(self.metrics.parse_value(metric, "Zelax, BIOS v4.2, E---"), None)

    def test_parse_values_regression_3(self):
        """ Added ' and " to words split regexp """
        metric = {'value': 'Overture-24',
                  'function': 'exact',
                  'title': 'snmp trap test',
                  'word_numbers': '22:24',
                  '_id': 'TxwLjtj8zJFXL8pNm',
                  'action_id': 'YoZBHpvnQLygv2DBB',
                  'line_numbers': '1',
                  'createdAt': {'$date': 1421858461816},
                  'numeric_id': 314055758,
                  'aggregate': 'sum',
                  'limit_duplicate_save': '24h',
                  'type': 'boolean'}

        self.assertEquals(self.metrics.parse_value(metric, 'iso.3.6.1.2.1.1.1.0 = STRING: "Overture-24"\nSNMP trap has been sent'), "Overture-24")
        self.assertEquals(self.metrics.parse_value(metric, "iso.3.6.1.2.1.1.1.0 = STRING: 'Overture-24'\nSNMP trap has been sent"), "Overture-24")

    def test_parse_values_regression_4(self):
        metric = {'numeric_id': 403862830,
                    'action_id': 'T9x2CSiJeTgyf7nHz',
                    'value': 'FastEthernet0/17 is up, line protocol is up (connected)',
                    'type': 'boolean',
                    '_id': 'Qid79SKC2gbwK2YiP',
                    'line_numbers': '5',
                    'function': 'contains',
                    'createdAt': {'$date': 1421858419520},
                    'title': 'test',
                    'aggregate': 'sum',
                    'limit_duplicate_save': ''}

        value = """cisco2950>enable

terminal length 0
show interface fastethernet 0/24
FastEthernet0/24 is up, line protocol is up (connected)
   Hardware is Fast Ethernet, address is 000a.b758.0a18 (bia 000a.b758.0a18)
   MTU 1500 bytes, BW 100000 Kbit, DLY 100 usec,
       reliability 255/255, txload 1/255, rxload 1/255
   Encapsulation ARPA, loopback not set
   Keepalive set (10 sec)
   Full-duplex, 100Mb/s, media type is 100BaseTX
   input flow-control is unsupported output flow-control is unsupported 
"""

        self.assertEquals(self.metrics.parse_value(metric, value), "FastEthernet0/24 is up, line protocol is up (connected)")




    def test_parse_values_regression_5(self):
        """ Added -\d+ support into words split regexp """
        metric = {'value': 'Overture-24',
                  'function': 'exact',
                  'title': 'snmp trap test',
                  'word_numbers': '4',
                  '_id': 'TxwLjtj8zJFXL8pNm',
                  'action_id': 'YoZBHpvnQLygv2DBB',
                  'line_numbers': '1',
                  'createdAt': {'$date': 1421858461816},
                  'numeric_id': 314055758,
                  'aggregate': 'sum',
                  'limit_duplicate_save': '24h',
                  'type': 'boolean'}

        self.assertEquals(self.metrics.parse_value(metric, 'hello, world! -42" is here'), "-42")

    @async
    def test_store_metric_value(self):
        self.metrics.metrics = {'M1': {'word_regexp': '(\d+)', 'line_numbers': '2', 'type': 'integer', 'multiplier': '10'}}
        task = {'run_at': datetime.datetime.now(), 'id': 'T1'}
        values = {'stdout': "Line 1\nline number 42\nline 3"}

        with mock.patch.object(self.metrics.metrics_storage, 'store_metric') as m,\
            mock.patch.object(self.metrics.connection, 'hset', side_effect=mock_coroutine()),\
            mock.patch.object(self.metrics.connection, 'publish', side_effect=mock_coroutine()):
            res = yield from self.metrics.store_metric_value('M1', 'A1', task, values)
            self.assertTrue(res)
            self.assertEquals(m.call_count, 1)
            args, kwargs = m.call_args[0], m.call_args[1]
            self.assertEquals(args[0], 'M1')
            self.assertEquals(args[1], 420.0)
            self.assertEquals(kwargs['time'], task['run_at'])

    def test_negative_numbers(self):
        value = "  a, b c d e-f g-h 1-100 -c - c -1 abc-20 param:-10"
        metric = {'_id': 'robonect:metric:geuRbJfsx449NZoqR',
                  'action_id': 'robonect:action:WFTLgwmz3FLN9szjj',
                  'aggregate': 'mean',
                  'createdAt': {'$date': 1435707943743},
                  'limit_duplicate_save': '24h',
                  'line_numbers': '1',
                  'numeric_id': 803956658,
                  'precision': 2,
                  'title': 'negative test',
                  'type': 'integer',
                  'word_numbers': 25}

        self.assertEquals(self.metrics.parse_value(metric, value), "-10")
