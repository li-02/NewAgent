from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.db import DB
from src.fetchers import run_source
from src.fetchers.extended import fetch_huggingface, fetch_github_org, fetch_page_watch, fetch_article_index
from src.pipeline.observe import observe, event_time
from src.pipeline.generate import build_material
from src.pipeline.dedup import url_hash
from src.source_config import load_source_config, normalize_source, SourceConfigError

NOW = datetime(2026,9,5, tzinfo=timezone.utc)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'news.db'
        self.db=DB(self.path)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def row(self, text='Original quota: 10', url='https://example.com/limits', mode='content', published=None):
        return dict(title='Limits',url=url,source='Official',summary=text,published=published,
                    _watch_scope='https://example.com',_watch_text=text,_watch_mode=mode)

    def test_baseline_unchanged_and_change_survive_restart(self):
        self.assertEqual(observe([self.row()],self.db,NOW),[])
        self.assertEqual(observe([self.row()],self.db,NOW+timedelta(hours=1)),[])
        changed=observe([self.row('New quota: 20')],self.db,NOW+timedelta(hours=2))[0]
        self.assertIsNone(changed['published'])
        self.assertEqual(event_time(changed),NOW+timedelta(hours=2))
        self.assertIn('-Original quota: 10',changed['text'])
        self.assertIn('+New quota: 20',changed['text'])
        self.db.close(); self.db=DB(self.path)
        repeated=observe([self.row('New quota: 20')],self.db,NOW+timedelta(days=2))[0]
        self.assertEqual(repeated['url'],changed['url'])
        self.assertEqual(event_time(repeated),event_time(changed))
        self.assertLess(event_time(repeated),NOW+timedelta(days=1))

    def test_second_change_same_page_has_new_identity(self):
        observe([self.row()],self.db,NOW)
        a=observe([self.row('quota 20')],self.db,NOW+timedelta(hours=1))[0]
        b=observe([self.row('quota 30')],self.db,NOW+timedelta(hours=2))[0]
        self.assertNotEqual(url_hash(a['url']),url_hash(b['url']))

    def test_discovery_baselines_whole_initial_batch_and_dates_are_preserved(self):
        rows=[self.row(url='https://example.com/a',mode='discovery'),
              self.row(url='https://example.com/b',mode='discovery')]
        self.assertEqual(observe(rows,self.db,NOW),[])
        new=observe([self.row(url='https://example.com/c',mode='discovery')],self.db,NOW)[0]
        self.assertIsNone(new['published'])
        dated=self.row(url='https://example.com/d',mode='discovery',published=NOW-timedelta(days=10))
        self.assertEqual(observe([dated],self.db,NOW)[0]['published'],dated['published'])

    def test_article_edit_does_not_keep_old_publication_time(self):
        old = NOW-timedelta(days=10)
        a = self.row(mode='article',published=old)
        self.assertEqual(observe([a],self.db,NOW)[0]['published'],old)
        b = self.row('Max is now available',mode='article',published=old)
        updated = observe([b],self.db,NOW)[0]
        self.assertIsNone(updated['published'])
        self.assertEqual(updated['original_published'],old)
        self.assertEqual(event_time(updated),NOW)

    def test_plain_undated_is_not_promoted(self):
        it={'title':'Old','url':'https://example.com','published':None}
        self.assertEqual(observe([it],self.db,NOW),[it])
        self.assertIsNone(event_time(it))

    def test_material_preserves_evidence_and_unknown_publication(self):
        it=self.row(); it['observed_at']=NOW; it['evidence_type']='community'
        text=build_material([it])
        self.assertIn('发布时间：未知',text)
        self.assertIn('不代表发布时间',text)
        self.assertIn('未经官方确认',text)


class FetcherTests(unittest.TestCase):
    def test_page_ignores_navigation_and_scripts(self):
        html='<html><nav>Noise</nav><main><article><h1>Model limits</h1><p>'+('Quota 20. '*25)+'</p></article></main><script>noise</script></html>'
        with patch('src.fetchers.extended._request_text',return_value=html):
            row=fetch_page_watch({'name':'Limits','url':'https://example.com'},3)[0]
        self.assertNotIn('Noise',row['_watch_text'])
        self.assertNotIn('noise',row['_watch_text'])
        self.assertEqual(row['_watch_text'].count('Model limits'),1)

    def test_invalid_page_does_not_become_snapshot(self):
        for html in ['<html>Sign in</html>','<main>Loading</main>','<main>captcha</main>']:
            with self.subTest(html=html), patch('src.fetchers.extended._request_text',return_value=html):
                with self.assertRaises((ValueError,RuntimeError)):
                    fetch_page_watch({'name':'Limits','url':'https://example.com'},1)

    def test_article_uses_publication_metadata_not_date_in_body(self):
        index='<a href="/news/model">New model launch</a>'
        article='<html><meta property="article:published_time" content="2026-09-04T12:00:00Z"><article><h1>Model</h1><p>Old event 2020-01-01</p></article></html>'
        with patch('src.fetchers.extended._request_text',side_effect=[index,article]):
            row=fetch_article_index({'url':'https://example.com/news/','link_pattern':r'/news/[^/]+$'},1)[0]
        self.assertEqual(row['published'],datetime(2026,9,4,12,tzinfo=timezone.utc))

    def test_hf_uses_created_not_modified_and_caps_limit(self):
        with patch('src.fetchers.extended._request_json',return_value=[{'id':'inclusionAI/LLaDA','createdAt':'2026-09-04T00:00:00Z','lastModified':'2026-09-05T00:00:00Z'}]) as request:
            row=fetch_huggingface({'url':'https://huggingface.co/inclusionAI'},200)[0]
        self.assertEqual(row['published'],NOW-timedelta(days=1))
        self.assertIn('limit=100',request.call_args.args[0])

    def test_github_excludes_forks(self):
        data=[{'full_name':'org/model','html_url':'https://github.com/org/model','created_at':'2026-09-04T00:00:00Z'}, {'fork':True}]
        with patch('src.fetchers.extended._request_json',return_value=data):
            rows=fetch_github_org({'url':'https://github.com/org'},3)
        self.assertEqual(len(rows),1)

    def test_community_source_marked(self):
        with patch.dict('src.fetchers.FETCHERS',{'test':lambda s,n:[{'title':'Report','url':'https://example.com'}]}):
            row=run_source({'type':'test','name':'Reddit','category':'community'},1)[0]
        self.assertEqual(row['evidence_type'],'community')

    def test_config_registered_and_invalid_selectors_rejected(self):
        config=load_source_config(Path('config/sources.yaml'))
        from src.fetchers import FETCHERS
        for s in config['sources']:
            self.assertIn(s['type'],FETCHERS)
        with self.assertRaises(SourceConfigError):
            normalize_source({'type':'article_index','name':'Bad','url':'https://example.com','link_pattern':'['})
        with self.assertRaises(SourceConfigError):
            normalize_source({'type':'page_watch','name':'Bad','url':'https://example.com','content_xpath':'['})

if __name__=='__main__':unittest.main()

class CatalogAndXTests(unittest.TestCase):
    def test_catalog_filters_provider_before_limit_and_keeps_listing_date(self):
        from src.fetchers.extended import fetch_model_catalog
        models={'data':[{'id':'other/new','created':200}, {'id':'inclusionai/old','created':100}, {'id':'inclusionai/new','created':150}]}
        with patch('src.fetchers.extended._request_json',return_value=models):
            rows=fetch_model_catalog({'url':'https://openrouter.ai/api/v1/models'},1)
        self.assertEqual(rows[0]['url'],'https://openrouter.ai/inclusionai/new')
        self.assertEqual(rows[0]['published'].timestamp(),150)

    def test_x_missing_credentials_is_actionable_and_no_network(self):
        from src.fetchers.extended import fetch_x_account
        with patch.dict('os.environ',{},clear=True), patch('src.fetchers.extended.httpx.Client') as client:
            with self.assertRaisesRegex(ValueError,'X_BEARER_TOKEN'):
                fetch_x_account({'url':'https://x.com/OpenAI'},3)
            client.assert_not_called()
