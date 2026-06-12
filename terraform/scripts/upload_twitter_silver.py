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
                "title": "Twitter Silver Lambda Job Failed" if is_error else "Twitter Silver Lambda Job Succeeded",
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
        dt = pd.to_datetime(timestamp_val, utc=True)
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        print(f"Error normalizing timestamp {timestamp_val}: {str(e)}")
        return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def extract_x_items(objects_list, date_str):
    posts = []
    users = {}

    for obj in objects_list:
        try:
            if not obj['Key'].endswith('.json'):
                continue
            response = s3_client.get_object(Bucket=BRONZE_BUCKET, Key=obj['Key'])
            data = json.loads(response['Body'].read().decode('utf-8'))
            if not isinstance(data, list):
                data = [data] if isinstance(data, dict) else []
            for tweet in data:
                if not isinstance(tweet, dict):
                    continue
                item_id = str(tweet.get('id') or tweet.get('tweet_id') or tweet.get('ID') or '')
                if not item_id:
                    continue
                author = tweet.get('user') or tweet.get('username') or tweet.get('author') or ''
                if isinstance(author, dict):
                    author = author.get('screen_name') or author.get('name') or str(author.get('id', ''))
                if not author:
                    continue
                timestamp_val = tweet.get('Timestamp') or tweet.get('created_at') or tweet.get('timestamp')
                created_at_norm = normalize_timestamp(timestamp_val, 'x')
                content_raw = tweet.get('Text') or tweet.get('text') or tweet.get('content') or ''
                content_clean = clean_html_text(content_raw)
                is_retweet = (
                    content_clean.startswith('RT @') or
                    tweet.get('is_retweet') == True or
                    tweet.get('retweet_count', 0) > 0
                )
                post_type = 'retweet' if is_retweet else 'tweet'
                posts.append({
                    'post_id': item_id,
                    'author_username': author,
                    'content_text': content_clean,
                    'created_at': created_at_norm,
                    'post_type': post_type,
                    'retweet_count': tweet.get('retweet_count', 0),
                    'favorite_count': tweet.get('favorite_count', 0)
                })
                if author not in users:
                    verified = False
                    user_obj = tweet.get('user', {})
                    if isinstance(user_obj, dict):
                        verified = user_obj.get('verified', False)
                    elif 'verified' in tweet:
                        verified = tweet.get('verified', False)

                    users[author] = {
                        'user_id': str(uuid.uuid5(uuid.NAMESPACE_DNS, f"x:{author}")),
                        'username': author,
                        'platform': 'X',
                        'karma_score': None,
                        'is_verified': bool(verified),
                        'created_at': created_at_norm
                    }

        except Exception as e:
            print(f"Error processing X object {obj['Key']}: {str(e)}")
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
        'x_posts': 0,
        'x_users': 0,
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
        prefix_x = f"datasource=x/"
        print("Fetching X (Twitter) objects from bronze layer...")
        x_objects = []
        continuation_token = None

        while True:
            if continuation_token:
                response = s3_client.list_objects_v2(
                    Bucket=BRONZE_BUCKET,
                    Prefix=prefix_x,
                    ContinuationToken=continuation_token
                )
            else:
                response = s3_client.list_objects_v2(
                    Bucket=BRONZE_BUCKET,
                    Prefix=prefix_x
                )

            if 'Contents' in response:
                for obj in response['Contents']:
                    if f"date={date_str}" in obj['Key']:
                        x_objects.append(obj)

            if response.get('IsTruncated'):
                continuation_token = response.get('NextContinuationToken')
            else:
                break

        print(f"Found {len(x_objects)} X objects for {date_str}")
        print("Processing X (Twitter) data...")
        x_posts, x_users = extract_x_items(x_objects, date_str)
        stats['x_posts'] = len(x_posts)
        stats['x_users'] = len(x_users)
        all_posts = x_posts
        all_users = x_users
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
            X (Twitter) Posts: {stats['x_posts']}
            X (Twitter) Users: {stats['x_users']}

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