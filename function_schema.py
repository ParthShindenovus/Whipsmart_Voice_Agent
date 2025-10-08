from pipecat.adapters.schemas.function_schema import FunctionSchema


query_knowledge_base_schema = FunctionSchema(
    name="query_knowledge_base",
    description="Query the knowledge base for the answer to the question.",
    properties={
        "question": {
            "type": "string",
            "description": "The question to query the knowledge base with.",
        },
    },
    required=["question"],
)

end_conversation_schema = FunctionSchema(
    name="end_conversation",
    description="Ends the current conversation.",
    properties={},
    required=[],
)