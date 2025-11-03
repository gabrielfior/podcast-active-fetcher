import os
import re
from typing import Dict, Optional

import boto3
from dotenv import load_dotenv
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.models import BedrockModel
from strands.session.s3_session_manager import S3SessionManager
from strands.tools.mcp import MCPClient

from podcast_fetcher.keys import Config
from podcast_fetcher.tools import DatabaseTools

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


class PodcastAgentManager:
    """
    Singleton manager for podcast agents.
    Initializes expensive resources once and reuses them across multiple calls.
    """

    _instance: Optional["PodcastAgentManager"] = None

    def __new__(cls):
        """Ensure only one instance exists (singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize all heavy resources once."""
        print("=== Initializing PodcastAgentManager ===")

        # Get environment variables
        config = Config()
        mcp_supabase = config.SUPABASE_MCP_URL
        supabase_token = config.SUPABASE_ACCESS_TOKEN

        print(f"MCP_SUPABASE_URL: {mcp_supabase}")
        print(f"SUPABASE_ACCESS_TOKEN: {supabase_token}")

        # # Initialize MCP client
        # self.mcp_client = MCPClient(
        #     lambda: streamablehttp_client(
        #         url=mcp_supabase,
        #         headers={
        #             "Authorization": f"Bearer {supabase_token}"
        #         },
        #     )
        # )

        # Initialize boto3 session
        config = Config()

        self.boto_session = boto3.Session(
            aws_access_key_id=config.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=config.AWS_SECRET_ACCESS_KEY,
            region_name=config.AWS_REGION,
        )

        # Initialize Bedrock model
        self.bedrock_model = BedrockModel(
            model_id="us.amazon.nova-pro-v1:0",
            temperature=0,
        )

        # Get tools from MCP server (do this once)
        # with self.mcp_client:
        # self.tools = self.mcp_client.list_tools_sync()
        # print(f"tools: {[t.__dict__ for t in self.tools]}")
        db_tools = DatabaseTools()
        self.tools = [db_tools.query_episodes_from_user, db_tools.query_episode_by_id]

        # Cache agents per user_id
        self.agents_cache: Dict[str, Agent] = {}

        print("=== PodcastAgentManager initialized successfully ===")

    def get_agent(self, user_id: str, force_new: bool = False) -> Agent:
        """
        Get or create an agent for a specific user.
        Agents are cached per user_id to maintain session state.

        Args:
            user_id: The user ID (telegram username)
            force_new: If True, create a new agent even if one exists

        Returns:
            An Agent instance for this user
        """
        # Return cached agent if exists and not forcing new
        if user_id in self.agents_cache and not force_new:
            return self.agents_cache[user_id]

        # Create new agent for this user
        session_manager = S3SessionManager(
            session_id=user_id,
            bucket="telegram-bot-agent-sessions",
            boto_session=self.boto_session,
        )

        system_prompt = """You are a podcast assistant. When users ask about their episodes, use query_episodes_from_user tool. When users ask for episode transcripts or detailed content, use query_episode_by_id tool. Username is provided in context."""

        self.conversation_manager = SummarizingConversationManager(
            summary_ratio=0.3,
            preserve_recent_messages=3,
        )

        agent = Agent(
            tools=self.tools,
            model=self.bedrock_model,
            session_manager=session_manager,
            system_prompt=system_prompt,
            conversation_manager=self.conversation_manager,
        )

        # Cache the agent
        self.agents_cache[user_id] = agent
        print(f"Created new agent for user: {user_id}")

        return agent

    def get_response(self, user_id: str, message: str) -> str:
        """
        Get a response from the agent for a given user message.

        Args:
            user_id: The user ID (telegram username)
            message: The message to send to the agent

        Returns:
            The agent's response as a string
        """
        try:
            # Get the agent for this user
            agent = self.get_agent(user_id)

            # Add username context to the message so the agent knows which user to query
            contextualized_message = f"[User: {user_id}] {message}"

            response = agent(contextualized_message)

            # Clean the response for Telegram
            cleaned_response = clean_response_for_telegram(str(response))
            return cleaned_response

        except Exception as e:
            print(f"ERROR in get_response: {type(e).__name__}: {str(e)}")

            # If it's a token limit error, clear the session and try again
            if "Input Tokens Exceeded" in str(e) or "maximum length" in str(e).lower():
                print(f"Token limit exceeded for user {user_id}, clearing session...")
                self.clear_user_cache(user_id)

                # Try again with a fresh agent
                try:
                    agent = self.get_agent(user_id, force_new=True)
                    response = agent(contextualized_message)
                    cleaned_response = clean_response_for_telegram(str(response))
                    return cleaned_response
                except Exception as retry_e:
                    print(f"Retry also failed: {retry_e}")
                    return f"Sorry, I encountered an error and couldn't process your request. Please try again."

            import traceback

            traceback.print_exc()
            return f"Sorry, I encountered an error: {str(e)}"

    def clear_user_cache(self, user_id: str):
        """Clear cached agent for a specific user."""
        if user_id in self.agents_cache:
            del self.agents_cache[user_id]
            print(f"Cleared agent cache for user: {user_id}")

    def clear_all_sessions(self):
        """Clear all cached agents to free up memory and reset sessions."""
        self.agents_cache.clear()
        print("Cleared all agent sessions")


def get_agent_response(user_id: str, message: str) -> str:
    """
    Get a response from the agent for a given user message.
    This is a convenience function that uses the singleton agent manager.

    Args:
        user_id: The user ID (telegram username)
        message: The message to send to the agent

    Returns:
        The agent's response as a string
    """
    return PodcastAgentManager().get_response(user_id, message)


def main(user_id: str):
    """Main function for testing the agent."""
    response = get_agent_response(
        user_id, "Did you already answer any questions about podcast episodes?"
    )
    print(response)


if __name__ == "__main__":
    main(user_id="wiskkkk")
