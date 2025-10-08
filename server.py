import os
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from typing import List, Optional
from pydantic import BaseModel

from twilio_manager import batch_outbound_call, generate_twiml
from hubspot_api import (
    fetch_contacts_by_lead_status,
    update_contact_lead_status,
    add_call_notes,
    HUBSPOT_LEAD_STATUS
)

load_dotenv(override=True)

# In-memory store for body data by call SID
call_body_data = {}
# Store for call results and notes
call_results = {}

# ----------------- MODELS ----------------- #

class CampaignRequest(BaseModel):
    lead_statuses: Optional[List[str]] = ["NEW", "OPEN", "ATTEMPTED_TO_CONTACT"]
    update_status_after_call: Optional[bool] = True
    max_contacts: Optional[int] = None

# ----------------- API ----------------- #

app = FastAPI(title="Outbound Call Campaign Manager")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- MAIN ENDPOINT ----------------- #

@app.post("/api/campaign/start")
async def start_campaign(request: Request, campaign_request: CampaignRequest) -> JSONResponse:
    """
    ONE-SHOT API: Fetch contacts from HubSpot and initiate calls automatically.
    
    Example payload:
    {
        "lead_statuses": ["NEW", "OPEN", "ATTEMPTED_TO_CONTACT"],
        "update_status_after_call": true,
        "max_contacts": 50
    }
    
    This single API call will:
    1. Fetch contacts from HubSpot based on lead statuses
    2. Filter contacts with valid phone numbers
    3. Initiate Twilio calls to all contacts
    4. Update HubSpot contact status to "ATTEMPTED_TO_CONTACT"
    5. Return complete results
    """
    try:
        print(f"🚀 Starting campaign for lead statuses: {campaign_request.lead_statuses}")
        
        # Step 1: Fetch contacts from HubSpot
        print("📊 Fetching contacts from HubSpot...")
        contacts = fetch_contacts_by_lead_status(campaign_request.lead_statuses)
        
        if not contacts:
            return JSONResponse({
                "success": False,
                "message": "No contacts found with specified lead statuses",
                "total_contacts": 0,
                "contacts_with_phone": 0,
                "calls_initiated": 0,
                "calls_failed": 0,
                "results": []
            })
        
        print(f"✅ Found {len(contacts)} contacts in HubSpot")
        
        # Step 2: Prepare call payload with contact data
        calls_payload = []
        contacts_data = []
        
        for contact in contacts:
            phone_number = contact.properties.get("phone")
            
            # Only include contacts with valid phone numbers
            if phone_number:
                contact_data = {
                    "contact_id": contact.id,
                    "phone_number": phone_number,
                    "firstname": contact.properties.get("firstname", ""),
                    "lastname": contact.properties.get("lastname", ""),
                    "email": contact.properties.get("email", ""),
                    "lead_status": contact.properties.get("hs_lead_status"),
                }
                
                contacts_data.append(contact_data)
                
                calls_payload.append({
                    "phone_number": phone_number,
                    "body": {
                        "contactId": contact.id,
                        "leadStatus": contact.properties.get("hs_lead_status"),
                        "firstname": contact.properties.get("firstname", ""),
                        "lastname": contact.properties.get("lastname", ""),
                        "email": contact.properties.get("email", ""),
                    }
                })
                
                # Limit number of contacts if specified
                if campaign_request.max_contacts and len(calls_payload) >= campaign_request.max_contacts:
                    print(f"⚠️ Reached maximum contacts limit: {campaign_request.max_contacts}")
                    break
        
        if not calls_payload:
            return JSONResponse({
                "success": False,
                "message": "No valid phone numbers found in contacts",
                "total_contacts": len(contacts),
                "contacts_with_phone": 0,
                "calls_initiated": 0,
                "calls_failed": 0,
                "results": []
            })
        
        print(f"📞 Preparing to call {len(calls_payload)} contacts with valid phone numbers")
        
        # Step 3: Initiate batch calls via Twilio
        print("☎️ Initiating Twilio calls...")
        results = batch_outbound_call(calls_payload)
        
        # Step 4: Store body data for each call and count results
        calls_initiated = 0
        calls_failed = 0
        
        for result in results:
            if result.get("status") == "call_initiated":
                call_sid = result.get("callsid")
                body = result.get("body")
                if call_sid and body:
                    call_body_data[call_sid] = body
                calls_initiated += 1
            else:
                calls_failed += 1
        
        print(f"✅ Calls initiated: {calls_initiated}")
        print(f"❌ Calls failed: {calls_failed}")
        
        # Step 5: Update HubSpot contact status
        if campaign_request.update_status_after_call:
            print("📝 Updating HubSpot contact statuses...")
            updated_count = 0
            for result in results:
                if result.get("status") == "call_initiated":
                    contact_id = result.get("body", {}).get("contactId")
                    if contact_id:
                        try:
                            update_contact_lead_status(
                                contact_id, 
                                HUBSPOT_LEAD_STATUS.ATTEMPTED_TO_CONTACT
                            )
                            updated_count += 1
                        except Exception as e:
                            print(f"⚠️ Failed to update contact {contact_id}: {e}")
            
            print(f"✅ Updated {updated_count} contacts in HubSpot")
        
        # Step 6: Return comprehensive results
        return JSONResponse({
            "success": True,
            "message": "Campaign started successfully",
            "total_contacts_found": len(contacts),
            "contacts_with_phone": len(calls_payload),
            "calls_initiated": calls_initiated,
            "calls_failed": calls_failed,
            "hubspot_updated": campaign_request.update_status_after_call,
            "contacts_data": contacts_data,
            "call_results": results,
            "summary": {
                "success_rate": f"{(calls_initiated / len(calls_payload) * 100):.2f}%" if calls_payload else "0%",
                "total_processed": len(calls_payload),
                "timestamp": __import__('datetime').datetime.now().isoformat()
            }
        })
        
    except Exception as e:
        print(f"❌ Error starting campaign: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Campaign failed: {str(e)}")


@app.post("/call_status")
async def twilio_call_status_webhook(request: Request):
    """
    Webhook endpoint for Twilio call status updates.
    Automatically called by Twilio during call lifecycle.
    """
    try:
        form_data = await request.form()
        
        call_sid = form_data.get("CallSid")
        call_status = form_data.get("CallStatus")
        call_duration = form_data.get("CallDuration", "0")
        
        print(f"📡 Call status update: {call_sid} - {call_status} - Duration: {call_duration}s")
        
        # Get contact data for this call
        body_data = call_body_data.get(call_sid, {})
        contact_id = body_data.get("contactId")
        
        # Log the status update
        if call_sid not in call_results:
            call_results[call_sid] = {
                "contact_id": contact_id,
                "body_data": body_data
            }
        
        call_results[call_sid]["twilio_status"] = call_status
        call_results[call_sid]["call_duration"] = call_duration
        
        # Auto-update HubSpot based on call status
        if contact_id:
            if call_status == "completed":
                # Call was successful - will be updated by bot based on conversation
                print(f"✅ Call completed for contact {contact_id}")
                
            elif call_status in ["no-answer", "busy", "failed"]:
                # Call failed - update to ATTEMPTED_TO_CONTACT
                update_contact_lead_status(contact_id, HUBSPOT_LEAD_STATUS.ATTEMPTED_TO_CONTACT)
                
                # Add failure note
                add_call_notes(contact_id, {
                    "Call Status": call_status,
                    "Call SID": call_sid,
                    "Timestamp": __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Note": f"Outbound call {call_status}"
                })
                print(f"⚠️ Call {call_status} for contact {contact_id} - HubSpot updated")
        
        return JSONResponse({"status": "received"})
        
    except Exception as e:
        print(f"❌ Error processing call status webhook: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/twiml")
async def get_twiml(request: Request) -> HTMLResponse:
    """Return TwiML instructions for connecting call to WebSocket."""
    print("📞 Serving TwiML for outbound call")
    
    try:
        form_data = await request.form()
        call_sid = form_data.get("CallSid", "")
        
        print(f"📋 Received form data: {dict(form_data)}")
        
        # Retrieve body data for this call
        body_data = call_body_data.get(call_sid, {})
        
        print(f"📋 TwiML for CallSid: {call_sid}, Contact: {body_data.get('contactId')}")
        print(f"📦 Body data from storage: {body_data}")
        
        # Get the server host to construct WebSocket URL
        host = "zvjk3c9x-7860.inc1.devtunnels.ms"
        if not host:
            host = os.getenv("API_BASE_URL", "localhost:7860")
        
        print(f"🌐 Using host for WebSocket: {host}")
        
        # Generate TwiML with body data parameter
        print(f"🔧 Calling generate_twiml with host: {host}, body_data: {body_data}")
        twiml_content = generate_twiml(host, body_data)
        
        print(f"✅ Generated TwiML content:")
        print(f"{'='*60}")
        print(twiml_content)
        print(f"{'='*60}")
        
        return HTMLResponse(content=twiml_content, media_type="application/xml")
        
    except Exception as e:
        print(f"❌ Error generating TwiML: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle WebSocket connection from Twilio Media Streams."""
    await websocket.accept()
    print("🔌 WebSocket connection accepted for outbound call")
    
    try:
        from bot import bot
        from pipecat.runner.types import WebSocketRunnerArguments
        
        runner_args = WebSocketRunnerArguments(websocket=websocket)
        runner_args.handle_sigint = False
        
        await bot(runner_args)
        
    except Exception as e:
        print(f"❌ Error in WebSocket endpoint: {e}")
        await websocket.close()


@app.get("/api/campaign/status")
async def get_campaign_status() -> JSONResponse:
    """Get status of all calls in the current campaign."""
    return JSONResponse({
        "active_calls": len(call_body_data),
        "completed_calls": len(call_results),
        "call_details": call_results
    })


@app.get("/")
async def root():
    """API documentation endpoint."""
    return JSONResponse({
        "name": "Outbound Call Campaign Manager",
        "description": "ONE-SHOT API to fetch HubSpot contacts and initiate Twilio calls",
        "version": "1.0",
        "main_endpoint": {
            "url": "/api/campaign/start",
            "method": "POST",
            "description": "Fetch contacts from HubSpot and start calling - ALL IN ONE",
            "example": {
                "lead_statuses": ["NEW", "OPEN", "ATTEMPTED_TO_CONTACT"],
                "update_status_after_call": True,
                "max_contacts": 50
            }
        },
        "other_endpoints": {
            "/api/campaign/status": "GET - Get current campaign status",
            "/call_status": "POST - Twilio webhook for call status updates",
            "/twiml": "POST - TwiML endpoint for Twilio",
            "/ws": "WebSocket - Media stream handler"
        }
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    print("=" * 60)
    print("🚀 Starting Outbound Call Campaign Server")
    print("=" * 60)
    print(f"📍 Port: {port}")
    print(f"🌐 API URL: http://localhost:{port}/")
    print(f"📖 Documentation: http://localhost:{port}/")
    print("=" * 60)
    print("\n💡 Main Endpoint: POST /api/campaign/start")
    print("   - Fetches HubSpot contacts")
    print("   - Initiates Twilio calls")
    print("   - Updates HubSpot status")
    print("   - All in ONE API call!\n")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=port)