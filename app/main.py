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
github = Github(github_token)
openai.api_key = openai_api_key


@app.post("/webhook")
async def handle_webhook(request: Request):
    payload = await request.json()

    # Check if it's a pull request opened event
    if payload['action'] == 'opened':
        repo_name = payload['repository']['full_name']
        pr_number = payload['pull_request']['number']

        try:
            repo = github.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            body = pr.body

            # Check for the token in the PR description
            if ':write_ai_description' in body:

                diff = await get_pr_diff(repo_name, pr_number)
                if diff:
                    summary = await generate_summary(diff)
                    new_body = body.replace(':write_ai_description',
                                            'Summary:\n\n' + summary)
                    pr.edit(body=new_body)
                    return {"message": "PR description updated successfully."}
        except GithubException as e:
            return {"error": str(e)}

    return {"message": "Webhook received, but no action taken."}


async def get_pr_diff(repo_name: str, pr_number: int) -> str:
    try:
        repo = github.get_repo(repo_name)
        pr = repo.get_pull(pr_number)
        return pr.get_diff()
    except GithubException as e:
        print(f"Error getting PR diff: {str(e)}")
        return ""


async def generate_summary(diff: str) -> str:
    response = openai.Completion.create(
        engine="text-davinci-003",  # Use the latest available engine
        prompt=f"Summarize the following PR diff:\n\n{diff}",
        max_tokens=150  # Adjust as needed
    )
    return response.choices[0].text.strip()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
