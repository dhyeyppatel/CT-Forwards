"""
generate_session.py — Run this LOCALLY once to generate your SESSION_STRING.

Usage:
    1. Fill in API_ID and API_HASH in your .env file (or set as env vars)
    2. Run:  python generate_session.py
    3. Enter your phone number and the OTP Telegram sends you
    4. Copy the printed SESSION_STRING
    5. Paste it as the SESSION_STRING environment variable in Koyeb

⚠️  Keep SESSION_STRING secret — it's equivalent to your account password.
"""
import asyncio
import os
import sys

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from dotenv import load_dotenv
except ImportError:
    print("❌ Missing dependencies. Run first:\n  pip install telethon python-dotenv")
    sys.exit(1)

load_dotenv()


async def main():
    api_id_raw = os.getenv("API_ID", "").strip()
    api_hash = os.getenv("API_HASH", "").strip()

    if not api_id_raw or not api_hash:
        print("❌ Set API_ID and API_HASH in your .env file or environment first.")
        print("   Get them from: https://my.telegram.org")
        sys.exit(1)

    try:
        api_id = int(api_id_raw)
    except ValueError:
        print("❌ API_ID must be an integer.")
        sys.exit(1)

    print("=" * 60)
    print("  MN Auto Forward Bot — Session Generator")
    print("=" * 60)
    print(f"  API_ID   : {api_id}")
    print(f"  API_HASH : {api_hash[:8]}{'*' * (len(api_hash) - 8)}")
    print("=" * 60)
    print("\nYou will be prompted for your phone number and OTP.\n")

    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        await client.start()
        session_str = client.session.save()

        me = await client.get_me()
        print(f"\n✅ Logged in as: {me.first_name} (@{me.username or 'N/A'})")

    print("\n" + "=" * 60)
    print("  SESSION_STRING (set this in Koyeb env vars)")
    print("=" * 60)
    print(session_str)
    print("=" * 60)
    print("\n⚠️  This string grants full access to your account.")
    print("   Never share it. Store it only in Koyeb environment variables.\n")


if __name__ == "__main__":
    asyncio.run(main())
