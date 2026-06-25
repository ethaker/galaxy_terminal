import json
import market_events_decision_engine

def lambda_handler(event, context):
    market_events_decision_engine.run_all()
    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }
