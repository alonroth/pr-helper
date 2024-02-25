from fastapi import BackgroundTasks
from github import GithubException, PullRequest, Repository, PullRequestComment

from app.openai_client import openai_client

SUGGEST_MAGIC_PHRASE = "ai:suggest"
SUGGEST_SYSTEM_PROMPT = "You are an expert programmer, and as part of a code review, you need to suggest a change in a file."
SUGGEST_USER_PROMPT = f"""
             Take a look at this diff hunk: %s.
             The file path is: %s.
             Here is the user request for the change: %s
             
             The user requested a change in line %s of the file.
             
             Answer in a Github suggestion format using the "```suggestion" markdown without any additional text.
             """


def comment_suggest(pr: PullRequest, payload: dict, background_tasks: BackgroundTasks):
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


async def process_comment_for_suggestion(pr: PullRequest, comment: PullRequestComment,
                                         user_request: str, eyes_reaction_id: int):
    response = await openai_client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": SUGGEST_SYSTEM_PROMPT},
            {"role": "user",
             "content": SUGGEST_USER_PROMPT % (
                 comment.diff_hunk, comment.path, user_request, comment.position
             )
             }
        ],
        temperature=0
    )

    suggestion = response.choices[0].message.content.strip()
    pr.create_review_comment_reply(body=suggestion, comment_id=comment.id)
    comment.delete_reaction(eyes_reaction_id)
