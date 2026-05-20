import kagglehub
import pandas as pd
import boto3
import json
import os

s3_client = boto3.Session(profile_name='cloud-projekat-dev').client('s3')

BRONZE_BUCKET = os.environ.get('BRONZE_BUCKET_NAME', 'visor-inc-amazing-datalake-bronze')

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
        print(f"Uploaded: {s3_key} ({len(batch)} tweets)")

print(f"\nDone. {total_batches} batches uploaded to s3://{BRONZE_BUCKET}/datasource=x/")
