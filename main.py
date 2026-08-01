import asyncio
from src.gmail_auth import ensure_authenticated
# pyrefly: ignore [missing-import]
from src.agent import GmailGroqAgent


async def main():
    print("🔒 Verifying Google authentication...")
    try:
        ensure_authenticated()
        print("✅ Authentication verified.")
    except Exception as e:
        print(f"\n❌ Authentication Error:\n{e}\n")
        return

    agent = GmailGroqAgent()
    await agent.setup()

    print("\n🤖 Gmail AI Assistant (powered by Groq)")
    print("=" * 45)
    print("Commands: 'quit' to exit\n")

    # FIX #3: Guarantee agent.close() is always called on exit so the MCP
    # subprocess is cleanly terminated and the anyio cancel scope is properly
    # exited — preventing the "RuntimeError: Attempted to exit cancel scope in
    # a different task" crash on shutdown.
    try:
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
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
