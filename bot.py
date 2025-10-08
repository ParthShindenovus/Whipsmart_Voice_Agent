#
# Copyright (c) 2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import os
import sys
import random
from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transcriptions.language import Language
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.frames.frames import LLMRunFrame
# from pipecat.services.azure.stt import AzureSTTService
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.services.azure.tts import AzureTTSService
from pipecat.services.azure.llm import AzureLLMService
# from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.base_transport import BaseTransport
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.transcript_processor import TranscriptProcessor
from pipecat.processors.user_idle_processor import UserIdleProcessor
from pipecat.observers.loggers.user_bot_latency_log_observer import UserBotLatencyLogObserver
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from funtions import query_knowledge_base, end_conversation
from function_schema import query_knowledge_base_schema, end_conversation_schema
from prompt import SYSTEM_PROMPT
from transcript_processor import TranscriptHandler
from user_idle_handler import handle_user_idle  
from agent_flow import initialize_whipsmart_flow, create_initial_greeting_node
from hubspot_api import update_contact_lead_status, add_call_notes, create_deal_for_contact, HUBSPOT_LEAD_STATUS
load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

GOAL_INSTRUCTION = """
### Your Goals:
1. Build rapport with a friendly and respectful introduction.
2. Ask whether the company currently offers a novated lease (salary sacrifice option).
3. Follow the correct scenario based on their response:
   - **Scenario A (Yes, they have a provider):**
     - Ask who the provider is.
     - Acknowledge positively.
     - Pitch WhipSmart’s all-inclusive EV novated lease program.
     - Try to book a 15-minute meeting next week.
     - If they decline, politely ask if you can send a 1-page summary by email.
   - **Scenario B (No, they don’t have a provider):**
     - Acknowledge respectfully.
     - Explain the benefits of novated leasing and WhipSmart’s zero-cost solution.
     - Try to book a 15-minute meeting next week.
     - If they decline, politely ask if you can send a 1-page summary by email.

### Conversation Rules:
- Answer should be short and to the point.
- Your response will be turned into speech so use only simple words and punctuation
- Always stay polite, confident, and respectful of time.
- Never push beyond one re-offer: first the meeting, then the email.
- End conversations professionally if they are not interested.
- You have access to the tool, query_knowledge_base, that allows you to query the knowledge base for the answer to the user's question related to whipsmart, benefits and employee benefits and some FAQ.

### Memory:
During the call, capture and store:
- Manager’s Name
- Company Name
- Current Provider (if any)
- Meeting Status (Booked / Declined)
- Meeting Day & Time (if booked)
- Email Address (if provided)
"""

SYSTEM_INSTRUCTION = f"""
You are Alex WhipSmart’s professional outbound call assistant and you are an Australian so speak like an Australian Professional. 
You are calling company managers (but you don't have name) to discuss employee benefits, 
specifically novated leasing programs for electric vehicles.

{GOAL_INSTRUCTION}
"""


async def run_bot(transport: BaseTransport, handle_sigint: bool, contactId: str):
    
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        language=Language.EN_AU,
    )
    
    # stt = AzureSTTService(
    #         api_key=os.getenv("AZURE_SPEECH_API_KEY"),
    #         region=os.getenv("AZURE_SPEECH_REGION"),
    #         language=Language.EN_AU,
    #     )

    
    # tts = ElevenLabsTTSService(
    #     api_key=os.getenv("ELEVEN_API_KEY"),
    #     voice_id=os.getenv("ELEVEN_VOICE_ID"),
    #     sample_rate=8000,
    #     params=ElevenLabsTTSService.InputParams(
    #         language=Language.EN_AU
    #     )
    # )
    
    tts = AzureTTSService(
        api_key=os.getenv("AZURE_SPEECH_API_KEY"),
        region=os.getenv("AZURE_SPEECH_REGION"),
        voice="en-AU-NatashaNeural",
        params=AzureTTSService.InputParams(
            language=Language.EN_AU,
        )
    )
    
    llm = AzureLLMService(
        api_key=os.getenv("AZURE_CHATGPT_API_KEY"),
        service_tier="priority",
        endpoint=os.getenv("AZURE_CHATGPT_ENDPOINT"),
        model=os.getenv("AZURE_CHATGPT_MODEL"),  # Your deployment name
        params=AzureLLMService.InputParams(
            temperature=0.7,
            max_completion_tokens=150
        )
    )
    
    # llm.register_function("query_knowledge_base", query_knowledge_base)
    # llm.register_function("end_conversation", end_conversation)
    
    # tools = ToolsSchema(standard_tools=[query_knowledge_base_schema, end_conversation_schema])

    # messages = [
    #         {
    #             "role": "system",
    #             "content": SYSTEM_PROMPT,
    #         },
    #         {
    #             "role": "system",
    #             "content": "Start by greeting the user warmly and introducing yourself.",
    #         }
    #     ]
    
    context = LLMContext()
    
    context_aggregator = LLMContextAggregatorPair(context)
    
    transcript = TranscriptProcessor()
    
    transcript_handler = TranscriptHandler()
    
    user_idle = UserIdleProcessor(
        callback=handle_user_idle,  # Your callback function
        timeout=5.0,               # Seconds of inactivity before triggering
    )

    pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from client
            stt,  # Speech-To-Text
            user_idle,
            transcript.user(),  # User transcripts
            context_aggregator.user(),
            llm,  # LLM
            tts,  # Text-To-Speech
            transport.output(),  # Websocket output to client
            transcript.assistant(),  # Assistant transcripts
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            audio_out_sample_rate=8000,
            enable_metrics=True,
            enable_usage_metrics=True,
            observers=[UserBotLatencyLogObserver()],
        ),
    )
    
    flow_manager = await initialize_whipsmart_flow(task,llm, context_aggregator, transport, contact_id=contactId)
    
    @llm.event_handler("on_function_calls_started")
    async def on_function_calls_started(service, function_calls):
        ACKNOWLEDGEMENTS_CONTEXTUAL = [
            "Thank you for your question. I’ll check the details and provide you with the most accurate information.",
            "I appreciate your query. Let me review the information and get back to you shortly.",
            "That’s a great question. I’ll look into the knowledgebase and provide a detailed answer.",
            "Thanks for asking. I’m retrieving the relevant information for you now.",
            "I’ll check the knowledgebase and ensure you get the most accurate response.",
            "Thank you — I’ll take a moment to gather the correct details for you.",
            "I appreciate you asking that. Let me confirm the information before answering.",
            "Good question. I’ll review the relevant information and get back to you promptly.",
            "I’ll check the knowledgebase now to provide a precise and helpful answer.",
            "Thanks for your query. I’m retrieving the details to answer accurately."
        ]
        for function_call in function_calls:
            if function_call.function_name == "query_knowledge_base":
                message = random.choice(ACKNOWLEDGEMENTS_CONTEXTUAL)
                await service.push_frame(TTSSpeakFrame(text=message))

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        # Kick off the outbound conversation, waiting for the user to speak first
        await flow_manager.initialize(create_initial_greeting_node())
        logger.info("Starting outbound call conversation")
        
    # Register event handler for transcript updates
    @transcript.event_handler("on_transcript_update")
    async def on_transcript_update(processor, frame):
        await transcript_handler.on_transcript_update(processor, frame)
        
    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected - Processing lead data")
        
        try:
            outcome = flow_manager.state
            logger.info(f"Flow state: {outcome}")
            
            # 1️⃣ Add call notes
            add_call_notes(contactId, {
                "Manager Name": outcome.get("manager_name"),
                "Company Name": outcome.get("company_name"),
                "Current Provider": outcome.get("current_provider"),
                "Meeting Status": outcome.get("meeting_status"),
                "Meeting Day/Time": outcome.get("meeting_day_time"),
                "Email Address": outcome.get("email_address"),
                "Interested": outcome.get("interested_in_novated_leasing"),
                "Has Existing Provider": outcome.get("has_existing_provider")
            })
            
            # 2️⃣ Update lead status if interested
            if outcome.get("interested_in_novated_leasing"):
                update_contact_lead_status(contactId, HUBSPOT_LEAD_STATUS.OPEN_DEAL)
                create_deal_for_contact(contactId)
            else:
                update_contact_lead_status(contactId, HUBSPOT_LEAD_STATUS.CONNECTED)
        except Exception as e:
            logger.error(f"Error processing lead data on disconnect: {e}")
        finally:
            await task.cancel()

    runner = PipelineRunner(handle_sigint=handle_sigint)

    await runner.run(task)


async def bot(runner_args: RunnerArguments):
    try:
        print("Starting bot...")
        transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)
        logger.info(f"Auto-detected transport: {transport_type}")
        body_data = call_data.get("body", {})

        if not body_data:
            logger.error("No body data found in call_data")
            return

        contact_id = body_data.get("contactId")
        if not contact_id:
            logger.error("No contactId found in body_data")
            return

        logger.info(f"Body data: {body_data}")

        serializer = TwilioFrameSerializer(
            stream_sid=call_data["stream_id"],
            call_sid=call_data["call_id"],
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        )
        logger.info("Initialized TwilioFrameSerializer")

        transport = FastAPIWebsocketTransport(
            websocket=runner_args.websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                vad_analyzer=SileroVADAnalyzer(),
                serializer=serializer,
            ),
        )
        logger.info("Initialized FastAPIWebsocketTransport")

        handle_sigint = runner_args.handle_sigint

        logger.info(f"Starting run_bot with contactId: {contact_id}")
        await run_bot(transport, handle_sigint, contact_id)

        logger.info("run_bot completed successfully")

    except Exception as e:
        logger.error(f"Error in bot processing: {e}", exc_info=True)
        raise
