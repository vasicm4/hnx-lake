import json
import urllib.request
import boto3
from datetime import datetime

s3 = boto3.client('s3')

def lambda_handler(event, context):
    # 1. Test interneta (preko NAT-a) - uzimamo najnoviji Item ID sa Hacker Newsa
    # Ovaj endpoint je izuzetno stabilan
    url = "https://hacker-news.firebaseio.com/v0/maxitem.json"
    
    try:
        print(f"Pokušavam fetch sa: {url}")
        # Postavljamo User-Agent jer neki API-jevi blokiraju default urllib botove
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        
        with urllib.request.urlopen(req, timeout=10) as response:
            max_id = response.read().decode()
            data = {
                "max_item_id": max_id,
                "timestamp": datetime.now().isoformat(),
                "test_status": "Success"
            }
            print(f"Uspešno povučen Max ID: {max_id}")
            
    except Exception as e:
        print(f"Internet Error: {str(e)}")
        return {"status": "error", "message": f"NAT/Internet failure: {str(e)}"}

    # 2. Test S3 pristupa (preko VPC Endpointa)
    bucket_name = "visor-inc-amazing-datalake-bronze"
    file_name = f"test_hn_{datetime.now().strftime('%H-%M-%S')}.json"
    
    try:
        s3.put_object(
            Bucket=bucket_name,
            Key=f"test/{file_name}",
            Body=json.dumps(data)
        )
        return {
            "status": "success",
            "message": f"Uspešan test! Podaci sa HN upisani u {file_name}"
        }
    except Exception as e:
        print(f"S3 Error: {str(e)}")
        return {"status": "error", "message": f"S3/VPCE failure: {str(e)}"}