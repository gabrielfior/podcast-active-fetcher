import boto3
import re
from strands import Agent
from mcp.client.sse import sse_client
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from dotenv import load_dotenv
import os
from strands.session.s3_session_manager import S3SessionManager

load_dotenv()


def clean_response_for_telegram(response: str) -> str:
    """
    Clean the agent response to remove HTML-like tags that Telegram can't parse.

    Args:
        response: The raw response from the agent

    Returns:
        Cleaned response safe for Telegram
    """
    # Remove thinking tags and other HTML-like tags
    cleaned = re.sub(r"<thinking>.*?</thinking>", "", response, flags=re.DOTALL)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)  # Remove any remaining HTML-like tags

    # Remove extra whitespace and newlines
    cleaned = re.sub(
        r"\n\s*\n", "\n\n", cleaned
    )  # Replace multiple newlines with double newlines
    cleaned = cleaned.strip()

    # If the response is empty after cleaning, return a default message
    if not cleaned:
        return "I received your message but couldn't generate a proper response. Please try again."

    return cleaned


def get_agent_response(user_id: str, message: str) -> str:
    """
    Get a response from the agent for a given user message.

    Args:
        user_id: The user ID (telegram username)
        message: The message to send to the agent

    Returns:
        The agent's response as a string
    """
    try:
        # ToDo - MCP supabase
        mcp_supabase = os.getenv('MCP_SUPABASE_URL')

        sse_mcp_client = MCPClient(
            lambda: streamablehttp_client(
                url=mcp_supabase,
                headers={
                    "Authorization": f"Bearer {os.getenv('SUPABASE_ACCESS_TOKEN')}"
                },
            )
        )

        # Create an agent with MCP tools
        with sse_mcp_client:
            # Get the tools from the MCP server
            tools = sse_mcp_client.list_tools_sync()
            print(f"tools: {[t.__dict__ for t in tools]}")

            boto_session = boto3.Session(
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
                region_name=os.getenv("AWS_REGION"),
            )

            # Create an agent with these tools
            bedrock_model = BedrockModel(
                model_id="us.amazon.nova-pro-v1:0",
                #model_id="us.amazon.claude-3-5-sonnet-20241022-v2:0",
                temperature=0.3,
                top_p=0.8,
            )

            session_manager = S3SessionManager(
                session_id=user_id,
                bucket="telegram-bot-agent-sessions",
                boto_session=boto_session,
            )

            agent = Agent(tools=tools, model=bedrock_model, 
                          session_manager=session_manager
                          )

            # Get response from agent
            response = agent(message)

        # Clean the response for Telegram
        cleaned_response = clean_response_for_telegram(str(response))
        return cleaned_response

    except Exception as e:
        print({e})
        return f"Sorry, I encountered an error: {str(e)}"


def main(user_id: str):
    """Main function for testing the agent."""
    response = get_agent_response(
        user_id, "Did you already answer any questions about podcast episodes?"
    )
    print(response)


if __name__ == "__main__":
    main(user_id="wiskkkk")
