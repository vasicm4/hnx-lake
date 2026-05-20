import kagglehub
import pandas as pd
import boto3
import json
import os
import urllib3
from datetime import datetime

s3_client = boto3.Session(profile_name='cloud-projekat-dev').client('s3')
http = urllib3.PoolManager()

BRONZE_BUCKET = os.environ.get('BRONZE_BUCKET_NAME', 'visor-inc-amazing-datalake-bronze')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')


def send_discord_notification(message, is_error=True):
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not configured")
        return

    try:
        color = 15158332 if is_error else 3066993  # red for error, green for success

        payload = {
            "embeds": [{
                "title": "X Bronze Upload Failed" if is_error else "X Bronze Upload Succeeded",
                "description": message,
                "color": color,
                "timestamp": datetime.utcnow().isoformat(),
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
            print(f"Discord notification failed with status: {response.status}")
    except Exception as e:
        print(f"Error sending Discord notification: {str(e)}")


try:
    path = kagglehub.dataset_download("goyaladi/twitter-dataset")
    print(f"Dataset cached at: {path}")

    df = pd.read_csv(path + "/twitter_dataset.csv")
    print(f"Columns: {df.columns.tolist()}")
    print(f"Total rows: {len(df)}")

    df['date'] = pd.to_datetime(df['Timestamp'], errors='coerce').dt.strftime('%Y-%m-%d')

    null_count = df['date'].isna().sum()
    if null_count > 0:
        print(f"Dropping {null_count} rows with unparseable timestamps")
    df = df.dropna(subset=['date'])

    grouped = df.groupby('date')
    print(f"Unique dates: {len(grouped)}")

    total_batches = 0
    total_tweets = 0
    for date_str, group in grouped:
        for i in range(0, len(group), 1000):
            batch = group.iloc[i:i + 1000].to_dict(orient='records')
            batch_num = i // 1000
            s3_key = f"datasource=x/type=tweet/date={date_str}/tweets_batch_{batch_num:03d}.json"

            s3_client.put_object(
                Bucket=BRONZE_BUCKET,
                Key=s3_key,
                Body=json.dumps(batch, indent=2),
                ContentType='application/json'
            )
            total_batches += 1
            total_tweets += len(batch)
            print(f"Uploaded: {s3_key} ({len(batch)} tweets)")

    summary = (
        f"**X (Twitter) Dataset Upload Summary**\n"
        f"Total tweets: {total_tweets}\n"
        f"Total batches: {total_batches}\n"
        f"Unique dates: {len(grouped)}\n"
        f"Dropped (bad timestamp): {null_count}\n"
        f"Bucket: `{BRONZE_BUCKET}`"
    )
    print(f"\nDone. {total_batches} batches, {total_tweets} tweets uploaded.")
    send_discord_notification(summary, is_error=False)

except Exception as e:
    error_message = f"**X Bronze Upload Failed**\n`{str(e)}`"
    print(error_message)
    send_discord_notification(error_message, is_error=True)
    raise
