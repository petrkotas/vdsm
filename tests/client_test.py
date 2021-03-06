#
# Copyright 2015-2017 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#
from contextlib import contextmanager
import logging
import time
import six
from six.moves import queue

try:
    from integration.jsonRpcHelper import constructClient
except:  # Import will fail in python3
    pass

from testlib import \
    VdsmTestCase, \
    dummyTextGenerator

from testValidation import skipif, slowtest

from vdsm.client import \
    _Client, \
    ServerError, \
    TimeoutError

import yajsonrpc
from vdsm.common import exception

CALL_TIMEOUT = 3
EVENT_TIMEOUT = 3
EVENT_TOPIC = "test.events"


class _Bridge(object):
    log = logging.getLogger("tests._TestBridge")
    cif = None

    def register_server_address(self, server_address):
        self.server_address = server_address

    def unregister_server_address(self):
        self.server_address = None

    @property
    def event_schema(self):
        return _FakeEventSchema()

    def dispatch(self, method):
        class_name, method_name = method.split('.', 1)
        if class_name != "Test":
            raise yajsonrpc.JsonRpcMethodNotFoundError(method=method)

        try:
            return getattr(self, method_name)
        except AttributeError:
            raise yajsonrpc.JsonRpcMethodNotFoundError(method=method)

    def echo(self, text):
        self.log.info("ECHO: '%s'", text)
        return text

    def slowCall(self):
        time.sleep(CALL_TIMEOUT + 2)

    def sendEvent(self):
        self.cif.notify('|vdsm|test_event|', {'content': True}, EVENT_TOPIC)

    def failingCall(self):
        raise exception.GeneralException("Test failure")


class _FakeSchema(object):
    get_methods = [
        "Test.echo",
        "Test.slowCall",
        "Test.sendEvent"
    ]


class _FakeEventSchema(object):
    def verify_event_params(self, *args, **kwargs):
        pass


class _MockedClient(_Client):
    # Redefining schema init for testing
    def _init_schema(self, gluster_enabled):
        self._schema = _FakeSchema()
        self._event_schema = _FakeEventSchema()


class VdsmClientTests(VdsmTestCase):

    @contextmanager
    def _create_client(self):
        bridge = _Bridge()
        ssl = True
        with constructClient(self.log, bridge, ssl) as clientFactory:
            json_client = clientFactory()
            try:
                yield _MockedClient(json_client, CALL_TIMEOUT, False)
            finally:
                json_client.close()

    def _get_with_timeout(self, event_queue):
        try:
            return event_queue.get(timeout=EVENT_TIMEOUT)
        except queue.Empty:
            self.fail("Event queue timed out.")

    @skipif(six.PY3, "Needs porting to python 3")
    def test_call(self):
        with self._create_client() as client:
            msg = dummyTextGenerator(1024)
            res = client.Test.echo(text=msg)

            self.assertEqual(msg, res)

    @skipif(six.PY3, "Needs porting to python 3")
    def test_failing_call(self):
        with self._create_client() as client:
            with self.assertRaises(ServerError) as ex:
                client.Test.failingCall()

            self.assertEqual(
                ex.exception.code,
                exception.GeneralException().code
            )
            self.assertIn("Test failure", str(ex.exception))

    @skipif(six.PY3, "Needs porting to python 3")
    def test_missing_method(self):
        with self._create_client() as client:
            with self.assertRaises(ServerError) as ex:
                client.Test.missingMethod()

            self.assertEqual(
                ex.exception.code,
                yajsonrpc.JsonRpcMethodNotFoundError("").code
            )
            self.assertIn("missingMethod", ex.exception.message)

    @skipif(six.PY3, "Needs porting to python 3")
    def test_missing_namespace(self):
        with self._create_client() as client:
            with self.assertRaises(AttributeError):
                client.MissingNamespace.missingMethod()

    @skipif(six.PY3, "Needs porting to python 3")
    def test_bad_parameters(self):
        with self._create_client() as client:
            with self.assertRaises(ServerError) as ex:
                client.Test.echo()

            self.assertEqual(
                ex.exception.code,
                yajsonrpc.JsonRpcInternalError().code
            )

    @skipif(six.PY3, "Needs porting to python 3")
    @slowtest
    def test_slow_call(self):
        with self._create_client() as client:
            with self.assertRaises(TimeoutError):
                client.Test.slowCall()

    @skipif(six.PY3, "Needs porting to python 3")
    def test_event_handler(self):
        with self._create_client() as client:
            event_queue = queue.Queue()

            sub_id = client.subscribe(EVENT_TOPIC, event_queue)
            client.Test.sendEvent()

            ev, ev_params = self._get_with_timeout(event_queue)
            self.assertEqual(ev, '|vdsm|test_event|')
            self.assertEqual(ev_params['content'], True)

            client.unsubscribe(sub_id)
            self.assertEqual(
                self._get_with_timeout(event_queue),
                None
            )

    @skipif(six.PY3, "Needs porting to python 3")
    def test_multiple_queues(self):
        with self._create_client() as client:
            event_queue1 = queue.Queue()
            event_queue2 = queue.Queue()

            sub_id_1 = client.subscribe(EVENT_TOPIC, event_queue1)
            sub_id_2 = client.subscribe(EVENT_TOPIC, event_queue2)

            client.Test.sendEvent()

            ev, ev_params = self._get_with_timeout(event_queue1)
            self.assertEqual(ev, '|vdsm|test_event|')
            self.assertEqual(ev_params['content'], True)

            ev, ev_params = self._get_with_timeout(event_queue2)
            self.assertEqual(ev, '|vdsm|test_event|')
            self.assertEqual(ev_params['content'], True)

            client.unsubscribe(sub_id_1)
            client.unsubscribe(sub_id_2)
            self.assertEqual(
                self._get_with_timeout(event_queue1),
                None
            )
            self.assertEqual(
                self._get_with_timeout(event_queue2),
                None
            )

    @skipif(six.PY3, "Needs porting to python 3")
    @slowtest
    def test_unsubscribe(self):
        with self._create_client() as client:
            event_queue = queue.Queue()

            sub_id = client.subscribe(EVENT_TOPIC, event_queue)
            client.unsubscribe(sub_id)

            client.Test.sendEvent()
            self.assertEqual(
                self._get_with_timeout(event_queue),
                None
            )

    @skipif(six.PY3, "Needs porting to python 3")
    def test_notify(self):
        with self._create_client() as client:
            event_queue = queue.Queue()

            test_topic = "test.topic"
            sub_id = client.subscribe(test_topic, event_queue)
            client.notify('vdsm.event', test_topic, {'content': True})

            ev, ev_params = self._get_with_timeout(event_queue)
            self.assertEqual(ev, 'vdsm.event')
            self.assertEqual(ev_params['content'], True)

            client.unsubscribe(sub_id)
            self.assertEqual(
                self._get_with_timeout(event_queue),
                None
            )
