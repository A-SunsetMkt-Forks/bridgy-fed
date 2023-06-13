"""Unit tests for protocol.py."""
from unittest.mock import patch

from flask import g
from oauth_dropins.webutil.testutil import requests_response
import requests

# import first so that Fake is defined before URL routes are registered
from .testutil import Fake, TestCase

from activitypub import ActivityPub
from app import app
from models import Follower, Object, PROTOCOLS, User
from protocol import Protocol
from web import Web

from .test_activitypub import ACTOR, REPLY

REPLY = {
    **REPLY,
    'actor': ACTOR,
    'object': {
        **REPLY['object'],
        'author': ACTOR,
    },
}


class ProtocolTest(TestCase):

    def setUp(self):
        super().setUp()
        self.user = self.make_user('foo.com', has_hcard=True)
        self.request_context.push()
        g.user = None

    def tearDown(self):
        self.request_context.pop()
        super().tearDown()

    def test_protocols_global(self):
        self.assertEqual(Fake, PROTOCOLS['fake'])
        self.assertEqual(Web, PROTOCOLS['web'])
        self.assertEqual(Web, PROTOCOLS['webmention'])

    def test_for_domain_for_request(self):
        for domain, protocol in [
                ('fake.brid.gy', Fake),
                ('ap.brid.gy', ActivityPub),
                ('activitypub.brid.gy', ActivityPub),
                ('web.brid.gy', Web),
                (None, None),
                ('', None),
                ('brid.gy', None),
                ('www.brid.gy', None),
                ('fed.brid.gy', None),
                ('fake.fed.brid.gy', None),
                ('fake', None),
                ('fake.com', None),
        ]:
            with self.subTest(domain=domain, protocol=protocol):
                self.assertEqual(protocol, Protocol.for_domain(domain))
                with app.test_request_context('/foo', base_url=f'https://{domain}/'):
                    self.assertEqual(protocol, Protocol.for_request())

    def test_for_request_fed(self):
        for base_url in 'https://fed.brid.gy/', 'http://localhost/':
            with app.test_request_context('/foo', base_url=base_url):
                self.assertEqual(Fake, Protocol.for_request(fed=Fake))

        with app.test_request_context('/foo', base_url='https://ap.brid.gy/'):
            self.assertEqual(ActivityPub, Protocol.for_request(fed=Fake))


    @patch('requests.get')
    def test_receive_reply_not_feed_not_notification(self, mock_get):
        Follower.get_or_create(to=Fake.get_or_create(id=ACTOR['id']),
                               from_=Fake.get_or_create(id='foo.com'))
        other_user = self.make_user('user.com', cls=Web)

        # user.com webmention discovery
        mock_get.return_value = requests_response('<html></html>')

        Fake.receive(REPLY['id'], as2=REPLY)

        self.assert_object(REPLY['id'],
                           as2=REPLY,
                           type='post',
                           users=[other_user.key],
                           # not feed since it's a reply
                           # not notification since it doesn't involve the user
                           labels=['activity'],
                           status='complete',
                           source_protocol='fake',
                           )
        self.assert_object(REPLY['object']['id'],
                           as2=REPLY['object'],
                           type='comment',
                           source_protocol='fake',
                           )

    def test_load(self):
        Fake.objects['foo'] = {'x': 'y'}

        loaded = Fake.load('foo')
        self.assert_equals({'x': 'y'}, loaded.our_as1)
        self.assertFalse(loaded.changed)
        self.assertTrue(loaded.new)

        self.assertIsNotNone(Object.get_by_id('foo'))
        self.assertEqual(['foo'], Fake.fetched)

    def test_load_existing(self):
        stored = Object(id='foo', our_as1={'x': 'y'})
        stored.put()

        loaded = Fake.load('foo')
        self.assert_equals({'x': 'y'}, loaded.our_as1)
        self.assertFalse(loaded.changed)
        self.assertFalse(loaded.new)

        self.assertEqual([], Fake.fetched)

    def test_load_existing_empty_deleted(self):
        stored = Object(id='foo', deleted=True)
        stored.put()

        loaded = Fake.load('foo')
        self.assert_entities_equal(stored, loaded)
        self.assertFalse(loaded.changed)
        self.assertFalse(loaded.new)

        self.assertEqual([], Fake.fetched)

    def test_load_refresh_existing_empty(self):
        Fake.objects['foo'] = {'x': 'y'}
        Object(id='foo').put()

        loaded = Fake.load('foo', refresh=True)
        self.assertEqual({'x': 'y'}, loaded.as1)
        self.assertTrue(loaded.changed)
        self.assertFalse(loaded.new)
        self.assertEqual(['foo'], Fake.fetched)

    def test_load_refresh_new_empty(self):
        Fake.objects['foo'] = None
        Object(id='foo', our_as1={'x': 'y'}).put()

        loaded = Fake.load('foo', refresh=True)
        self.assertIsNone(loaded.as1)
        self.assertTrue(loaded.changed)
        self.assertFalse(loaded.new)
        self.assertEqual(['foo'], Fake.fetched)

    def test_load_refresh_unchanged(self):
        obj = Object(id='foo', our_as1={'x': 'stored'})
        obj.put()
        Fake.objects['foo'] = {'x': 'stored'}

        loaded = Fake.load('foo', refresh=True)
        self.assert_entities_equal(obj, loaded)
        self.assertFalse(obj.changed)
        self.assertFalse(obj.new)
        self.assertEqual(['foo'], Fake.fetched)

    def test_load_refresh_changed(self):
        Object(id='foo', our_as1={'content': 'stored'}).put()
        Fake.objects['foo'] = {'content': 'new'}

        loaded = Fake.load('foo', refresh=True)
        self.assert_equals({'content': 'new'}, loaded.our_as1)
        self.assertTrue(loaded.changed)
        self.assertFalse(loaded.new)
        self.assertEqual(['foo'], Fake.fetched)
