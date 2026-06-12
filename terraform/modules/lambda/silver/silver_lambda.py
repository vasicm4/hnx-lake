import json
import boto3
import urllib3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
import os
import time
import re
import html
import uuid

try:
    import awswrangler as wr
    HAS_WRANGLER = True
except ImportError:
    HAS_WRANGLER = False
    print("Warning: awswrangler not available, will use pandas for Parquet")

s3_client = boto3.client('s3')
http = urllib3.PoolManager()

BRONZE_BUCKET = os.environ.get('BRONZE_BUCKET_NAME', 'visor-inc-amazing-datalake-bronze')
SILVER_BUCKET = os.environ.get('SILVER_BUCKET_NAME', 'visor-inc-amazing-datalake-silver')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')


def send_discord_notification(message, is_error=True):
    """Send notification to Discord webhook"""
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not configured")
        return

    try:
        color = 15158332 if is_error else 3066993  # Red for error green for success

        payload = {
            "embeds": [{
                "title": "Silver Lambda Job Failed" if is_error else "Silver Lambda Job Succeeded",
                "description": message,
                "color": color,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {
                    "text": "Visor Inc Data Lake"
                }
            }]
        }

        encoded_data = json.dumps(payload).encode('utf-8')
        response = http.request(
            'POST',
            DISCORD_WEBHOOK_URL,
            body=encoded_data,
            headers={'Content-Type': 'application/json'}
        )

        if response.status != 204:
            print(f"Discord notification failed: {response.status}")
    except Exception as e:
        print(f"Error sending Discord notification: {str(e)}")


def clean_html_text(text):
    if not text or not isinstance(text, str):
        return text
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', text)
    text = html.unescape(text)
    return text.strip()


def normalize_timestamp(timestamp_val, source_platform):
    try:
        if isinstance(timestamp_val, (int, float)):
            dt = datetime.fromtimestamp(timestamp_val, tz=timezone.utc)
        elif isinstance(timestamp_val, str) and timestamp_val.isdigit():
            dt = datetime.fromtimestamp(int(timestamp_val), tz=timezone.utc)
        else:
            dt = pd.to_datetime(timestamp_val, utc=True)
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        print(f"Error normalizing timestamp {timestamp_val}: {str(e)}")
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def extract_hn_items(objects_list, date_str):
    """Extract and normalize Hacker News items from bronze layer"""
    posts = []
    users = {}

    for obj in objects_list:
        try:
            if not obj['Key'].endswith('.json'):
                continue
            response = s3_client.get_object(Bucket=BRONZE_BUCKET, Key=obj['Key'])
            data = json.loads(response['Body'].read().decode('utf-8'))
            if not data:
                continue
            key_parts = obj['Key'].split('/')
            item_type = None
            for part in key_parts:
                if part.startswith('type='):
                    item_type = part.split('=')[1]
                    break
            if not item_type:
                if 'post_type' in data:
                    item_type = data['post_type']
                elif 'title' in data and 'url' in data:
                    item_type = 'story'
                elif 'text' in data:
                    item_type = 'comment'
                else:
                    item_type = 'unknown'
            item_id = str(data.get('objectID') or data.get('id') or data.get('post_id') or '')
            if not item_id:
                continue
            author = data.get('author') or data.get('username') or data.get('user') or ''
            if not author:
                continue
            created_at_i = data.get('created_at_i') or data.get('created_at')
            created_at_norm = normalize_timestamp(created_at_i, 'hackernews')
            if item_type == 'comment':
                content_raw = data.get('text') or data.get('comment') or ''
            else:
                content_raw = data.get('title') or data.get('text') or ''
            content_clean = clean_html_text(content_raw)
            url = data.get('url') or data.get('link') or ''
            score = data.get('score') or data.get('points') or 0
            if item_type in ['story', 'ask', 'job', 'poll']:
                post_type_map = {
                    'story': 'story',
                    'ask': 'ask_hn',
                    'job': 'job',
                    'poll': 'poll'
                }
                post_type = post_type_map.get(item_type, item_type)
                posts.append({
                    'post_id': item_id,
                    'author_username': author,
                    'content_text': content_clean,
                    'created_at': created_at_norm,
                    'post_type': post_type,
                    'url': url,
                    'score': score
                })
                if author not in users:
                    users[author] = {
                        'user_id': str(uuid.uuid5(uuid.NAMESPACE_DNS, f"hn:{author}")),
                        'username': author,
                        'platform': 'Hacker News',
                        'karma_score': int(score) if isinstance(score, (int, float)) and not np.isnan(score) else 0,
                        'is_verified': None,
                        'created_at': created_at_norm
                    }
            elif item_type == 'comment':
                posts.append({
                    'post_id': item_id,
                    'author_username': author,
                    'content_text': content_clean,
                    'created_at': created_at_norm,
                    'post_type': 'comment',
                    'parent_id': data.get('parent') or data.get('parent_id'),
                    'story_id': data.get('story_id')
                })
                if author not in users:
                    users[author] = {
                        'user_id': str(uuid.uuid5(uuid.NAMESPACE_DNS, f"hn:{author}")),
                        'username': author,
                        'platform': 'Hacker News',
                        'karma_score': 0,
                        'is_verified': None,
                        'created_at': created_at_norm
                    }
        except Exception as e:
            print(f"Error processing HN object {obj['Key']}: {str(e)}")
            continue
    return posts, list(users.values())

def write_dataframe_to_s3_parquet(df, bucket, prefix, partition_cols=None):
    try:
        if HAS_WRANGLER:
            wr.s3.to_parquet(
                df=df,
                path=f"s3://{bucket}/{prefix}",
                dataset=True,
                partition_cols=partition_cols,
                mode='append'
            )
        else:
            import pyarrow as pa
            import pyarrow.parquet as pq
            table = pa.Table.from_pandas(df)
            if partition_cols and len(partition_cols) > 0:
                pq.write_to_dataset(
                    table,
                    root_path=f"s3://{bucket}/{prefix}",
                    partition_cols=partition_cols,
                    existing_data_behavior='overwrite_or_ignore'
                )
            else:
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                filename = f"data_{timestamp}.parquet"
                pq.write_table(table, f"s3://{bucket}/{prefix}/{filename}")
        print(f"Successfully wrote {len(df)} records to s3://{bucket}/{prefix}")
        return True
    except Exception as e:
        print(f"Error writing DataFrame to S3: {str(e)}")
        return False


def lambda_handler(event, context):
    start_time = time.time()
    stats = {
        'hn_posts': 0,
        'hn_users': 0,
        'total_posts': 0,
        'total_users': 0
    }
    errors = []
    try:
        if 'date' in event:
            target_date = datetime.strptime(event['date'], '%Y-%m-%d')
        else:
            target_date = datetime.now(timezone.utc) - timedelta(days=1)
        date_str = target_date.strftime('%Y-%m-%d')
        print(f"Processing data for date: {date_str}")
        prefix_hn = f"datasource=hackernews/"
        print("Fetching Hacker News objects from bronze layer...")
        hn_objects = []
        continuation_token = None
        while True:
            if continuation_token:
                response = s3_client.list_objects_v2(
                    Bucket=BRONZE_BUCKET,
                    Prefix=prefix_hn,
                    ContinuationToken=continuation_token
                )
            else:
                response = s3_client.list_objects_v2(
                    Bucket=BRONZE_BUCKET,
                    Prefix=prefix_hn
                )
            if 'Contents' in response:
                for obj in response['Contents']:
                    if f"date={date_str}" in obj['Key']:
                        hn_objects.append(obj)
            if response.get('IsTruncated'):
                continuation_token = response.get('NextContinuationToken')
            else:
                break
        print(f"Found {len(hn_objects)} Hacker News objects for {date_str}")
        
        print("Processing Hacker News data...")
        hn_posts, hn_users = extract_hn_items(hn_objects, date_str)
        stats['hn_posts'] = len(hn_posts)
        stats['hn_users'] = len(hn_users)
        all_posts = hn_posts
        all_users = hn_users
        users_by_key = {}
        for user in all_users:
            key = (user['username'], user['platform'])
            if key not in users_by_key or user['created_at'] > users_by_key[key]['created_at']:
                users_by_key[key] = user
        deduped_users = list(users_by_key.values())
        posts_by_id = {}
        for post in all_posts:
            pid = post['post_id']
            if pid not in posts_by_id:
                posts_by_id[pid] = post

        deduped_posts = list(posts_by_id.values())

        stats['total_posts'] = len(deduped_posts)
        stats['total_users'] = len(deduped_users)

        print(f"After deduplication: {stats['total_posts']} posts, {stats['total_users']} users")

        if deduped_posts:
            posts_df = pd.DataFrame(deduped_posts)
            posts_columns = ['post_id', 'author_username', 'content_text', 'created_at', 'post_type']
            posts_columns = [col for col in posts_columns if col in posts_df.columns]
            posts_df = posts_df[posts_columns]
            posts_df['created_at_dt'] = pd.to_datetime(posts_df['created_at'])
            posts_df['year'] = posts_df['created_at_dt'].dt.year
            posts_df['month'] = posts_df['created_at_dt'].dt.month
            posts_df['day'] = posts_df['created_at_dt'].dt.day

            write_success = write_dataframe_to_s3_parquet(
                posts_df,
                SILVER_BUCKET,
                'posts/',
                partition_cols=['year', 'month', 'day']
            )

            if not write_success:
                errors.append("Failed to write posts DataFrame to S3")
        else:
            print("No posts data to write")
            write_success = True

        if deduped_users:
            users_df = pd.DataFrame(deduped_users)
            users_columns = ['user_id', 'username', 'platform', 'karma_score', 'is_verified', 'created_at']
            users_columns = [col for col in users_columns if col in users_df.columns]
            users_df = users_df[users_columns]
            write_success_users = write_dataframe_to_s3_parquet(
                users_df,
                SILVER_BUCKET,
                'users/',
                partition_cols=['platform']
            )

            if not write_success_users:
                errors.append("Failed to write users DataFrame to S3")
        else:
            print("No users data to write")
            write_success_users = True

        execution_time = time.time() - start_time

        summary = f"""
            **Silver Layer Normalization Summary**
            Date: {date_str}
            Hacker News Posts: {stats['hn_posts']}
            Hacker News Users: {stats['hn_users']}

            Execution Time: {execution_time:.2f}s
            Errors: {len(errors)}
        """

        if errors:
            summary += f"\n**Error Details:**\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                summary += f"\n... and {len(errors) - 10} more errors"
        error_rate = len(errors) / max(stats['total_posts'] + stats['total_users'], 1)
        if errors and error_rate > 0.1:  # More than 10% error rate
            send_discord_notification(summary, is_error=True)
        else:
            send_discord_notification(summary, is_error=False)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Silver layer normalization completed',
                'stats': stats,
                'date': date_str,
                'execution_time': execution_time,
                'error_count': len(errors),
                'errors': errors if errors else None
            })
        }

    except Exception as e:
        error_message = f"Silver Lambda execution failed: {str(e)}"
        print(error_message)

        send_discord_notification(
            f"**Critical Failure**\n{error_message}\n\nPartial stats: {json.dumps(stats)}",
            is_error=True
        )

        raise