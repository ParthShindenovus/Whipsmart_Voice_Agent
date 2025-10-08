import requests
from hubspot_api import fetch_contacts_by_lead_status
from  twilio_manager import batch_outbound_call

API_BASE_URL = "https://zvjk3c9x-7860.inc1.devtunnels.ms"  # Change to your server address if needed

def start_campaign():
    lead_statuses = ["NEW", "OPEN", "ATTEMPTED_TO_CONTACT"]
    contacts = fetch_contacts_by_lead_status(lead_statuses)
    print(f"Starting calls for {len(contacts)} contacts.")

    calls_payload = []
    for contact in contacts:
        phonenumber = contact.properties.get("phone")
        if phonenumber:
            calls_payload.append({
                "phone_number": phonenumber,
                "body": {
                    "contactId": contact.id,
                    "leadStatus": contact.properties.get("hs_lead_status"),
                }
            })

    if calls_payload:
        print(f"Initiating calls to {len(calls_payload)} contacts.")
        response = batch_outbound_call(calls_payload)
        return response
    else:
        return {"message": "No contacts to call"}
