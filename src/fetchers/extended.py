"""Official article indexes, page changes, model repositories and opt-in X timelines."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx
from lxml import html as lh

from . import register, strip_html
from .html_updates import _request_text, _request_json, _raise_if_blocked


def iso_date(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def content_nodes(raw, xpath=None):
    _raise_if_blocked('page', raw)
    doc = lh.fromstring(raw)
    for el in doc.xpath('//script|//style|//svg|//nav|//footer|//header|//aside'):
        el.drop_tree()
    nodes = doc.xpath(xpath) if xpath else doc.xpath('//article[not(ancestor::article)]')
    if not nodes and not xpath:
        nodes = doc.xpath('//main[not(ancestor::main)]')
    # Never snapshot whole-page navigation or a JS shell as editorial content.
    if not nodes:
        raise ValueError('未找到正文区域；请配置正文 XPath 或使用该站的 RSS/API')
    return doc, nodes


def plain(nodes):
    return '\n'.join(re.sub(r'\s+', ' ', s).strip() for n in nodes
                     for s in n.itertext() if s.strip())


@register('page_watch')
def fetch_page_watch(source, limit):
    raw = _request_text(source['url'])
    _, nodes = content_nodes(raw, source.get('content_xpath'))
    text = plain(nodes)
    # Ignore relative "updated X minutes ago" labels; keep real content and dates.
    text = re.sub(r'(?im)^.*(?:updated|更新于?).{0,30}(?:ago|之前|前)\s*$', '', text).strip()
    if len(text) < 100:
        raise ValueError('正文过短，拒绝覆盖页面基线')
    return [{'title': source['name'] + ' 页面变更', 'url': source['url'],
             'summary': text[:800], 'published': None, 'no_extract': True,
             '_watch_scope': source['url'], '_watch_text': text,
             '_watch_mode': 'content'}]


@register('article_index')
def fetch_article_index(source, limit):
    raw = _request_text(source['url'])
    _raise_if_blocked(source['url'], raw)
    doc = lh.fromstring(raw)
    pattern = re.compile(source['link_pattern'])
    links = {}
    for a in doc.xpath('//a[@href]'):
        url = urljoin(source['url'], a.get('href')).split('#')[0]
        title = strip_html(lh.tostring(a, encoding='unicode'))
        if pattern.search(url) and len(title) >= 8:
            links.setdefault(url, title)
    if not links:
        raise ValueError('未找到文章链接；站点可能需要动态加载或已改变结构')
    rows = []
    for url, title in list(links.items())[:min(limit, int(source.get('item_limit', 10)))]:
        detail = _request_text(url)
        d, nodes = content_nodes(detail, source.get('content_xpath'))
        heads = d.xpath('//h1')
        if heads:
            title = strip_html(lh.tostring(heads[0], encoding='unicode'))
        else:
            meta_title = d.xpath('//meta[@property="og:title"]/@content')
            if meta_title:
                title = meta_title[0]
        # Only article publication metadata, never arbitrary dates in body text.
        dates = d.xpath('//meta[@property="article:published_time"]/@content|'
                        '//meta[@name="date"]/@content|//time/@datetime')
        published = next((v for x in dates if (v := iso_date(x))), None)
        rows.append({'title': title, 'url': url, 'summary': plain(nodes)[:1200],
                     'published': published, 'no_extract': True,
                     '_watch_scope': source['url'], '_watch_text': plain(nodes),
                     '_watch_mode': 'article'})
    return rows


@register('huggingface')
def fetch_huggingface(source, limit):
    author = source['url'].rstrip('/').split('/')[-1]
    data = _request_json(f'https://huggingface.co/api/models?author={author}&sort=createdAt&direction=-1&limit={min(limit,100)}')
    if not isinstance(data, list):
        raise ValueError('Hugging Face 返回格式异常')
    rows = []
    for m in data:
        model = m['id']
        rows.append({'title': f'{model} 新模型仓库', 'url': f'https://huggingface.co/{model}',
                     'published': iso_date(m.get('createdAt')), 'no_extract': True,
                     'summary': f"模型仓库新增（不等同于发布公告）。任务：{m.get('pipeline_tag','未标注')}；标签：{', '.join(m.get('tags', [])[:20])}"})
    return rows


@register('github_org')
def fetch_github_org(source, limit):
    org = source['url'].rstrip('/').split('/')[-1]
    data = _request_json(f'https://api.github.com/orgs/{org}/repos?sort=created&direction=desc&per_page={min(limit,100)}')
    if not isinstance(data, list):
        raise ValueError('GitHub 返回格式异常')
    return [{'title': f"{m['full_name']} 新开源仓库", 'url': m['html_url'],
             'published': iso_date(m.get('created_at')), 'no_extract': True,
             'summary': '仓库创建记录（不等同于模型正式发布）。' + (m.get('description') or '')}
            for m in data if not m.get('fork') and not m.get('private')]


@register('x_account')
def fetch_x_account(source, limit):
    token = os.environ.get('X_BEARER_TOKEN')
    if not token:
        raise ValueError('X 来源需要 X_BEARER_TOKEN 及可读取用户时间线的 API 权限')
    account = source['url'].rstrip('/').split('/')[-1]
    if not re.fullmatch(r'[A-Za-z0-9_]{1,15}', account):
        raise ValueError('X URL 必须是账号主页')
    with httpx.Client(headers={'Authorization': f'Bearer {token}'}, timeout=30) as client:
        r = client.get(f'https://api.x.com/2/users/by/username/{account}')
        r.raise_for_status()
        uid = r.json()['data']['id']
        r = client.get(f'https://api.x.com/2/users/{uid}/tweets', params={
            'max_results': max(5, min(limit,100)), 'tweet.fields': 'created_at', 'exclude': 'retweets,replies'})
        r.raise_for_status()
        return [{'title': f"@{account}：{m['text'][:160]}",
                 'url': f"https://x.com/{account}/status/{m['id']}",
                 'summary': m['text'], 'published': iso_date(m.get('created_at')), 'no_extract': True}
                for m in r.json().get('data', [])[:limit]]


@register('model_catalog')
def fetch_model_catalog(source, limit):
    data = _request_json(source['url'])
    if not isinstance(data, dict) or not isinstance(data.get('data'), list):
        raise ValueError('模型目录 API 返回格式异常')
    prefix = source.get('code', 'inclusionai/')
    models = [m for m in data['data'] if m.get('id', '').startswith(prefix)]
    models.sort(key=lambda m: m.get('created') or 0, reverse=True)
    rows = []
    for m in models[:limit]:
        created = m.get('created')
        published = datetime.fromtimestamp(created, timezone.utc) if isinstance(created, (int,float)) else None
        rows.append({'title': f"{m.get('name') or m['id']} 上架模型目录",
                     'url': 'https://openrouter.ai/' + m['id'], 'published': published,
                     'summary': '服务商上架记录，不代表研发机构首次发布。' + (m.get('description') or '')[:1000],
                     'no_extract': True})
    return rows
