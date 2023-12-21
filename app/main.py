from fastapi import FastAPI, Request
from github import Github, GithubException
import openai
import os
import dotenv

app = FastAPI()

# GitHub and OpenAI credentials
github_token = os.getenv('GITHUB_TOKEN')
openai_api_key = os.getenv('OPENAI_API_KEY')

# Initialize clients
g = Github(github_token)
openai.api_key = openai_api_key

@app.post("/webhook")
async def handle_webhook(request: Request):
    payload = await request.json()

    # ... (existing code for handling the PR description update)

    if 'pull_request' in payload:
        repo_name = payload['repository']['full_name']
        pr_number = payload['pull_request']['number']

        diff = await get_pr_diff(repo_name, pr_number)
        if diff:
            summary = await generate_summary(diff)
            await post_summary_to_pr(repo_name, pr_number, summary)

    return {"message": "Webhook received, but no action taken."}

async def get_pr_diff(repo_name: str, pr_number: int) -> str:
    # ... (existing code for getting PR diff)

async def generate_summary(diff: str) -> str:
    response = openai.Completion.create(
        engine="text-davinci-003",  # Use the latest available engine
        prompt=f"Summarize the following PR diff:\n\n{diff}",
        max_tokens=150  # Adjust as needed
    )
    return response.choices[0].text.strip()

async def post_summary_to_pr(repo_name: str, pr_number: int, summary: str):
    try:
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        pr.create_issue_comment(f"### PR Summary:\n\n{summary}")
    except GithubException as e:
        print(f"Error posting summary to PR: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
