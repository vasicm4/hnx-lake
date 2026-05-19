import json
import boto3
import urllib3
from datetime import datetime, timedelta
import os
import time

s3_client = boto3.client('s3')
http = urllib3.PoolManager()

BRONZE_BUCKET = os.environ.get('BRONZE_BUCKET_NAME', 'visor-inc-amazing-datalake-bronze')
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
HN_SEARCH_API = "http://hn.algolia.com/api/v1"


def send_discord_notification(message, is_error=True):
    """Send notification to Discord webhook"""
    if not DISCORD_WEBHOOK_URL:
        print("Discord webhook URL not configured")
        return
    
    try:
        color = 15158332 if is_error else 3066993  # Red for error green for success
        
        payload = {
            "embeds": [{
                "title": "Lambda Job Failed" if is_error else "Lambda Job Succeeded",
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
            print(f"Discord notification failed: {response.status}")
    except Exception as e:
        print(f"Error sending Discord notification: {str(e)}")


def fetch_item(item_id):
    try:
        url = f"{HN_API_BASE}/item/{item_id}.json"
        response = http.request('GET', url)
        
        if response.status == 200:
            return json.loads(response.data.decode('utf-8'))
        return None
    except Exception as e:
        print(f"Error fetching item {item_id}: {str(e)}")
        return None


def get_items_from_yesterday(item_type):

    yesterday = datetime.utcnow() - timedelta(days=1)
    yesterday_start = int(yesterday.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    yesterday_end = int(yesterday.replace(hour=23, minute=59, second=59, microsecond=0).timestamp())
    
    items = []
    
    try:
        if item_type == 'story':
            tags = 'story'
        elif item_type == 'ask':
            tags = 'ask_hn'
        elif item_type == 'job':
            tags = 'job'
        elif item_type == 'poll':
            tags = 'poll'
        elif item_type == 'comment':
            tags = 'comment'
        else:
            tags = 'story'
        
        page = 0
        while True:
            search_url = f"{HN_SEARCH_API}/search_by_date?tags={tags}&numericFilters=created_at_i>{yesterday_start},created_at_i<{yesterday_end}&hitsPerPage=1000&page={page}"
            
            response = http.request('GET', search_url)
            
            if response.status != 200:
                print(f"Search API error for {item_type}: {response.status}")
                break
            
            data = json.loads(response.data.decode('utf-8'))
            hits = data.get('hits', [])
            
            if not hits:
                break
            
            items.extend(hits)
            
            if page >= data.get('nbPages', 1) - 1:
                break
            
            page += 1
            time.sleep(0.5)
        
        print(f"Found {len(items)} {item_type} items from yesterday")
        return items
        
    except Exception as e:
        print(f"Error fetching {item_type} items: {str(e)}")
        raise


def write_to_s3(data, datasource, item_type, date_str, item_id):
    """Write data to S3 with proper partitioning"""
    try:
        s3_key = f"datasource={datasource}/type={item_type}/date={date_str}/{item_type}_{item_id}.json"
        
        s3_client.put_object(
            Bucket=BRONZE_BUCKET,
            Key=s3_key,
            Body=json.dumps(data, indent=2),
            ContentType='application/json'
        )
        
        return s3_key
    except Exception as e:
        print(f"Error writing to S3: {str(e)}")
        raise


def lambda_handler(event, context):
    
    start_time = time.time()
    stats = {
        'story': 0,
        'ask': 0,
        'comment': 0,
        'job': 0,
        'poll': 0
    }
    errors = []
    
    try:
        yesterday = datetime.utcnow() - timedelta(days=1)
        date_str = yesterday.strftime('%Y-%m-%d')
        
        print(f"Starting data collection for date: {date_str}")
        
        item_types = ['story', 'ask', 'comment', 'job', 'poll']
        
        for item_type in item_types:
            try:
                print(f"\nProcessing {item_type}s")
                items = get_items_from_yesterday(item_type)
                
                for item in items:
                    try:
                        item_id = item.get('objectID') or item.get('id')
                        if item_id:
                            s3_key = write_to_s3(
                                data=item,
                                datasource='hackernews',
                                item_type=item_type,
                                date_str=date_str,
                                item_id=item_id
                            )
                            stats[item_type] += 1
                            
                            if stats[item_type] % 100 == 0:
                                print(f"Processed {stats[item_type]} {item_type} items")
                    
                    except Exception as e:
                        error_msg = f"Error processing {item_type} item {item_id}: {str(e)}"
                        print(error_msg)
                        errors.append(error_msg)
                        continue
                
                print(f"Completed {item_type}: {stats[item_type]} items written to S3")
                time.sleep(1)
                
            except Exception as e:
                error_msg = f"Error processing {item_type} type: {str(e)}"
                print(error_msg)
                errors.append(error_msg)
                continue
        
        execution_time = time.time() - start_time
        
        total_items = sum(stats.values())
        summary = f"""
            **Data Collection Summary**
            Date: {date_str}
            Total Items: {total_items}
            - Stories: {stats['story']}
            - Asks: {stats['ask']}
            - Comments: {stats['comment']}
            - Jobs: {stats['job']}
            - Polls: {stats['poll']}

            Execution Time: {execution_time:.2f}s
            Errors: {len(errors)}
        """
        
        if errors:
            summary += f"\n**Error Details:**\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                summary += f"\n... and {len(errors) - 10} more errors"
        
        if errors and len(errors) > total_items * 0.1:
            send_discord_notification(summary, is_error=True)
        else:
            send_discord_notification(summary, is_error=False)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Data collection completed',
                'stats': stats,
                'date': date_str,
                'execution_time': execution_time,
                'error_count': len(errors)
            })
        }
    
    except Exception as e:
        error_message = f"Lambda execution failed: {str(e)}"
        print(error_message)
        
        send_discord_notification(
            f"**Critical Failure**\n{error_message}\n\nPartial stats: {json.dumps(stats)}",
            is_error=True
        )
        
        raise