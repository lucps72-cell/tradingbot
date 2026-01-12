import os
from dotenv import load_dotenv
load_dotenv()

#openai_api_key = os.getenv("OPENAI_API_KEY")
api_key = os.getenv("BYBIT_API_KEY")
secret = os.getenv("BYBIT_API_SECRET")

print(api_key)
print(secret)