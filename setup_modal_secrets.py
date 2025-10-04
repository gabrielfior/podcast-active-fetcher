#!/usr/bin/env python3
"""
Helper script to set up Modal secrets for the Telegram bot.
This script guides you through creating the necessary secrets.
"""

import subprocess
import sys
import os

def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n🔄 {description}...")
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"Error: {e.stderr}")
        return False

def check_modal_auth():
    """Check if user is authenticated with Modal."""
    return run_command("modal token current", "Checking Modal authentication")

def create_secret():
    """Create the telegram-bot-secrets secret."""
    print("\n🔐 Creating Modal secret 'telegram-bot-secrets'...")
    print("You will be prompted to enter the following values:")
    print()
    print("Required:")
    print("- TELEGRAM_BOT_TOKEN: Your Telegram bot token (from @BotFather)")
    print("- TADDY_API_KEY: Your Taddy API key")
    print("- TADDY_USER_ID: Your Taddy user ID")
    print()
    print("Optional:")
    print("- SQLALCHEMY_DATABASE_URI: Database connection string (leave empty for SQLite)")
    print()
    
    response = input("Press Enter to continue with secret creation...")
    
    # Create the secret
    cmd = "modal secret create telegram-bot-secrets"
    return run_command(cmd, "Creating telegram-bot-secrets")

def verify_secret():
    """Verify the secret was created successfully."""
    print("\n🔍 Verifying secret creation...")
    return run_command("modal secret list", "Listing secrets")

def main():
    """Main setup function."""
    print("🔐 Modal Secrets Setup for Telegram Bot")
    print("=" * 50)
    
    # Check authentication
    if not check_modal_auth():
        print("\n❌ Please authenticate with Modal first:")
        print("modal token new")
        return
    
    # Create secret
    if not create_secret():
        print("\n❌ Failed to create secret. Please try again.")
        return
    
    # Verify secret
    if not verify_secret():
        print("\n❌ Failed to verify secret. Please check manually.")
        return
    
    print("\n✅ Secret setup completed successfully!")
    print("\nNext steps:")
    print("1. Deploy the bot: modal deploy bot/modal_bot.py")
    print("2. Run the bot: modal run bot/modal_bot.py::run_telegram_bot_with_volume")
    print("\nOr use the deployment script: python deploy_bot.py")

if __name__ == "__main__":
    main()
