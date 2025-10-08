import os
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import Connect, Stream, VoiceResponse
from dotenv import load_dotenv
from fastapi import HTTPException



load_dotenv(override=True)

def get_websocket_url(host: str) -> str:
    """Get the appropriate WebSocket URL based on environment."""
    env = os.getenv("ENV", "local").lower()

    if env == "production":
        return "wss://api.pipecat.daily.co/ws/twilio"
    else:
        return f"wss://{host}/ws"


def generate_twiml(host: str, body_data: dict = None) -> str:
    """Generate TwiML response with WebSocket streaming using Twilio SDK."""
    websocket_url = get_websocket_url(host)

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=f"{websocket_url}?contactId={body_data['contactId']}")

    # Add unique CallSid if provided
    if body_data and "CallSid" in body_data:
        print(f"Adding CallSid parameter to TwiML: {body_data['CallSid']}")
        stream.parameter(name="CallSid", value=body_data["CallSid"])

    # Add other params from body_data
    if body_data:
        for key, value in body_data.items():
            if key != "CallSid":
                stream.parameter(name=key, value=value)

    connect.append(stream)
    response.append(connect)
    response.pause(length=20)

    return str(response)



def make_twilio_call(to_number: str, from_number: str, twiml_url: str):
    """Make an outbound call using Twilio's REST API."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        raise ValueError("Missing Twilio credentials")

    # Construct status callback URL
    host = os.getenv("API_BASE_URL", "localhost:7860")
    # protocol = "https" if not host.startswith(("localhost", "127.0.0.1")) else "http"
    status_callback_url = f"{host}/call_status"
    client = TwilioClient(account_sid, auth_token)
    print(status_callback_url)
    call = client.calls.create(
        to=to_number,
        from_=from_number,
        url=twiml_url,  # TwiML instructions
        method="POST",
        status_callback=status_callback_url,
        status_callback_method="POST",
        status_callback_event=["initiated", "ringing", "answered", "completed", "no-answer", "busy", "failed"],
    )

    return {"sid": call.sid}

def batch_outbound_call(calls):
    """
    accepts a list like:
    [{
        "phone_number": "+1234567890",
        "body": {...}  # optional
    }, ...]
    """
    results = []
    
    if os.getenv("API_BASE_URL"): host = os.getenv("API_BASE_URL")  # Use API_BASE_URL if set in environment
    twimlurl = f"{host}/twiml"
    
    for call in calls:
        phonenumber = call.get("phone_number")
        bodydata = call.get("body", None)
        print(f"Initiating call to {phonenumber} with body data: {bodydata}")
        try:
            callsid = make_twilio_call(phonenumber, os.getenv("TWILIO_PHONE_NUMBER"), twimlurl)
            results.append({
                "phonenumber": phonenumber,
                "callsid": callsid.get("sid"),
                "body": bodydata,
                "status": "call_initiated"
            })
        except Exception as e:
            results.append({
                "phonenumber": phonenumber,
                "error": str(e),
                "status": "failed"
            })
    return results

