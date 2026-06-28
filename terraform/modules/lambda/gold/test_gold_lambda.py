"""Local unit tests for gold metric computations (pure pandas, no AWS).

Run: python test_gold_lambda.py
"""
import os
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gold_lambda as g

DATE = '2026-06-27'


def make_posts():
    return pd.DataFrame([
        # HN posts on target date
        {'post_id': 's1', 'author_username': 'alice', 'content_text': 'Show HN', 'created_at': '2026-06-27T10:00:00Z', 'post_type': 'story',   'score': 100},
        {'post_id': 's2', 'author_username': 'bob',   'content_text': 'Blog',    'created_at': '2026-06-27T11:00:00Z', 'post_type': 'story',   'score': 50},
        {'post_id': 'j1', 'author_username': 'carol', 'content_text': 'Hiring',  'created_at': '2026-06-27T12:00:00Z', 'post_type': 'job',     'score': 80},
        {'post_id': 'j2', 'author_username': 'dave',  'content_text': 'Job',     'created_at': '2026-06-27T13:00:00Z', 'post_type': 'job',     'score': 30},
        {'post_id': 'c1', 'author_username': 'alice', 'content_text': 'nice',    'created_at': '2026-06-27T14:00:00Z', 'post_type': 'comment', 'score': None},
        {'post_id': 'a1', 'author_username': 'eve',   'content_text': 'Ask HN',  'created_at': '2026-06-27T15:00:00Z', 'post_type': 'ask_hn',  'score': 5},
        # X tweets (2023) -> engagement snapshot
        {'post_id': 't1', 'author_username': 'xuser1', 'content_text': 'gm',     'created_at': '2023-01-30T10:00:00Z', 'post_type': 'tweet',   'score': 27},
        {'post_id': 't2', 'author_username': 'xuser2', 'content_text': 'hello',  'created_at': '2023-01-30T10:00:00Z', 'post_type': 'tweet',   'score': 64},
        {'post_id': 't3', 'author_username': 'xuser1', 'content_text': 'again',  'created_at': '2023-01-30T11:00:00Z', 'post_type': 'tweet',   'score': 10},
    ])


def make_users():
    return pd.DataFrame([
        {'user_id': 'u-alice', 'username': 'alice', 'platform': 'Hacker News', 'karma_score': 100,  'is_verified': None,  'created_at': '2026-06-27T10:00:00Z'},
        {'user_id': 'u-alice', 'username': 'alice', 'platform': 'Hacker News', 'karma_score': 100,  'is_verified': None,  'created_at': '2026-06-26T10:00:00Z'},
        {'user_id': 'u-bob',   'username': 'bob',   'platform': 'Hacker News', 'karma_score': 50,   'is_verified': None,  'created_at': '2026-06-27T11:00:00Z'},
        {'user_id': 'u-carol', 'username': 'carol', 'platform': 'Hacker News', 'karma_score': 80,   'is_verified': None,  'created_at': '2026-06-27T12:00:00Z'},
        {'user_id': 'u-frank', 'username': 'frank', 'platform': 'Hacker News', 'karma_score': 200,  'is_verified': None,  'created_at': '2026-06-26T09:00:00Z'},
        {'user_id': 'u-x1',    'username': 'xuser1','platform': 'X',           'karma_score': None, 'is_verified': True,  'created_at': '2023-01-30T10:00:00Z'},
        {'user_id': 'u-x2',    'username': 'xuser2','platform': 'X',           'karma_score': None, 'is_verified': False, 'created_at': '2023-01-30T10:00:00Z'},
    ])


def show(title, df):
    print(f"\n=== {title} ===")
    print(df.to_string(index=False) if not df.empty else "(empty)")


def main():
    posts, users = make_posts(), make_users()

    m1 = g.compute_daily_content_metrics(posts, DATE)
    show('M1 daily_content_metrics', m1)
    hn = m1[m1['platform'] == 'Hacker News'].set_index('post_type')['post_count'].to_dict()
    assert hn == {'story': 2, 'job': 2, 'comment': 1, 'ask_hn': 1}, hn
    assert 'X' not in m1['platform'].values  # X tweets are 2023, not on DATE

    m23 = g.compute_daily_users_metric(users, DATE)
    show('M2/M3 daily_users_metric', m23)
    hn_row = m23[m23['platform'] == 'Hacker News'].iloc[0]
    x_row = m23[m23['platform'] == 'X'].iloc[0]
    assert (hn_row['total_users'], hn_row['new_users']) == (4, 2), hn_row.to_dict()
    assert (x_row['total_users'], x_row['new_users']) == (2, 0), x_row.to_dict()

    karma = g.compute_top_hn_users_by_karma(users, DATE)
    show('M5/M6 top_hn_users_by_karma', karma)
    top = karma[karma['direction'] == 'top'].sort_values('rank')
    bottom = karma[karma['direction'] == 'bottom'].sort_values('rank')
    assert list(top['username']) == ['alice', 'carol', 'bob'], list(top['username'])  # frank excluded (not active on DATE)
    assert bottom.iloc[0]['username'] == 'bob'

    jobs = g.compute_top_posts_by_score(posts, DATE, 'job')
    show('M7 top_hn_jobs_by_score', jobs)
    assert list(jobs['post_id']) == ['j1', 'j2'] and jobs.iloc[0]['score'] == 80

    stories = g.compute_top_posts_by_score(posts, DATE, 'story')
    show('M8 top_hn_posts_by_score', stories)
    assert list(stories['post_id']) == ['s1', 's2'] and stories.iloc[0]['score'] == 100

    eng = g.compute_top_x_users_by_engagement(posts, DATE)
    show('M4 top_x_users_by_engagement', eng)
    assert eng.iloc[0]['username'] == 'xuser2' and eng.iloc[0]['engagement_score'] == 64
    assert eng[eng['username'] == 'xuser1'].iloc[0]['engagement_score'] == 37  # 27 + 10

    dq = g.compute_data_quality_score(posts, users, DATE)
    show('KPI data_quality_score', dq)
    assert dq[dq['table_name'] == 'posts'].iloc[0]['dq_score_pct'] == 100.0
    assert dq[dq['table_name'] == 'users'].iloc[0]['dq_score_pct'] == 100.0

    # idempotent writer: empty frame writes nothing, no AWS call
    assert g.write_gold_table(pd.DataFrame(), 'whatever', ['date']) == 0

    # empty-input safety for every metric
    empty_p = pd.DataFrame(columns=g.POSTS_SCHEMA)
    empty_u = pd.DataFrame(columns=g.USERS_SCHEMA)
    for fn, args in [
        (g.compute_daily_content_metrics, (empty_p, DATE)),
        (g.compute_daily_users_metric, (empty_u, DATE)),
        (g.compute_top_hn_users_by_karma, (empty_u, DATE)),
        (g.compute_top_posts_by_score, (empty_p, DATE, 'job')),
        (g.compute_top_x_users_by_engagement, (empty_p, DATE)),
        (g.compute_data_quality_score, (empty_p, empty_u, DATE)),
    ]:
        assert fn(*args).empty or fn(*args).shape[0] >= 0  # must not raise

    print("\nALL TESTS PASSED")


if __name__ == '__main__':
    main()
