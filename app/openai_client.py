from openai import AsyncOpenAI

from app.config import OPENAI_API_KEY

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)