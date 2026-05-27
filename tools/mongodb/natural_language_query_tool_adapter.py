import json
import os

from pydantic import BaseModel, Field, create_model, create_model
from typing import Any, Optional
from mcp.server.fastmcp import Context
from langchain_mongodb.agent_toolkit import (
    MONGODB_AGENT_SYSTEM_PROMPT,
    MongoDBDatabase,
    MongoDBDatabaseToolkit
)
from langchain_core.tools import BaseTool
from langchain_core.language_models.chat_models import BaseChatModel

from core.agent import create_react_agent
from core.auth_middleware import audit_info_decorator
from core.log_exceptions_middleware import log_exceptions_decorator

class MongoDBNaturalLanguageQueryToolAdapterSchema(BaseModel):
    query: str = Field(
        ...,
        description="Users query in natural language. The query should be related to document search in MongoDB databases.",
    )
    auditcontext: Optional[dict[str, Any]] = Field(
        default_factory=dict, description="auditcontext of the current request"
    )


class MongoDBNaturalLanguageQueryToolAdapter(BaseTool):
    """
    MongoDBNaturalLanguageAgent is an agent adapter tool designed to handle natural language queries related to document search in MongoDB Databases.
        - It receives a natural language query and an audit context.
    """

    name: str = "MongoDBNaturalLanguageQueryAgent"
    description: str = MONGODB_AGENT_SYSTEM_PROMPT.format(top_k=5)
    args_schema = MongoDBNaturalLanguageQueryToolAdapterSchema


    def __init__(self):
        self.db_wrapper = MongoDBDatabase.from_connection_string(os.getenv("MONGODB_URI"), os.getenv("MONGODB_NATURAL_LANGUAGE_DATABASE_NAME"))
        self.llm: BaseChatModel = create_model(name="MongoDBNaturalLanguageQueryAgent", max_completion_tokens=1024)
        self.agent = create_react_agent(
            llm=self.llm,
            tools=MongoDBDatabaseToolkit(db = self.db_wrapper, llm = self.llm).get_tools(),
            system_prompt=MONGODB_AGENT_SYSTEM_PROMPT.format(top_k=5)
            )
        self.toolkit: MongoDBDatabaseToolkit = MongoDBDatabaseToolkit(db = self.db_wrapper, llm = self.llm)
        self.messages = []

    @audit_info_decorator()
    @log_exceptions_decorator(logger_name="mongodb_natural_language_tool_logger")
    async def _run(
        self,
        query: str,
        ctx: Context,
        auditcontext: Optional[dict[str, Any]] = None,
        tool_logger: Optional[Any] = None,
    ) -> str:

        if not query or not isinstance(query, str):
            raise ValueError("Query must be a non-empty string.")
    
        result = self.execute_natural_language_query(query, ctx.session_id, auditcontext or {})

        return result if isinstance(result, str) else json.dumps(result)


    def execute_natural_language_query(self, user_query: str, session_id: str, audit_context: dict):
        """
        Converts user natural language query into structured MongoDB queries using a React agent and returns the results.
        """
        try:
            # Log the user query
            self.logger.debug(f"Received natural language query: {user_query}")

            # Process the natural language query and generate a response
            # Start the agent with the agent.stream() method
            events = self.agent.stream(
                {'messages': [('user', user_query)]},
                stream_mode='values'
            )
            # Add output (events) from the agent to the self.messages list
            for event in events:
                self.messages.extend(event['messages'])


            return self.messages[-1].content if len(self.messages) > 0 else "No response generated."
        
        except Exception as e:
            self.logger.error(f"Error processing natural language query {user_query} \n\n exception: {e}")
            raise

def mongodb_document_search_agent_adapter() -> MongoDBNaturalLanguageQueryToolAdapter:
    """
    Returns MongoDB Natural Language Query agent adapter tool instance.
    """
    mongodburl = os.getenv("MONGODB_URI")
    if mongodburl is None:
        raise ValueError(
            "Environment variable 'MONGODB_URI' is not set."
        )
    mongodb_database_name = os.getenv("MONGODB_NATURAL_LANGUAGE_DATABASE_NAME", "")
    if not mongodb_database_name:
        raise ValueError(
            "Environment variable 'MONGODB_NATURAL_LANGUAGE_DATABASE_NAME' is not set or empty."
        )
    mongodb_document_search_agent_adapter = MongoDBNaturalLanguageQueryToolAdapter()

    return mongodb_document_search_agent_adapter
