"""Persist page baselines and dated observations without inventing publication dates."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from difflib import unified_diff
from urllib.parse import urldefrag


def observe(items, db, now=None):
    now = now or datetime.now(timezone.utc)
    watched = [it for it in items if it.get('_watch_scope')]
    if not watched:
        return items
    conn = db.conn
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS watch_scopes (scope TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS page_snapshots (
            scope TEXT NOT NULL, url TEXT NOT NULL, content TEXT NOT NULL,
            event TEXT, PRIMARY KEY(scope, url)
        );
    ''')
    seeded = {r[0] for r in conn.execute('SELECT scope FROM watch_scopes')}
    result = [it for it in items if not it.get('_watch_scope')]
    with conn:
        for it in watched:
            scope, url, content = it['_watch_scope'], it['url'], it['_watch_text']
            prior = conn.execute('SELECT content,event FROM page_snapshots WHERE scope=? AND url=?', (scope,url)).fetchone()
            event = json.loads(prior[1]) if prior and prior[1] else None
            changed = prior is not None and prior[0] != content and it['_watch_mode'] in {'content', 'article'}
            discovered = prior is None and scope in seeded and not it.get('published')
            if changed or discovered:
                diff = '\n'.join(unified_diff((prior[0] if prior else '').splitlines(), content.splitlines(), fromfile='previous', tofile='current', lineterm=''))
                event = {'observed_at': now.isoformat(), 'diff': diff[:12000],
                         'id': hashlib.sha256((content+now.isoformat()).encode()).hexdigest()[:16]}
            conn.execute('INSERT OR REPLACE INTO page_snapshots VALUES (?,?,?,?)',
                         (scope,url,content,json.dumps(event,ensure_ascii=False) if event else None))
            conn.execute('INSERT OR IGNORE INTO watch_scopes VALUES (?)',(scope,))
            if it['_watch_mode'] in {'discovery', 'article'} and it.get('published') and not event:
                result.append(it)
            elif event:
                row = {k:v for k,v in it.items() if not k.startswith('_watch_')}
                row['original_published'] = row.get('published')
                row['published'] = None
                row['observed_at'] = datetime.fromisoformat(event['observed_at'])
                row['time_basis'] = 'observed'
                row['url'] = urldefrag(url)[0] + '#change-' + event['id']
                label = '检测到正文变化' if it['_watch_mode'] in {'content', 'article'} else '首次发现条目'
                row['summary'] = f'{label}；真实发布时间未知，不可写成今日发布。\n' + event['diff'][:1600]
                row['text'] = event['diff']
                result.append(row)
    return result


def event_time(item):
    return item.get('published') or item.get('observed_at')
