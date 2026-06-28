import json
import boto3
import urllib3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import os
import time

try:
    import awswrangler as wr
    HAS_WRANGLER = True
except ImportError:
    HAS_WRANGLER = False
    print("Warning: awswrangler not available, will use pandas/pyarrow for Parquet")

s3_client = boto3.client('s3')
http = urllib3.PoolManager()

SILVER_BUCKET = os.environ.get('SILVER_BUCKET_NAME', 'visor-inc-amazing-datalake-silver')
GOLD_BUCKET = os.environ.get('GOLD_BUCKET_NAME', 'visor-inc-amazing-datalake-gold')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')

# --- Domain constants -------------------------------------------------------
HN = 'Hacker News'
X = 'X'
HN_POST_TYPES = ['story', 'ask_hn', 'comment', 'job', 'poll']
X_POST_TYPES = ['tweet', 'retweet']
TOP_N = 10

# Columns that must never be null after normalization (used by the Data Quality
# KPI). Schema-nullable columns (karma_score for X, is_verified for HN, score
# for comments) are intentionally excluded so the KPI measures normalization
# quality, not by-design nulls.
POSTS_REQUIRED = ['post_id', 'author_username', 'created_at', 'post_type']
USERS_REQUIRED = ['user_id', 'username', 'platform', 'created_at']

POSTS_SCHEMA = ['post_id', 'author_username', 'content_text', 'created_at', 'post_type', 'score']
USERS_SCHEMA = ['user_id', 'username', 'platform', 'karma_score', 'is_verified', 'created_at']


def send_discord_notification(message, is_error=True):
    """Send notification to Discord webhook (same contract as bronze/silver)."""
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not configured")
        return
    try:
        color = 15158332 if is_error else 3066993  # red for error, green for success
        payload = {
            "embeds": [{
                "title": "Gold Lambda Job Failed" if is_error else "Gold Lambda Job Succeeded",
                "description": message,
                "color": color,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Visor Inc Data Lake"}
            }]
        }
        encoded_data = json.dumps(payload).encode('utf-8')
        response = http.request('POST', DISCORD_WEBHOOK_URL, body=encoded_data,
                                headers={'Content-Type': 'application/json'})
        if response.status != 204:
            print(f"Discord notification failed: {response.status}")
    except Exception as e:
        print(f"Error sending Discord notification: {str(e)}")


# --- Helpers ----------------------------------------------------------------
def _date_series(df, col='created_at'):
    """UTC date string (YYYY-MM-DD) derived from a timestamp column."""
    return pd.to_datetime(df[col], utc=True, errors='coerce').dt.strftime('%Y-%m-%d')


def _with_post_dims(posts_df):
    """Add derived `date` and `platform` columns to the posts dataframe.

    posts has no platform column, so we derive it from post_type
    (tweet/retweet -> X, everything else -> Hacker News)."""
    df = posts_df.copy()
    df['date'] = _date_series(df)
    df['platform'] = np.where(df['post_type'].isin(X_POST_TYPES), X, HN)
    return df


# --- Metric computations (pure: dataframe in -> dataframe out) ---------------
def compute_daily_content_metrics(posts_df, date_str):
    """M1: number of posts per platform/post_type on a given day."""
    cols = ['date', 'platform', 'post_type', 'post_count']
    if posts_df.empty:
        return pd.DataFrame(columns=cols)
    df = _with_post_dims(posts_df)
    df = df[df['date'] == date_str]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = df.groupby(['platform', 'post_type']).size().reset_index(name='post_count')
    out.insert(0, 'date', date_str)
    return out[cols]


def compute_daily_users_metric(users_df, date_str):
    """M2/M3: cumulative total_users and new_users per platform up to a day.

    total_users = distinct users first seen on or before date_str.
    new_users   = distinct users first seen exactly on date_str."""
    cols = ['date', 'platform', 'total_users', 'new_users']
    if users_df.empty:
        return pd.DataFrame(columns=cols)
    df = users_df.copy()
    df['date'] = _date_series(df)
    first_seen = df.groupby(['platform', 'username'])['date'].min().reset_index()
    rows = []
    for platform, grp in first_seen.groupby('platform'):
        total = int((grp['date'] <= date_str).sum())
        new = int((grp['date'] == date_str).sum())
        rows.append({'date': date_str, 'platform': platform,
                     'total_users': total, 'new_users': new})
    return pd.DataFrame(rows, columns=cols)


def compute_top_hn_users_by_karma(users_df, date_str, n=TOP_N):
    """M5/M6: top and bottom N Hacker News users by karma on a given day."""
    cols = ['date', 'direction', 'rank', 'username', 'karma_score']
    if users_df.empty:
        return pd.DataFrame(columns=cols)
    df = users_df.copy()
    df['date'] = _date_series(df)
    df = df[(df['platform'] == HN) & (df['date'] == date_str)]
    df = df.dropna(subset=['karma_score'])
    if df.empty:
        return pd.DataFrame(columns=cols)
    # one karma value per user (highest seen that day)
    df = df.groupby('username', as_index=False)['karma_score'].max()
    top = df.nlargest(n, 'karma_score').copy()
    top['direction'] = 'top'
    top['rank'] = range(1, len(top) + 1)
    bottom = df.nsmallest(n, 'karma_score').copy()
    bottom['direction'] = 'bottom'
    bottom['rank'] = range(1, len(bottom) + 1)
    out = pd.concat([top, bottom], ignore_index=True)
    out['date'] = date_str
    return out[cols]


def compute_top_posts_by_score(posts_df, date_str, post_type, n=TOP_N):
    """M7/M8: top N Hacker News posts of a given post_type by score on a day."""
    cols = ['date', 'rank', 'post_id', 'author_username', 'score', 'content_text']
    if posts_df.empty:
        return pd.DataFrame(columns=cols)
    df = _with_post_dims(posts_df)
    df = df[(df['date'] == date_str) & (df['post_type'] == post_type)]
    df = df.dropna(subset=['score'])
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df.nlargest(n, 'score').copy()
    df['rank'] = range(1, len(df) + 1)
    df['date'] = date_str
    return df[cols]


def compute_top_x_users_by_engagement(posts_df, date_str, n=TOP_N):
    """M4: top N X users by total engagement (Likes + Retweets).

    The chosen X dataset has no follower count, so engagement is used as a
    proxy for influence. This is a snapshot stamped with date_str (the spec
    does not mark this metric as daily)."""
    cols = ['date', 'rank', 'username', 'engagement_score']
    if posts_df.empty:
        return pd.DataFrame(columns=cols)
    df = _with_post_dims(posts_df)
    df = df[df['platform'] == X].dropna(subset=['score'])
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = df.groupby('author_username', as_index=False)['score'].sum()
    out = out.rename(columns={'author_username': 'username', 'score': 'engagement_score'})
    out = out.nlargest(n, 'engagement_score').copy()
    out['rank'] = range(1, len(out) + 1)
    out['date'] = date_str
    return out[cols]


def _table_dq(df, required, table_name, date_str):
    present = [c for c in required if c in df.columns]
    total_cells = len(df) * max(len(present), 1)
    non_null = int(df[present].notna().sum().sum()) if (present and len(df)) else 0
    pct = round(100.0 * non_null / total_cells, 2) if total_cells else 0.0
    return {'date': date_str, 'table_name': table_name, 'total_rows': len(df),
            'non_null_cells': non_null, 'total_cells': total_cells, 'dq_score_pct': pct}


def compute_data_quality_score(posts_df, users_df, date_str):
    """KPI: percentage of non-null cells over required columns, per table, for
    the given day. Measures how well silver normalization filled mandatory
    fields."""
    cols = ['date', 'table_name', 'total_rows', 'non_null_cells', 'total_cells', 'dq_score_pct']
    p = _with_post_dims(posts_df) if not posts_df.empty else posts_df.assign(date=pd.Series(dtype=str))
    p = p[p['date'] == date_str] if not posts_df.empty else posts_df
    if not users_df.empty:
        u = users_df.copy()
        u['date'] = _date_series(u)
        u = u[u['date'] == date_str]
    else:
        u = users_df
    rows = [_table_dq(p, POSTS_REQUIRED, 'posts', date_str),
            _table_dq(u, USERS_REQUIRED, 'users', date_str)]
    return pd.DataFrame(rows, columns=cols)


# --- Silver I/O -------------------------------------------------------------
def _read_silver(prefix, empty_cols):
    path = f"s3://{SILVER_BUCKET}/{prefix}/"
    try:
        df = wr.s3.read_parquet(path=path, dataset=True)
        print(f"[gold] read {len(df)} rows from {path}")
        return df
    except Exception as e:
        print(f"[gold] no data at {path} ({e}); using empty frame")
        return pd.DataFrame(columns=empty_cols)


def read_silver_posts():
    return _read_silver('posts', POSTS_SCHEMA)


def read_silver_users():
    return _read_silver('users', USERS_SCHEMA)


def write_gold_table(df, table_name, partition_cols):
    """Write a gold table as partitioned parquet. Idempotent: re-running for a
    date overwrites that date's partitions instead of appending duplicates."""
    if df is None or df.empty:
        print(f"[gold] {table_name}: nothing to write")
        return 0
    path = f"s3://{GOLD_BUCKET}/{table_name}/"
    if not HAS_WRANGLER:
        raise RuntimeError("awswrangler is required to write gold tables")
    wr.s3.to_parquet(df=df, path=path, dataset=True,
                     partition_cols=partition_cols, mode='overwrite_partitions')
    print(f"[gold] wrote {len(df)} rows to {path} (partitions={partition_cols})")
    return len(df)


# --- Handler ----------------------------------------------------------------
def lambda_handler(event, context):
    start_time = time.time()
    event = event or {}
    if 'date' in event:
        date_str = event['date']
    else:
        date_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
    print(f"[gold] transforming metrics for date: {date_str}")

    written = {}
    errors = []
    try:
        posts_df = read_silver_posts()
        users_df = read_silver_users()

        tables = [
            ('daily_content_metrics', compute_daily_content_metrics(posts_df, date_str), ['date']),
            ('daily_users_metric', compute_daily_users_metric(users_df, date_str), ['platform', 'date']),
            ('top_hn_users_by_karma', compute_top_hn_users_by_karma(users_df, date_str), ['date']),
            ('top_hn_jobs_by_score', compute_top_posts_by_score(posts_df, date_str, 'job'), ['date']),
            ('top_hn_posts_by_score', compute_top_posts_by_score(posts_df, date_str, 'story'), ['date']),
            ('top_x_users_by_engagement', compute_top_x_users_by_engagement(posts_df, date_str), ['date']),
            ('data_quality_score', compute_data_quality_score(posts_df, users_df, date_str), ['date']),
        ]

        for name, df, parts in tables:
            try:
                written[name] = write_gold_table(df, name, parts)
            except Exception as e:
                msg = f"{name}: {str(e)}"
                print(f"[gold] ERROR {msg}")
                errors.append(msg)

        execution_time = time.time() - start_time
        summary = (
            f"**Gold Layer Transformation Summary**\n"
            f"Date: {date_str}\n"
            + "\n".join(f"- {k}: {v} rows" for k, v in written.items())
            + f"\n\nExecution Time: {execution_time:.2f}s\nErrors: {len(errors)}"
        )
        if errors:
            summary += "\n**Error Details:**\n" + "\n".join(errors[:10])
        send_discord_notification(summary, is_error=bool(errors))

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Gold layer transformation completed',
                'date': date_str,
                'written': written,
                'execution_time': execution_time,
                'error_count': len(errors),
                'errors': errors or None,
            })
        }
    except Exception as e:
        error_message = f"Gold Lambda execution failed: {str(e)}"
        print(error_message)
        send_discord_notification(
            f"**Critical Failure**\n{error_message}\n\nDate: {date_str}",
            is_error=True
        )
        raise
