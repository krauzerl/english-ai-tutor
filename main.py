import requests

MODEL = "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M"
OLLAMA_URL = "http://localhost:11434/api/chat"

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