import asyncio
import base64
import hashlib
import hmac
from itertools import islice

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from github import Github, GithubException, Auth, PullRequest, Repository,\
    PullRequestComment
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

client = AsyncOpenAI(api_key=openai_api_key)

SUMMARY_MAGIC_PHRASE = "ai:summary"
SUGGEST_MAGIC_PHRASE = "ai:suggest"
SUMMARY_IN_PROGRESS_MESSAGE = "AI Generating summary..."


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

    try:
        action = payload['action']
        repo_name = payload['repository']['full_name']
        pr_number = payload['pull_request']['number']
        installation_id = payload['installation']['id']
    except KeyError:
        raise HTTPException(status_code=400, detail="Invalid payload - missing action, "
                                                    "repo name, PR number, "
                                                    "or installation ID")

    auth = Auth.AppAuth(os.environ.get('GITHUB_APP_ID'), github_private_key).get_installation_auth(installation_id)
    g = Github(auth=auth)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    # Check if it's a pull request that's been opened or edited
    if 'pull_request' in payload and action in ('opened', 'edited'):
        try:
            issue = repo.get_issue(number=pr_number)

            # Check for the token in the PR description
            if SUMMARY_MAGIC_PHRASE in pr.body:
                new_body = pr.body.replace(SUMMARY_MAGIC_PHRASE, SUMMARY_IN_PROGRESS_MESSAGE)
                pr.edit(body=new_body)
                reaction = issue.create_reaction('eyes')
                eyes_reaction_id = reaction.id
                background_tasks.add_task(process_pr_for_summary, repo, pr, eyes_reaction_id)
                return "Sent PR to background summarize."
        except GithubException as e:
            return {"error": str(e)}

    if 'comment' in payload and action in ('created', 'edited'):
        try:
            comment = pr.get_review_comment(payload['comment']['id'])
            body = comment.body

            if SUGGEST_MAGIC_PHRASE in body:
                trigger_index = body.find(SUGGEST_MAGIC_PHRASE)
                user_request = body[trigger_index + len('ai:suggest'):].strip()

                reaction = comment.create_reaction('eyes')
                eyes_reaction_id = reaction.id
                background_tasks.add_task(process_comment_for_suggestion, pr,
                                          comment, user_request, eyes_reaction_id)
                return "Sent comment to suggestion."
        except GithubException as e:
            return {"error": str(e)}

    return {"message": "Webhook received, but no action taken."}


async def process_comment_for_suggestion(pr: PullRequest, comment: PullRequestComment,
                                         user_request: str, eyes_reaction_id: int):
    response = await client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system",
             "content": "You are an expert programmer, and as part of a code review, you need to suggest a change in a file."},
            {"role": "user",
             "content": f"""
             Take a look at this diff hunk: {comment.diff_hunk}.
             The file path is: {comment.path}.
             Here is the user request for the change: {user_request}
             
             The user requested a change in line {comment.position} of the file.
             
             Answer in a Github suggestion format using the "```suggestion" markdown without any additional text.
             """
             }
        ],
        temperature=0
    )

    suggestion = response.choices[0].message.content.strip()
    pr.create_review_comment_reply(body=suggestion, comment_id=comment.id)
    comment.delete_reaction(eyes_reaction_id)


async def process_pr_for_summary(repo: Repository, pr: PullRequest, eyes_reaction_id: int):
    files_diff = await get_pr_files_diff(repo, pr)
    if files_diff:
        summary = await generate_summary(pr, files_diff)
        new_body = pr.body.replace(SUMMARY_IN_PROGRESS_MESSAGE,
                                '🤖 AI Generated Summary 🤖\n\n' + summary)
        pr.edit(body=new_body)
        issue = repo.get_issue(number=pr.number)
        issue.delete_reaction(eyes_reaction_id)


async def get_pr_files_diff(repo: Repository, pr: PullRequest) -> list:
    head_sha = pr.head.sha
    files = list(islice(pr.get_files(), 75))
    files_diff = []
    for file in files:
        path = file.filename
        patch = file.patch
        # try:
        #     contents = repo.get_contents(path, ref=head_sha)
        # except GithubException:
        #     logger.warning(f"({pr.id}) File {path} not found in repo")
        #     continue
        # content = contents.decoded_content.decode()
        files_diff.append(f"File: {path}\n\n{patch}\n\n\n\n")

    return files_diff


async def process_chunk(pr: PullRequest, chunk: str) -> str:
    response = await client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system",
             "content": "You are an expert programmer, and you are trying to summarize one file changes from a pull request."},
            {"role": "user",
             "content": f"""Take a look at this PR file changes.
             Summarize the rational behind the changes in this file in up to 3 sentences while addressing major changes only.  
             Take into consideration that import changes, variable, function, classes renaming are not important - don't summarize them.
             If there major changes, start with writing the file path.
             If there are no major changes, return just the string "No major changes".
            The PR title is: {pr.title}
            
            The file diff is:
            {chunk}"""
             }
        ],
        temperature=0
    )
    chunk_summary = response.choices[0].message.content.strip()
    logger.info(f"({pr.id}) Chunk summary: {chunk_summary}")

    if "No major changes" in chunk_summary:
        return ""
    return chunk_summary


async def generate_summary(pr: PullRequest, files_diff: list) -> str:
    # Split the file diff into smaller chunks if its too long
    tasks = []
    tasks.extend([process_chunk(pr, file) for file in files_diff])
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
             objectives and overall impact of the PR, while omitting minor details and technical specifics.
             
             The summary should be short, in bullet list and up to 8 list items but should be focused only on the PR main objectives so it can and should be less than 8 if it's not importantZ.
             Don't mention the PR title in the summary.
             Examples of unimportant details: import changes, introduction of new variables or constants, renaming of objects.
             Don't get into too much technical details.
             
             The PR title is: {pr.title}
             
             The partial summaries are:
             '''{combined_partial_summaries}'''
             """}
        ],
        temperature=0,
        max_tokens=4000
    )
    final_summary = final_summary_response.choices[0].message.content.strip()
    logger.info(f"({pr.id}) Final summary: {final_summary}")
    return final_summary


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
