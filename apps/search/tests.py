# -*- coding: utf-8 -*-
import os
import shutil
import time
import datetime
import socket

from django.contrib.sites.models import Site
from django.test.client import Client as TestClient

from mock import patch, Mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import test_utils

from input.urlresolvers import reverse
from feedback import FIREFOX, OPINION_PRAISE, OPINION_ISSUE, OPINION_SUGGESTION
from feedback.models import Opinion
from search import views
from search.client import Client, SearchError
from search.utils import start_sphinx, stop_sphinx, reindex


# TODO(davedash): liberate from Zamboni
class SphinxTestCase(test_utils.TransactionTestCase):
    """
    This test case type can setUp and tearDown the sphinx daemon.  Use this
    when testing any feature that requires sphinx.
    """

    fixtures = ('feedback/opinions',)
    sphinx = True
    sphinx_is_running = False

    def setUp(self):
        super(SphinxTestCase, self).setUp()

        from django.conf import settings
        settings.SITE_ID = settings.DESKTOP_SITE_ID

        if not SphinxTestCase.sphinx_is_running:
            if (not settings.SPHINX_SEARCHD or
                not settings.SPHINX_INDEXER):  # pragma: no cover
                raise SkipTest()

            os.environ['DJANGO_ENVIRONMENT'] = 'test'

            if os.path.exists(settings.TEST_SPHINX_CATALOG_PATH):
                shutil.rmtree(settings.TEST_SPHINX_CATALOG_PATH)
            if os.path.exists(settings.TEST_SPHINX_LOG_PATH):
                shutil.rmtree(settings.TEST_SPHINX_LOG_PATH)

            os.makedirs(settings.TEST_SPHINX_LOG_PATH)
            os.makedirs(settings.TEST_SPHINX_CATALOG_PATH)

            reindex()
            start_sphinx()
            time.sleep(1)
            SphinxTestCase.sphinx_is_running = True

    @classmethod
    def tearDownClass(cls):
        if SphinxTestCase.sphinx_is_running:
            stop_sphinx()
            SphinxTestCase.sphinx_is_running = False

query = lambda x='', **kwargs: Client().query(x, **kwargs)
num_results = lambda x='', **kwargs: len(query(x, **kwargs))


class SearchTest(SphinxTestCase):

    def test_query(self):
        eq_(num_results(), 31)

    def test_url_search(self):
        eq_(num_results('url:*'), 7)

    def test_result_set(self):
        rs = query()
        assert isinstance(rs[0], Opinion)

    def test_default_ordering(self):
        """Any query should return results in rev-chron order."""
        r = query()
        dates = [o.created for o in r]
        eq_(dates, sorted(dates, reverse=True), "These aren't revchron.")

        r = query('Firefox')
        dates = [o.created for o in r]
        eq_(dates, sorted(dates, reverse=True), "These aren't revchron.")

    def test_product_filter(self):
        eq_(num_results(product=1), 31)
        eq_(num_results(product=2), 0)

    def test_version_filter(self):
        eq_(num_results(version='3.6.3'), 11)
        eq_(num_results(version='3.6.4'), 16)

    def test_type_filter(self):
        eq_(num_results(type=OPINION_PRAISE), 17)
        eq_(num_results(type=OPINION_ISSUE), 11)
        eq_(num_results(type=OPINION_SUGGESTION), 3)

    def test_os_filter(self):
        eq_(num_results(os='mac'), 31)
        eq_(num_results(os='palm'), 0)

    def test_locale_filter(self):
        eq_(num_results(locale='en-US'), 29)
        eq_(num_results(locale='de'), 1)
        eq_(num_results(locale='unknown'), 1)

    def test_date_filter(self):
        start = datetime.datetime(2010, 5, 27)
        end = datetime.datetime(2010, 5, 27)
        eq_(num_results(date_start=start, date_end=end), 5)

    @patch('search.client.sphinx.SphinxClient.RunQueries')
    def test_errors(self, sphinx):
        for error in (socket.timeout(), Exception(),):
            sphinx.side_effect = error
            self.assertRaises(SearchError, query)

    @patch('search.client.sphinx.SphinxClient.GetLastError')
    def test_getlasterror(self, sphinx):
        sphinx = lambda: True
        self.assertRaises(SearchError, query)


def search_request(product='firefox', **kwargs):
    kwargs['product'] = product
    kwargs['date_start'] = '2010-01-01'
    return TestClient().get(reverse('search'), kwargs, follow=True)


class SearchViewTest(SphinxTestCase):
    """Tests relating to the search template rendering."""

    def test_pagination_max(self):
        r = search_request(page=700)
        self.failUnlessEqual(r.status_code, 200)

    def test_page_2(self):
        r = search_request()
        doc = pq(r.content)
        firstmsg = doc('.message').eq(1).text()
        r = search_request(page=2)
        doc = pq(r.content)
        eq_(len(doc('.message')), 11)
        self.assertNotEqual(firstmsg, doc('.message').eq(1).text())

    @patch('search.views._get_results')
    def test_error(self, get_results):
        get_results.side_effect = SearchError()
        r = search_request()
        eq_(r.status_code, 500)

    def test_atom_link(self):
        r = search_request()
        doc = pq(r.content)
        eq_(len(doc('link[type="application/atom+xml"]')), 1)

    def test_flipped_date_filter(self):
        """No error if start > end."""
        r = search_request(date_start='2010-09-01', date_end='2010-06-01')
        eq_(r.status_code, 200)

    def test_carets(self):
        """Rotten queries should not phase us."""
        r = search_request(q='^')
        eq_(r.status_code, 200)



class FeedTest(SphinxTestCase):
    def test_invalid_form(self):
        # Sunbird is always the wrong product.
        r = self.client.get(reverse('search.feed'), {'search': 'sunbird'},
                            True)
        self.failUnlessEqual(r.status_code, 200)

    def test_title(self):
        r = self.client.get(reverse('search.feed'),
                            {'product': 'firefox', 'q': 'lol'})
        doc = pq(r.content.replace('xmlns', 'xmlnamespace'))
        eq_(doc('title').text(), "Firefox Input: 'lol'")

    def test_unicode_title(self):
        """Unicode in search queries must not fail. Bug 606001."""
        r = self.client.get(reverse('search.feed'),
                            {'product': 'firefox', 'q': u'é'})
        doc = pq(r.content.replace('xmlns', 'xmlnamespace'))
        eq_(doc('title').text(), u"Firefox Input: 'é'")


    def test_query(self):
        r = self.client.get(reverse('search.feed'),
                            dict(product='firefox',
                                 date_start='01/01/2000',
                                 date_end='01/01/2011'))
        doc = pq(r.content.replace('xmlns', 'xmfail'))
        s = Site.objects.all()[0]
        url_base = 'http://%s/' % s.domain
        eq_(doc('entry link').attr['href'],
            '%s%s' % (url_base, 'en-US/opinion/29'))


def test_get_sentiment():
    r = views.get_sentiment([{'type': OPINION_ISSUE, 'count': 1}])
    eq_(r['sentiment'], 'sad')


@patch('search.forms.ReporterSearchForm.is_valid')
def test_get_results(is_valid):
    is_valid.return_value = False
    request = Mock()
    request.GET = {}
    request.default_app = FIREFOX
    r = views._get_results(request)
    eq_(r[2], request.default_app)
