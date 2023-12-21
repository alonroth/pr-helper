import base64
import textwrap

from fastapi import FastAPI, Request
from github import Github, GithubException
import openai
import os
import dotenv

app = FastAPI()

# GitHub and OpenAI credentials
openai_api_key = os.getenv('OPENAI_API_KEY')
encoded_pem = os.environ.get('GITHUB_APP_PRIVATE_KEY')
decoded_pem = base64.b64decode(encoded_pem)


# Initialize clients
github = Github(base_url="https://api.github.com/app", login_or_token=decoded_pem)
openai.api_key = openai_api_key


@app.post("/webhook")
async def handle_webhook(request: Request):
    payload = await request.json()
    action = payload.get('action', '')

    # Check if it's a pull request that's been opened or edited
    if payload.get('pull_request') and action in ['opened', 'edited']:
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
    # Split the diff into smaller chunks
    chunks = textwrap.wrap(diff, 1000)  # Adjust the chunk size as needed

    # Generate summaries for each chunk
    partial_summaries = []
    for chunk in chunks:
        response = openai.Completion.create(
            engine="gpt-4-model-name",  # Replace with actual GPT-4 model name
            prompt=f"Summarize the following PR diff chunk:\n\n{chunk}",
            max_tokens=150
        )
        partial_summaries.append(response.choices[0].text.strip())

    # Combine partial summaries and generate a final summary
    combined_partial_summaries = ' '.join(partial_summaries)
    final_summary_response = openai.Completion.create(
        engine="gpt-4",  # Replace with actual GPT-4 model name
        prompt=f"Generate a comprehensive summary based on these partial summaries:\n\n{combined_partial_summaries}",
        max_tokens=150
    )

    return final_summary_response.choices[0].text.strip()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
