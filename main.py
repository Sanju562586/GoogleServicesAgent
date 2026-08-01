"""
Gmail + Groq AI Assistant via MCP
----------------------------------
Connects to Gmail using OAuth2, exposes tools via MCP,
and uses Groq LLM to answer email-related queries.
"""

import asyncio
# pyrefly: ignore [missing-import]
from src.agent import GmailGroqAgent


async def main():
    agent = GmailGroqAgent()
    await agent.setup()

    print("\n🤖 Gmail AI Assistant (powered by Groq)")
    print("=" * 45)
    print("Commands: 'quit' to exit\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break

            response = await agent.chat(user_input)
            print(f"\nAssistant: {response}\n")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
