from hubspot import HubSpot
from hubspot.crm.contacts.models import Filter, FilterGroup, PublicObjectSearchRequest
from hubspot.crm.deals import ApiException
from hubspot.crm.deals import SimplePublicObjectInput

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# ------------ CONFIG ------------
access_token = os.getenv("HUBSPOT_ACCESS_TOKEN")

if not access_token:
    raise ValueError("Missing HubSpot access token in environment variables")

client = HubSpot(access_token=access_token)

from enum import Enum

class HUBSPOT_LEAD_STATUS(str, Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    OPEN_DEAL = "OPEN_DEAL"
    UNQUALIFIED = "UNQUALIFIED"
    ATTEMPTED_TO_CONTACT = "ATTEMPTED_TO_CONTACT"
    CONNECTED = "CONNECTED"
    BAD_TIMING = "BAD_TIMING"



# ------------ FUNCTIONS ------------

def fetch_contacts_by_lead_status(lead_status_values: HUBSPOT_LEAD_STATUS):
    # lead_status_values should be: ["New", "Open", "Attempted To Connect"], etc.
    filters = [
        Filter(property_name="hs_lead_status", operator="IN", values=lead_status_values)
    ]
    # print(filters)
    filter_group = FilterGroup(filters=filters)
    search_request = PublicObjectSearchRequest(
        filter_groups=[filter_group],
        properties=["firstname", "lastname", "email", "phone", "hs_lead_status"],
        limit=100
    )
    # print(search_request)
    try:
        # all_contacts = client.crm.contacts.basic_api.get_page(limit=5, properties=["firstname", "lastname", "email", "hs_lead_status"])
        # for c in all_contacts.results:
        #     print(c.properties)
        response = client.crm.contacts.search_api.do_search(public_object_search_request=search_request)
        return response.results
    except ApiException as e:
        print(f"Exception when fetching contacts: {e}")
        return []
    
def update_contact_lead_status(contact_id, new_status: HUBSPOT_LEAD_STATUS):
    """
    Update the lead status of a contact in HubSpot given contact ID and new status value.
    """
    try:
        update_properties = {
            "hs_lead_status": new_status
        }
        simple_object = SimplePublicObjectInput(properties=update_properties)

        client.crm.contacts.basic_api.update(contact_id=contact_id, simple_public_object_input=simple_object)
        print(f"Updated contact {contact_id} lead status to {new_status}")
        return True
    except ApiException as e:
        print(f"Exception when updating contact lead status: {e}")
        return False

def create_deal_for_contact(contact_id: str, deal_name: str = "Novated Leasing Deal"):
    """Create a simple deal linked to the contact."""
    deal = SimplePublicObjectInput(
        properties={
            "dealname": deal_name,
            "dealstage": "appointmentscheduled",  # change according to your pipeline
            "pipeline": "default",
        }
    )
    created_deal = client.crm.deals.basic_api.create(deal)
    
    # Associate deal with contact
    client.crm.associations.v4.basic_api.create_default(
        from_object_type="deals",          # source object type
        from_object_id=created_deal.id,    # source object id
        to_object_type="contacts",    # target object type
        to_object_id=contact_id,      # target object id
    )
    print(f"Created deal {created_deal.id} for contact {contact_id}")

import time
from hubspot.crm.objects import SimplePublicObjectInput

def add_call_notes(contact_id: str, notes: dict):
    """Add call outcome / transcription as engagement note."""
    note_text = "\n".join([f"{k}: {v}\n\n" for k, v in notes.items()])

    # HubSpot requires hs_timestamp
    timestamp_ms = int(time.time() * 1000)  # current time in milliseconds

    simple_note = SimplePublicObjectInput(
        properties={
            "hs_note_body": note_text,
            "hs_timestamp": timestamp_ms
        }
    )

    # Create the note
    created_note = client.crm.objects.notes.basic_api.create(
        simple_public_object_input_for_create=simple_note
    )
    
    # Associate note with contact
    client.crm.associations.v4.basic_api.create_default(
        from_object_type="notes",          # source object type
        from_object_id=created_note.id,    # source object id
        to_object_type="contacts",    # target object type
        to_object_id=contact_id,      # target object id
    )

    print(f"Added notes to contact {contact_id}")


# ------------ USAGE EXAMPLES ------------

# 1. Fetch leads that are not contacted yet
# leads = fetch_contacts_by_lead_status(["New", "Open", "Attempted To Connect"])
# for lead in leads:
#     print(lead.properties)

# 2. When a user is interested, create a deal:
# Replace "CONTACT_ID" and "Deal Name" with actual values
# new_deal = create_deal_for_contact("Deal Name", "CONTACT_ID", amount=5000)
