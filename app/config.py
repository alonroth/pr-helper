import base64
import os
import dotenv

dotenv.load_dotenv()
GITHUB_APP_ID = os.getenv('GITHUB_APP_ID')
GITHUB_APP_PRIVATE_KEY = base64.b64decode(os.environ.get('GITHUB_APP_PRIVATE_KEY')).decode('utf-8')
GITHUB_APP_WEBHOOK_SECRET = os.environ.get('GITHUB_APP_WEBHOOK_SECRET')

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')