import os
from openai import OpenAI

client = OpenAI(
  api_key= os.environ.get("OPENAI_API_KEY")
)

# response = client.responses.create(
#   model="gpt-5-nano",
#   input="write a haiku about ai",
#   store=True,
# )
prompt = f"""
Portfolio Greeks:
Net Delta: 100
Net Gamma: 100
Net Theta: 100
Net Vega: 100"""
completion = client.responses.create(
            model="gpt-5-nano",
            input=f"""
             You are a senior derivatives risk manager reviewing an Indian F&O options portfolio.

            Provide a concise professional risk summary in 4 sections:

            1. Portfolio Overview
            2. Key Risk Flags (2–3 most important)
            3. Stress Sensitivity
            4. Trader's Edge Assessment

            Tone: direct, risk-desk briefing style.
            Max 100 words.

            {prompt}""",
            store=False,
)



print(completion);
