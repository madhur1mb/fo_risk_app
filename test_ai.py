from openai import OpenAI

client = OpenAI(
  api_key="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"
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
