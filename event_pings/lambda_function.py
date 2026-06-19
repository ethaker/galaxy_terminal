import json
import event_driven_pings

def lambda_handler(event, context):
    event_driven_pings.run_all()
    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }
