from loguru import logger
import json
import time
from pipecat.services.llm_service import FunctionCallParams
from pipecat.frames.frames import EndTaskFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection
from query_knowledebase import RAG_PROMPT, RAG_MODEL, client

async def end_conversation(params: FunctionCallParams):
    await params.llm.push_frame(TTSSpeakFrame("Have a nice day!"))

    # Signal that the task should end after processing this frame
    await params.llm.push_frame(EndTaskFrame(), FrameDirection.UPSTREAM)


async def query_knowledge_base(params: FunctionCallParams):
    """Query the knowledge base for the answer to the question."""
    logger.info(f"Querying knowledge base for question: {params.arguments['question']}")

    # for our case, the first two messages are the instructions and the user message
    # so we remove them.
    conversation_turns = params.context.get_messages()[2:]

    def _is_tool_call(turn):
        if turn.get("role", None) == "tool":
            return True
        if turn.get("tool_calls", None):
            return True
        return False

    # filter out tool calls
    messages = [turn for turn in conversation_turns if not _is_tool_call(turn)]
    # use the last 3 turns as the conversation history/context
    messages = messages[-3:]
    messages_json = json.dumps(messages, ensure_ascii=False, indent=2)

    logger.info(f"Conversation turns: {messages_json}")

    start = time.perf_counter()
    full_prompt = f"System: {RAG_PROMPT}\n\nConversation History: {messages_json}"

    response = await client.aio.models.generate_content(
        model=RAG_MODEL,
        contents=[full_prompt],
        config={
            "temperature": 0.1,
            "max_output_tokens": 64,
        },
    )
    end = time.perf_counter()
    logger.info(f"Time taken: {end - start:.2f} seconds")
    logger.info(response.text)
    await params.result_callback(response.text)