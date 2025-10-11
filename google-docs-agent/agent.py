import os
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from tools import create_google_doc


def create_docs_agent(credentials_dict: Dict):

    # Initialize the LLM
    llm = ChatOpenAI(
        model="gpt-4", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY")
    )

    # Define the available tools used
    tools = [create_google_doc]

    # Create the agent using langgraph
    agent = create_react_agent(
        llm=llm,
        tools=tools,
        state_modifier="""
        You are the Google Docs specialist agent for SafexpressOps.
        Your only responsibility is creating and managing Google Docs.

        When the supervisor agent routes a request to you:
        1. Use the create_google_doc tool to create documents
        2. Provide clear confirmation with the document URL
        3. Report back to the supervisor with the result

        Be concise and professional. Focus only on Google Docs tasks.
        If asked to do something outside of Google Docs, politely indicate that is outside your scope.
        """,
    )
    return agent
