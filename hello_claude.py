import anthropic

client = anthropic.Anthropic()

topic = input("What topic do you want to search for?")

message = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": f"I'm looking for government solicitations related to: {topic}. What kinds of agencies and programs should I be targeting?"}
    ]
)

print("\n" + message.content[0].text)