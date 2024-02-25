import asyncio
from itertools import islice

from fastapi import BackgroundTasks
from github import GithubException, PullRequest, Repository

from app.logger import logger
from app.openai_client import openai_client

SUMMARY_MAGIC_PHRASE = "ai:summary"

SUMMARY_IN_PROGRESS_MESSAGE = "AI Generating summary..."

SUMMARY_SYSTEM_PROMPT = "You are an expert programmer, and you are trying to summarize a pull request."
FILE_SUMMARY_USER_PROMPT = f"""Take a look at this PR file changes.
             Summarize the rational behind the changes in this file in up to 3 sentences while addressing major changes only.  
             Take into consideration that import changes, variable, function, classes renaming are not important - don't summarize them.
             If there major changes, start with writing the file path.
             If there are no major changes, return just the string "No major changes".
            The PR title is: %s
            
            The file diff is:
            %s"""

FINAL_SUMMARY_USER_PROMPT = f"""
Based on the following PR summaries of the files diff.
Write in not more than 2 sentences what is the main goal of the PR.

The PR title is: %s

The partial summaries are:
'''%s'''
"""


def pr_summarize(repo: Repository, pr: PullRequest, background_tasks: BackgroundTasks) -> dict:
    try:
        issue = repo.get_issue(number=pr.number)
        new_body = pr.body.replace(SUMMARY_MAGIC_PHRASE, SUMMARY_IN_PROGRESS_MESSAGE)
        pr.edit(body=new_body)
        reaction = issue.create_reaction('eyes')
        eyes_reaction_id = reaction.id
        background_tasks.add_task(process_pr_for_summary, repo, pr, eyes_reaction_id)

        return {"message": "Sent PR to background summarize."}
    except GithubException as e:
        return {"error": str(e)}


async def process_pr_for_summary(repo: Repository, pr: PullRequest, eyes_reaction_id: int):
    files_diff = await get_pr_files_diff(pr)
    if files_diff:
        summary = await generate_summary(pr, files_diff)
        new_body = pr.body.replace(SUMMARY_IN_PROGRESS_MESSAGE,
                                summary + '\n🤖 AI generated summary')
        pr.edit(body=new_body)
        issue = repo.get_issue(number=pr.number)
        issue.delete_reaction(eyes_reaction_id)


async def get_pr_files_diff(pr: PullRequest) -> list:
    files = list(islice(pr.get_files(), 75))
    files_diff = []
    for file in files:
        path = file.filename
        patch = file.patch
        files_diff.append(f"File: {path}\n\n{patch}\n\n\n\n")

    return files_diff


async def summary_file_diff(pr: PullRequest, file_diff: str) -> str:
    response = await openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": FILE_SUMMARY_USER_PROMPT % (pr.title, file_diff)
            }
        ],
        temperature=0
    )
    file_summary = response.choices[0].message.content.strip()
    logger.info(f"({pr.id}) File summary: {file_summary}")

    if "No major changes" in file_summary:
        return ""
    return file_summary


async def generate_summary(pr: PullRequest, files_diff: list) -> str:
    # Split the file diff into smaller chunks if its too long
    tasks = []
    tasks.extend([summary_file_diff(pr, file) for file in files_diff])
    partial_summaries = await asyncio.gather(*tasks)

    # Combine partial summaries and generate a final summary
    combined_partial_summaries = '\n\n'.join(partial_summaries)
    final_summary_response = await openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": FINAL_SUMMARY_USER_PROMPT % (pr.title, combined_partial_summaries)
            }
        ],
        temperature=0,
        max_tokens=4000
    )
    final_summary = final_summary_response.choices[0].message.content.strip()
    logger.info(f"({pr.id}) Final summary: {final_summary}")
    return final_summary

