import os

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import AzureChatOpenAI


def create_model(name: str, max_completion_tokens: int) -> BaseChatModel:
    if not os.environ.get("DKS_AZURE_OPENAI_API_KEY"):
        raise ValueError('Missing DKS_AZURE_OPENAI_API_KEY')

    llm = AzureChatOpenAI(
        name=name,
        azure_endpoint=os.environ["DKS_AZURE_OPENAI_ENDPOINT"]
        ,azure_deployment=os.environ["DKS_AZURE_OPENAI_DEPLOYMENT_NAME"]
        ,openai_api_version=os.environ["DKS_AZURE_OPENAI_API_VERSION"]
        ,api_key=os.environ['DKS_AZURE_OPENAI_API_KEY']
        ,verbose=True
        , temperature=0.0
        , max_retries=1
        , max_completion_tokens= max_completion_tokens
    )
    return llm


def create_react_agent(llm: BaseChatModel, tools: list, system_prompt: str = ""):
    if not tools or not isinstance(tools, list):
        raise ValueError("Tools must be a non-empty list.")
    
    if not system_prompt or not isinstance(system_prompt, str):
        raise ValueError("System prompt must be a non-empty string.")   

    agent = create_agent(
        model=llm,
        tools=tools,
        system_prompt=system_prompt,
    )
    return agent
