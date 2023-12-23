import asyncio
import base64
import hashlib
import hmac
import textwrap
from itertools import islice

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from github import Github, GithubException, Auth, PullRequest, Repository
from openai import AsyncOpenAI

import os
import dotenv

from app.logger import logger

dotenv.load_dotenv()

app = FastAPI()

# GitHub and OpenAI credentials
openai_api_key = os.getenv('OPENAI_API_KEY')
github_private_key = base64.b64decode(os.environ.get('GITHUB_APP_PRIVATE_KEY')).decode('utf-8')
GITHUB_APP_SECRET = os.environ.get('GITHUB_APP_SECRET')

# Initialize clients
client = AsyncOpenAI(api_key=openai_api_key)
auth = Auth.AppAuth(729209, github_private_key).get_installation_auth(45373297) # todo: use env vars
g = Github(auth=auth)

MAGIC_PHRASE = "ai:summary"
IN_PROGRESS_MESSAGE = "Generating summary..."


def verify_signature(x_hub_signature: str, data: bytes) -> bool:
    # Use HMAC to compute the hash
    hmac_gen = hmac.new(GITHUB_APP_SECRET.encode(), data, hashlib.sha1)
    expected_signature = 'sha1=' + hmac_gen.hexdigest()
    return hmac.compare_digest(expected_signature, x_hub_signature)


@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    x_hub_signature = request.headers.get('X-Hub-Signature')
    payload = await request.json()
    body = await request.body()

    # Verify the signature
    if not x_hub_signature or not verify_signature(x_hub_signature, body):
        raise HTTPException(status_code=400, detail="Invalid signature")

    action = payload.get('action', '')

    # Check if it's a pull request that's been opened or edited
    if payload.get('pull_request') and action in ['opened', 'edited']:
        repo_name = payload['repository']['full_name']
        pr_number = payload['pull_request']['number']

        try:
            repo = g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)
            issue = repo.get_issue(number=pr_number)

            # Check for the token in the PR description
            if MAGIC_PHRASE in pr.body:
                pr.body.replace(MAGIC_PHRASE, IN_PROGRESS_MESSAGE)
                reaction = issue.create_reaction('eyes')
                eyes_reaction_id = reaction.id
                background_tasks.add_task(write_summary, repo, pr, eyes_reaction_id)
                return "Sent to background task queue."
        except GithubException as e:
            return {"error": str(e)}

    return {"message": "Webhook received, but no action taken."}


async def write_summary(repo: Repository, pr: PullRequest, eyes_reaction_id: int):
    files_diff = await get_pr_files_diff(repo, pr)
    if files_diff:
        summary = await generate_summary(pr, files_diff)
        new_body = pr.body.replace(MAGIC_PHRASE,
                                '🤖 AI Generated Summary 🤖:\n\n' + summary)
        pr.edit(body=new_body)
        issue = repo.get_issue(number=pr.number)
        issue.delete_reaction(eyes_reaction_id)


async def get_pr_files_diff(repo: Repository, pr: PullRequest) -> list:
    head_sha = pr.head.sha
    files = list(islice(pr.get_files(), 51))
    files_diff = []
    for file in files:
        path = file.filename
        patch = file.patch
        contents = repo.get_contents(path, ref=head_sha)
        content = contents.decoded_content.decode()
        files_diff.append(f"File: {path}\n\n{patch}\n\n{content}\n\n\n\n")

    return files_diff


async def process_chunk(pr: PullRequest, chunk: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "user",
             "content": f"""Summarize this PR file diff, highlighting the most important changes.
                        Focus on major updates, significant  code modifications, and important feature alterations. 
                        Omit minor or trivial details. If there are no major updates
                        don't write anything. Start with writing the file path.
                        The PR title is: {pr.title}
                        
                        The file diff is:
                        {chunk}"""
             }
        ],
        temperature=0
    )
    chunk_summary = response.choices[0].message.content.strip()
    logger.info(f"({pr.id}) Chunk summary: {chunk_summary}")
    return chunk_summary


async def generate_summary(pr: PullRequest, files_diff: list) -> str:
    # Split the file diff into smaller chunks if its too long
    tasks = []
    for file in files_diff:
        chunks = textwrap.wrap(file, 4 * 8000)  # Adjust the chunk size as needed
        tasks.extend([process_chunk(pr, chunk) for chunk in chunks])
    partial_summaries = await asyncio.gather(*tasks)

    # Combine partial summaries and generate a final summary
    combined_partial_summaries = '\n\n'.join(partial_summaries)
    final_summary_response = await client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are an expert programmer, and you are trying to summarize a pull request."},
            {"role": "user",
             "content": f"""
             Create a consolidated high-level summary based on the following files diff summaries of the PR.
             Synthesize these into a clear, concise overview that captures the main 
             objectives, significant changes, and overall impact of the PR, 
             while omitting minor details and technical specifics.
             
             The summary should be short and up to 3 sentences.
             
             The PR title is: {pr.title}
             
             The partial summaries are:
             '''{combined_partial_summaries}'''
             """}
        ],
        temperature=0.2
    )
    final_summary = final_summary_response.choices[0].message.content.strip()
    logger.info(f"({pr.id}) Final summary: {final_summary}")
    return final_summary


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
