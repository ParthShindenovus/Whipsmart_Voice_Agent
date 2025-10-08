"""
WhipSmart Outbound Call Flow - Lead Generation System
Handles novated leasing program discussions with company managers
"""

from pipecat_flows import FlowManager, FlowsFunctionSchema, FlowArgs, NodeConfig
from typing import Tuple
from loguru import logger
import json
import time
from utils.funtions import client, RAG_MODEL, RAG_PROMPT 


# ============================================================================
# FUNCTION HANDLERS - These process user responses and manage flow transitions
# ============================================================================

async def capture_manager_details(
    args: FlowArgs, 
    flow_manager: FlowManager
) -> Tuple[str, NodeConfig]:
    """
    Capture the manager's name and company name at the start of the call.
    
    Args:
        manager_name: The name of the person we're speaking with
        company_name: The name of their company
    """
    manager_name = args.get("manager_name", "Not provided")
    company_name = args.get("company_name", "Not provided")
    
    flow_manager.state["manager_name"] = manager_name
    flow_manager.state["company_name"] = company_name
    
    logger.info(f"Captured details - Manager: {manager_name}, Company: {company_name}")
    
    return f"Lovely to speak with you, {manager_name}!", create_ask_provider_node()


async def handle_has_provider_response(
    args: FlowArgs,
    flow_manager: FlowManager
) -> Tuple[str, NodeConfig]:
    """
    Handle the response about whether they have a novated lease provider.
    Routes to appropriate scenario (A or B).
    
    Args:
        has_provider: Boolean indicating if they have a provider (true/false)
    """
    has_provider = args.get("has_provider", False)
    flow_manager.state["has_existing_provider"] = has_provider
    
    if has_provider:
        logger.info("Company has existing provider - Scenario A")
        return "Right, I see.", create_ask_provider_name_node()
    else:
        logger.info("Company has no provider - Scenario B")
        flow_manager.state["current_provider"] = "None"
        return "No worries, I understand.", create_scenario_b_pitch_node()


async def capture_provider_name(
    args: FlowArgs,
    flow_manager: FlowManager
) -> Tuple[str, NodeConfig]:
    """
    Capture the name of their current novated lease provider.
    
    Args:
        provider_name: Name of their current provider
    """
    provider_name = args.get("provider_name", "Not specified")
    flow_manager.state["current_provider"] = provider_name
    
    logger.info(f"Current provider: {provider_name}")
    
    return f"Thanks for that. {provider_name} is a solid choice.", create_scenario_a_pitch_node()


async def query_knowledge_base(
    args: FlowArgs,
    flow_manager: FlowManager
) -> Tuple[str, None]:
    """
    Query WhipSmart knowledge base for FAQs and information.
    This function does NOT change the conversation node - it only provides information.
    
    Args:
        question: The user's question about WhipSmart, benefits, or novated leasing
    """
    question = args.get("question", "")
    logger.info(f"Knowledge base query in flow: {question}")
    
    # Get conversation history from context aggregator
    all_messages = flow_manager.get_current_context()
    
    # Filter to get actual conversation (skip system/task messages and tool calls)
    def _is_tool_call(turn):
        if turn.get("role", None) == "tool":
            return True
        if turn.get("tool_calls", None):
            return True
        return False
    
    # Get conversation turns (skip initial system messages)
    conversation_turns = [msg for msg in all_messages if msg.get("role") in ["user", "assistant"]]
    
    # Filter out tool calls
    messages = [turn for turn in conversation_turns if not _is_tool_call(turn)]
    
    # Use the last 3 turns as conversation history/context
    messages = messages[-3:]
    messages_json = json.dumps(messages, ensure_ascii=False, indent=2)
    
    logger.info(f"Conversation history for RAG: {messages_json}")
    
    start = time.perf_counter()
    full_prompt = f"System: {RAG_PROMPT}\n\nConversation History: {messages_json}\n\nUser Question: {question}"
    
    try:
        response = await client.aio.models.generate_content(
            model=RAG_MODEL,
            contents=[full_prompt],
            config={
                "temperature": 0.1,
                "max_output_tokens": 128,
            },
        )
        end = time.perf_counter()
        logger.info(f"RAG query time: {end - start:.2f} seconds")
        logger.info(f"RAG response: {response.text}")
        
        return response.text, None
        
    except Exception as e:
        logger.error(f"Error querying knowledge base: {e}")
        fallback_response = "Sorry mate, I'm having a bit of trouble accessing that information right now. Let me continue with our chat about WhipSmart's novated leasing program."
        return fallback_response, None


async def handle_meeting_response(
    args: FlowArgs,
    flow_manager: FlowManager
) -> Tuple[str, NodeConfig]:
    """
    Handle the response to meeting invitation.
    
    Args:
        accepts_meeting: Boolean - true if they want to schedule, false if declined
        meeting_date: Optional - specific date for the meeting (e.g., "next Monday", "15th June")
        meeting_time: Optional - specific time for the meeting (e.g., "10am", "2:30pm")
    """
    accepts_meeting = args.get("accepts_meeting", False)
    meeting_date = args.get("meeting_date", None)
    meeting_time = args.get("meeting_time", None)
    
    if accepts_meeting:
        flow_manager.state["meeting_status"] = "Interested - To Be Scheduled"
        
        # Capture date and time separately
        flow_manager.state["meeting_date"] = meeting_date if meeting_date else "To be confirmed"
        flow_manager.state["meeting_time"] = meeting_time if meeting_time else "To be confirmed"
        
        # Also store combined for compatibility
        if meeting_date and meeting_time:
            flow_manager.state["meeting_day_time"] = f"{meeting_date} at {meeting_time}"
        elif meeting_date:
            flow_manager.state["meeting_day_time"] = meeting_date
        else:
            flow_manager.state["meeting_day_time"] = "To be confirmed"
        
        flow_manager.state["interested_in_novated_leasing"] = True
        
        logger.info(f"Meeting accepted - Date: {meeting_date}, Time: {meeting_time}")
        
        return "Brilliant! I'll get that sorted for you.", create_collect_email_node(for_meeting=True)
    else:
        flow_manager.state["meeting_status"] = "Declined"
        flow_manager.state["interested_in_novated_leasing"] = False
        
        logger.info("Meeting declined - offering email summary")
        
        return "No worries at all, mate.", create_offer_email_summary_node()


async def handle_email_summary_response(
    args: FlowArgs,
    flow_manager: FlowManager
) -> Tuple[str, NodeConfig]:
    """
    Handle response to email summary offer.
    
    Args:
        wants_summary: Boolean - true if they want the summary, false if not interested
    """
    wants_summary = args.get("wants_summary", False)
    
    if wants_summary:
        flow_manager.state["send_summary_email"] = True
        logger.info("User wants email summary")
        return "Ripper!", create_collect_email_node(for_meeting=False)
    else:
        flow_manager.state["send_summary_email"] = False
        flow_manager.state["interested_in_novated_leasing"] = False
        logger.info("User declined email summary - ending call")
        return "Fair enough, I completely understand.", create_end_call_node()


async def capture_email_address(
    args: FlowArgs,
    flow_manager: FlowManager
) -> Tuple[str, NodeConfig]:
    """
    Capture the user's email address for follow-up.
    
    Args:
        email: The user's email address
    """
    email = args.get("email", "Not provided")
    flow_manager.state["email_address"] = email
    
    logger.info(f"Email captured: {email}")
    
    # Log final lead data
    log_lead_data(flow_manager)
    
    return f"Perfect, I've got that down as {email}.", create_end_call_node()


async def finalize_and_update_crm(
    args: FlowArgs,
    flow_manager: FlowManager
) -> Tuple[str, None]:
    """
    Final action to update CRM before ending call.
    """
    logger.info("Finalizing call and updating CRM")
    
    outcome = flow_manager.state
    contact_id = flow_manager.state.get("contact_id")
    
    if contact_id:
        try:
            from service.hubspot_service import update_contact_lead_status, add_call_notes, create_deal_for_contact, HUBSPOT_LEAD_STATUS
            
            # Add call notes with date and time
            add_call_notes(contact_id, {
                "Manager Name": outcome.get("manager_name"),
                "Company Name": outcome.get("company_name"),
                "Current Provider": outcome.get("current_provider"),
                "Meeting Status": outcome.get("meeting_status"),
                "Meeting Date": outcome.get("meeting_date"),
                "Meeting Time": outcome.get("meeting_time"),
                "Meeting Day/Time": outcome.get("meeting_day_time"),
                "Email Address": outcome.get("email_address"),
                "Interested": outcome.get("interested_in_novated_leasing"),
                "Has Existing Provider": outcome.get("has_existing_provider")
            })
            
            # Update lead status
            if outcome.get("interested_in_novated_leasing"):
                update_contact_lead_status(contact_id, HUBSPOT_LEAD_STATUS.OPEN_DEAL)
                create_deal_for_contact(contact_id)
            else:
                update_contact_lead_status(contact_id, HUBSPOT_LEAD_STATUS.CONNECTED)
                
            logger.info("CRM update completed successfully")
        except Exception as e:
            logger.error(f"Error updating CRM: {e}")
    
    return "Cheers for your time!", None


def log_lead_data(flow_manager: FlowManager):
    """Log all captured lead data for CRM integration"""
    lead_data = {
        "manager_name": flow_manager.state.get("manager_name", "None"),
        "company_name": flow_manager.state.get("company_name", "None"),
        "current_provider": flow_manager.state.get("current_provider", "None"),
        "meeting_status": flow_manager.state.get("meeting_status", "Not Discussed"),
        "meeting_date": flow_manager.state.get("meeting_date", "None"),
        "meeting_time": flow_manager.state.get("meeting_time", "None"),
        "meeting_day_time": flow_manager.state.get("meeting_day_time", "None"),
        "email_address": flow_manager.state.get("email_address", "None"),
        "interested_in_novated_leasing": flow_manager.state.get("interested_in_novated_leasing", False),
        "send_summary_email": flow_manager.state.get("send_summary_email", False),
    }
    
    logger.info(f"LEAD DATA CAPTURED: {lead_data}")
    return lead_data


# ============================================================================
# NODE CREATION FUNCTIONS - Define conversation states
# ============================================================================

def create_initial_greeting_node() -> NodeConfig:
    """
    Initial greeting and introduction node.
    Sets the bot's personality and captures basic information.
    """
    capture_details_func = FlowsFunctionSchema(
        name="capture_manager_details",
        description="Capture the manager's name and company name once they've introduced themselves.",
        required=["manager_name", "company_name"],
        handler=capture_manager_details,
        properties={
            "manager_name": {
                "type": "string",
                "description": "The name of the manager we're speaking with"
            },
            "company_name": {
                "type": "string", 
                "description": "The name of the company"
            }
        }
    )
    
    knowledge_base_func = FlowsFunctionSchema(
        name="query_knowledge_base",
        description="Use this when the user asks questions about WhipSmart, novated leasing benefits, or any FAQs. This provides detailed information without changing the conversation flow.",
        required=["question"],
        handler=query_knowledge_base,
        properties={
            "question": {
                "type": "string",
                "description": "The user's question or topic they want to know more about"
            }
        }
    )
    
    return {
        "name": "initial_greeting",
        "role_messages": [
            {
                "role": "system",
                "content": """You are Alex, a professional outbound call assistant for WhipSmart in Australia. 
You speak with an Australian professional style - friendly, down-to-earth, and respectful.
Use Australian expressions naturally like 'no worries', 'reckon', 'cheers', 'mate' (when appropriate), 'brilliant', 'ripper' (sparingly).
Keep your responses SHORT and CONVERSATIONAL - you're having a chat, not writing a letter.
Use simple Australian English suitable for text-to-speech.
Never use special characters, emojis, or complex formatting.
Your goal is to have a respectful yarn about novated leasing programs for electric vehicles."""
            }
        ],
        "task_messages": [
            {
                "role": "system",
                "content": """G'day! Greet the person warmly in Australian professional style. Introduce yourself as Alex from WhipSmart.
Say something like: 'G'day, this is Alex calling from WhipSmart. How are you going today?'
Briefly mention you're reaching out to discuss novated leasing programs for electric vehicles.
Ask if you're speaking with the right person who handles employee benefits or fleet management.
Once they confirm and share their name and company, use the capture_manager_details function.
Keep it friendly and brief. If they ask questions about WhipSmart, use the query_knowledge_base function."""
            }
        ],
        "functions": [capture_details_func, knowledge_base_func],
        "respond_immediately": True
    }


def create_ask_provider_node() -> NodeConfig:
    """
    Ask if they currently have a novated lease provider.
    This determines which scenario (A or B) to follow.
    """
    provider_response_func = FlowsFunctionSchema(
        name="handle_has_provider_response",
        description="Record whether the company currently has a novated lease provider. Use this after they answer yes or no.",
        required=["has_provider"],
        handler=handle_has_provider_response,
        properties={
            "has_provider": {
                "type": "boolean",
                "description": "True if they have a provider, false if they don't"
            }
        }
    )
    
    knowledge_base_func = FlowsFunctionSchema(
        name="query_knowledge_base",
        description="Use this when the user asks questions about WhipSmart, novated leasing benefits, or any FAQs.",
        required=["question"],
        handler=query_knowledge_base,
        properties={
            "question": {"type": "string", "description": "The user's question"}
        }
    )
    
    return {
        "name": "ask_provider",
        "task_messages": [
            {
                "role": "system",
                "content": """Ask if their company currently offers a novated lease provider to employees.
Keep it casual and direct. Say something like: 'Can I ask, does your mob currently have a novated lease provider for your team?'
Wait for their answer, then use the handle_has_provider_response function.
If they ask questions, use query_knowledge_base."""
            }
        ],
        "functions": [provider_response_func, knowledge_base_func],
        "respond_immediately": True
    }


def create_ask_provider_name_node() -> NodeConfig:
    """
    Scenario A: They have a provider - ask who it is.
    """
    capture_provider_func = FlowsFunctionSchema(
        name="capture_provider_name",
        description="Record the name of their current novated lease provider.",
        required=["provider_name"],
        handler=capture_provider_name,
        properties={
            "provider_name": {
                "type": "string",
                "description": "The name of their current provider"
            }
        }
    )
    
    knowledge_base_func = FlowsFunctionSchema(
        name="query_knowledge_base",
        description="Use this when the user asks questions about WhipSmart or novated leasing.",
        required=["question"],
        handler=query_knowledge_base,
        properties={
            "question": {"type": "string", "description": "The user's question"}
        }
    )
    
    return {
        "name": "ask_provider_name",
        "task_messages": [
            {
                "role": "system",
                "content": """Ask who their current novated lease provider is.
Keep it conversational: 'That's great. May I ask who you're working with at the moment?'
Once they tell you, use capture_provider_name function.
If they ask questions, use query_knowledge_base."""
            }
        ],
        "functions": [capture_provider_func, knowledge_base_func],
        "respond_immediately": True
    }


def create_scenario_a_pitch_node() -> NodeConfig:
    """
    Scenario A: Pitch WhipSmart's EV program to companies with existing providers.
    """
    meeting_response_func = FlowsFunctionSchema(
        name="handle_meeting_response",
        description="Record the user's response to the meeting invitation, including specific date and time if provided.",
        required=["accepts_meeting"],
        handler=handle_meeting_response,
        properties={
            "accepts_meeting": {
                "type": "boolean",
                "description": "True if they want to schedule a meeting, false if they decline"
            },
            "meeting_date": {
                "type": "string",
                "description": "The specific date for the meeting (e.g., 'next Monday', 'Tuesday the 15th', 'next week')"
            },
            "meeting_time": {
                "type": "string",
                "description": "The specific time for the meeting (e.g., '10am', '2:30pm', 'morning', 'afternoon')"
            }
        }
    )
    
    knowledge_base_func = FlowsFunctionSchema(
        name="query_knowledge_base",
        description="Use this when the user asks questions about WhipSmart or novated leasing.",
        required=["question"],
        handler=query_knowledge_base,
        properties={
            "question": {"type": "string", "description": "The user's question"}
        }
    )
    
    return {
        "name": "scenario_a_pitch",
        "task_messages": [
            {
                "role": "system",
                "content": """Acknowledge their current provider positively in Australian style.
Then briefly pitch WhipSmart's all-inclusive EV novated lease program.
Key points: we specialise in electric vehicles, comprehensive package, competitive rates.
Keep it SHORT - 2 or 3 sentences maximum.
Then offer: 'Would you be up for a quick 15-minute chat next week to explore how we could complement what you've already got?'
If they accept, ask: 'What day and time works best for you next week?'
Use handle_meeting_response function after they respond with their availability.
If they ask questions first, use query_knowledge_base."""
            }
        ],
        "functions": [meeting_response_func, knowledge_base_func],
        "respond_immediately": True
    }


def create_scenario_b_pitch_node() -> NodeConfig:
    """
    Scenario B: Pitch to companies without a provider.
    """
    meeting_response_func = FlowsFunctionSchema(
        name="handle_meeting_response",
        description="Record the user's response to the meeting invitation, including specific date and time if provided.",
        required=["accepts_meeting"],
        handler=handle_meeting_response,
        properties={
            "accepts_meeting": {
                "type": "boolean",
                "description": "True if they want to schedule a meeting, false if they decline"
            },
            "meeting_date": {
                "type": "string",
                "description": "The specific date for the meeting (e.g., 'next Monday', 'Tuesday the 15th', 'next week')"
            },
            "meeting_time": {
                "type": "string",
                "description": "The specific time for the meeting (e.g., '10am', '2:30pm', 'morning', 'afternoon')"
            }
        }
    )
    
    knowledge_base_func = FlowsFunctionSchema(
        name="query_knowledge_base",
        description="Use this when the user asks questions about WhipSmart or novated leasing.",
        required=["question"],
        handler=query_knowledge_base,
        properties={
            "question": {"type": "string", "description": "The user's question"}
        }
    )
    
    return {
        "name": "scenario_b_pitch",
        "task_messages": [
            {
                "role": "system",
                "content": """Acknowledge respectfully that they don't have a provider in Australian style.
Briefly explain the benefits: novated leasing helps your employees save on tax, get better vehicle deals, and it's a zero-cost benefit for you as the employer.
WhipSmart specialises in electric vehicles with a full-service program.
Keep it SHORT - 2 or 3 sentences.
Then offer: 'Would you be keen for a quick 15-minute chat next week to learn more?'
If they accept, ask: 'What day and time suits you best next week?'
Use handle_meeting_response function after they respond with their availability.
If they ask questions first, use query_knowledge_base."""
            }
        ],
        "functions": [meeting_response_func, knowledge_base_func],
        "respond_immediately": True
    }


def create_offer_email_summary_node() -> NodeConfig:
    """
    Offer to send a one-page email summary if they declined the meeting.
    """
    email_summary_func = FlowsFunctionSchema(
        name="handle_email_summary_response",
        description="Record if they want the email summary.",
        required=["wants_summary"],
        handler=handle_email_summary_response,
        properties={
            "wants_summary": {
                "type": "boolean",
                "description": "True if they want the email summary, false if not interested"
            }
        }
    )
    
    knowledge_base_func = FlowsFunctionSchema(
        name="query_knowledge_base",
        description="Use this when the user asks questions about WhipSmart or novated leasing.",
        required=["question"],
        handler=query_knowledge_base,
        properties={
            "question": {"type": "string", "description": "The user's question"}
        }
    )
    
    return {
        "name": "offer_email_summary",
        "task_messages": [
            {
                "role": "system",
                "content": """Politely acknowledge they're not keen on a meeting in Australian style.
Offer to send them a one-page summary by email instead: 'Would it be helpful if I shot you a brief one-page summary by email instead?'
Keep it light and non-pushy.
Use handle_email_summary_response after they respond.
If they ask questions, use query_knowledge_base."""
            }
        ],
        "functions": [email_summary_func, knowledge_base_func],
        "respond_immediately": True
    }


def create_collect_email_node(for_meeting: bool = False) -> NodeConfig:
    """
    Collect email address for meeting confirmation or summary.
    
    Args:
        for_meeting: True if collecting for meeting, False if for summary
    """
    email_capture_func = FlowsFunctionSchema(
        name="capture_email_address",
        description="Record the user's email address.",
        required=["email"],
        handler=capture_email_address,
        properties={
            "email": {
                "type": "string",
                "description": "The user's email address"
            }
        }
    )
    
    knowledge_base_func = FlowsFunctionSchema(
        name="query_knowledge_base",
        description="Use this when the user asks questions about WhipSmart or novated leasing.",
        required=["question"],
        handler=query_knowledge_base,
        properties={
            "question": {"type": "string", "description": "The user's question"}
        }
    )
    
    purpose = "send you the meeting invite" if for_meeting else "shoot you that summary"
    
    return {
        "name": "collect_email",
        "task_messages": [
            {
                "role": "system",
                "content": f"""Ask for their email address to {purpose} in Australian style.
Keep it simple: 'What's the best email address to {purpose}?'
Once they provide it, use capture_email_address function.
Confirm the email back to them to make sure it's spot on.
If they ask questions, use query_knowledge_base."""
            }
        ],
        "functions": [email_capture_func, knowledge_base_func],
        "respond_immediately": True
    }


def create_end_call_node() -> NodeConfig:
    """
    Gracefully end the conversation in Australian professional style.
    """
    finalize_crm_func = FlowsFunctionSchema(
        name="finalize_and_update_crm",
        description="Internal function to finalize call and update CRM",
        required=[],
        handler=finalize_and_update_crm,
        properties={}
    )
    
    return {
        "name": "end_call",
        "task_messages": [
            {
                "role": "system",
                "content": """Thank them professionally in Australian style.
If they accepted a meeting or email: Let them know you'll follow up soon. Say something like: 'I'll get that sorted for you straightaway.'
If they declined: Thank them anyway and wish them well. Say something like: 'Thanks so much for your time today. Have a ripper day!'
Keep it brief and friendly.
After thanking them, use the finalize_and_update_crm function to complete the call."""
            }
        ],
        "functions": [finalize_crm_func],
        "post_actions": [
            {
                "type": "end_conversation"
            }
        ],
        "respond_immediately": True
    }


# ============================================================================
# FLOW MANAGER INITIALIZATION
# ============================================================================

async def initialize_whipsmart_flow(
    task,
    llm,
    context_aggregator,
    transport,
    contact_id: str = None
) -> FlowManager:
    """
    Initialize the WhipSmart outbound call flow.
    
    Args:
        task: PipelineTask instance
        llm: LLMService instance
        context_aggregator: Context aggregator instance
        transport: Transport instance
        contact_id: HubSpot contact ID for CRM updates
        
    Returns:
        Initialized FlowManager ready to handle calls
    """
    # Initialize state dictionary for lead data
    initial_state = {
        "contact_id": contact_id,
        "manager_name": None,
        "company_name": None,
        "current_provider": None,
        "meeting_status": "Not Discussed",
        "meeting_date": None,
        "meeting_time": None,
        "meeting_day_time": None,
        "email_address": None,
        "interested_in_novated_leasing": False,
        "send_summary_email": False,
        "has_existing_provider": None
    }
    
    # Create flow manager with dynamic flow pattern
    flow_manager = FlowManager(
        task=task,
        llm=llm,
        context_aggregator=context_aggregator,
        transport=transport
    )
    
    # Initialize state
    flow_manager.state.update(initial_state)
    
    logger.info("WhipSmart outbound call flow initialized successfully")
    
    return flow_manager