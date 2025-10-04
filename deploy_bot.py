#!/usr/bin/env python3
"""
Deployment script for the Telegram bot on Modal.
This script helps set up and deploy the bot to Modal.
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description):
    """Run a command and handle errors."""
    print(f"\n🔄 {description}...")
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"Error: {e.stderr}")
        return False

def check_modal_installed():
    """Check if Modal is installed."""
    try:
        import modal
        print("✅ Modal is installed")
        return True
    except ImportError:
        print("❌ Modal is not installed")
        print("Install it with: pip install modal")
        return False

def setup_secrets():
    """Guide user through setting up Modal secrets."""
    print("\n🔐 Setting up Modal secrets...")
    print("You need to create a secret named 'telegram-bot-secrets' in Modal with the following variables:")
    print()
    print("Required secrets:")
    print("- TELEGRAM_BOT_TOKEN: Your Telegram bot token")
    print("- TADDY_API_KEY: Your Taddy API key")
    print("- TADDY_USER_ID: Your Taddy user ID")
    print()
    print("Optional secrets:")
    print("- SQLALCHEMY_DATABASE_URI: Database connection string (defaults to SQLite)")
    print()
    print("To create the secret, run:")
    print("modal secret create telegram-bot-secrets")
    print("Then add each variable when prompted.")
    print()
    
    response = input("Have you set up the secrets? (y/n): ").lower().strip()
    return response == 'y'

def deploy_bot():
    """Deploy the bot to Modal."""
    print("\n🚀 Deploying Telegram bot to Modal...")
    
    # Change to the project directory
    project_dir = Path(__file__).parent
    os.chdir(project_dir)
    
    # Deploy the bot
    cmd = "modal deploy bot/modal_bot.py"
    return run_command(cmd, "Deploying bot to Modal")

def run_bot():
    """Run the bot on Modal."""
    print("\n🤖 Starting the Telegram bot on Modal...")
    
    cmd = "modal run bot/modal_bot.py::run_telegram_bot_with_volume"
    return run_command(cmd, "Starting bot on Modal")

def main():
    """Main deployment function."""
    print("🤖 Telegram Podcast Bot - Modal Deployment")
    print("=" * 50)
    
    # Check if Modal is installed
    if not check_modal_installed():
        print("\nPlease install Modal first:")
        print("pip install modal")
        return
    
    # Check if user is logged in to Modal
    if not run_command("modal token current", "Checking Modal authentication"):
        print("\nPlease log in to Modal first:")
        print("modal token new")
        return
    
    # Guide through secret setup
    if not setup_secrets():
        print("\nPlease set up the secrets first, then run this script again.")
        return
    
    # Deploy the bot
    if not deploy_bot():
        print("\nDeployment failed. Please check the errors above.")
        return
    
    print("\n✅ Bot deployed successfully!")
    print("\nTo run the bot, use:")
    print("modal run bot/modal_bot.py::run_telegram_bot_with_volume")
    print("\nOr use the run_bot() function in this script.")
    
    # Ask if user wants to run the bot now
    response = input("\nDo you want to start the bot now? (y/n): ").lower().strip()
    if response == 'y':
        run_bot()

if __name__ == "__main__":
    main()
