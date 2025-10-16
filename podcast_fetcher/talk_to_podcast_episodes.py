import boto3
from strands import Agent
from mcp.client.sse import sse_client
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from dotenv import load_dotenv
import os
from strands.session.s3_session_manager import S3SessionManager
load_dotenv()


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
        mcp_supabase = "https://mcp.supabase.com/mcp?project_ref=qeebhwfzcqvoytqskiiw&read_only=true&features=database"
        
        sse_mcp_client = MCPClient(
            lambda: streamablehttp_client(
                url=mcp_supabase,
                headers={"Authorization": f"Bearer {os.getenv('SUPABASE_ACCESS_TOKEN')}"},
            )
        )

        # Create an agent with MCP tools
        with sse_mcp_client:
            # Get the tools from the MCP server
            tools = sse_mcp_client.list_tools_sync()

            boto_session = boto3.Session(
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
                region_name=os.getenv("AWS_REGION"),
            )
            
            # Create an agent with these tools
            bedrock_model = BedrockModel(
                model_id="us.amazon.nova-lite-v1:0",
                temperature=0.3,
                top_p=0.8,
            )
            session_manager = S3SessionManager(
                session_id=user_id,
                bucket="telegram-bot-agent-sessions",
                boto_session=boto_session,
            )

            agent = Agent(tools=tools, model=bedrock_model, session_manager=session_manager)

            # Get response from agent
            response = agent(message)
            return str(response)
            
    except Exception as e:
        return f"Sorry, I encountered an error: {str(e)}"


def main(user_id: str):
    """Main function for testing the agent."""
    response = get_agent_response(user_id, "Did you already answer any questions about podcast episodes?")
    print(response)


if __name__ == "__main__":
    main(user_id="wiskkkk")
