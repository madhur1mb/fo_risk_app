import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# Access the API key using os.getenv() or os.environ[]
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

response = client.responses.create(
    model="gpt-5-nano",
    input="Write a short bedtime story about a unicorn in 100 words"
)

print(response.output_text)