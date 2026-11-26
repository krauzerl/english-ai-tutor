import sys

import requests

MODEL = "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/chat"


def chat():
    messages = [
        {
            "role": "system",
            "content": (
                "You are a friendly English tutor. "
                "Speak mainly in English. Correct the user's most important mistakes "
                "briefly and continue the conversation."
            ),
        }
    ]

    while True:
        user_message = input("You: ")

        if user_message.strip().lower() in {"exit", "quit", "/exit", "/quit", "/bye"}:
            print("Tutor: Goodbye!")
            break

        messages.append({"role": "user", "content": user_message})

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False,
            },
            timeout=120,
        )

        response.raise_for_status()
        assistant_message = response.json()["message"]["content"]

        messages.append({"role": "assistant", "content": assistant_message})

        print(f"\nTutor: {assistant_message}\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["profile"]:
        from tutor.cli import main as profile_main

        sys.exit(profile_main(sys.argv[2:]))
    if sys.argv[1:2] == ["content"]:
        from tutor.cli import content_main

        sys.exit(content_main(sys.argv[2:]))
    if "--gui" in sys.argv[1:]:
        from tutor.gui.server import main as gui_main

        sys.exit(gui_main(sys.argv[1:]))
    if "--voice" in sys.argv[1:]:
        from tutor.voice.cli import run

        sys.exit(run(sys.argv[1:]))
    chat()  # także `--cli`: GUI jeszcze nie istnieje
